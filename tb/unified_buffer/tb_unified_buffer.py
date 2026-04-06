# =============================================================================
# tb_unified_buffer.py
# Cocotb testbench for unified_buffer.sv (three-bank buffer with result readback)
#
# Architecture:
#   Write bank  — host/feedback writes one column per cycle (wide write port)
#   Active bank — copy from write on load_trigger, sequencer streams to array
#   Result bank — copy from write on store_trigger, host reads via rd_addr/rd_en
#   Internal FSM: IDLE → COPY → STREAM (8 cyc) → IDLE   (computation path)
#                 IDLE → STORE → IDLE                     (result capture path)
#
# Tests:
#   T1  — Reset: ready=1, load_done=0, outputs zeroed
#   T2  — Basic load: identity matrix, verify column-by-column streaming output
#   T3  — Ready timing: de-asserts during COPY and STORE, re-asserts for STREAM
#   T4  — load_done timing: pulses exactly once at end of streaming
#   T5  — Double buffer isolation: write bank writes during STREAM don't affect active
#   T6  — Random signed 8×8 matrix (seed=42)
#   T7  — Back-to-back: two loads without reset
#   T8  — Write blocked during COPY: wr_en gated by ready=0
#   T9  — Pipeline overlap: write bank written during STREAM, trigger immediately
#   T10 — Store and read: store_trigger copies write → result, host reads all columns
#   T11 — store_done timing: pulses exactly once during STORE
#   T12 — Result bank isolation: new writes to write bank don't affect result bank
#   T13 — Read gating: rd_data is zero when rd_en=0
#   T14 — Full pipeline: load → stream → store → read (end-to-end)
#
# Run:    make  (from tb/unified_buffer/ directory)
# Sim:    Verilator 5+, cocotb, numpy
# =============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
import numpy as np

# Design parameters — must match RTL
ROWS   = 8
COLS   = 8
DATA_W = 8
CLK_PERIOD_NS = 10


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def pack_row_data(col_values):
    """Pack 8 row values (one column) into a single integer.
    col_values[r] = value for row r.
    Matches SystemVerilog packed dimension [ROWS-1:0][DATA_W-1:0]:
    row 0 in LSBs, row 7 in MSBs.
    """
    val = 0
    for r in range(ROWS):
        byte_val = int(col_values[r]) & 0xFF
        val |= byte_val << (r * DATA_W)
    return val


def unpack_bus(val):
    """Unpack a [ROWS-1:0][DATA_W-1:0] bus into list of 8 signed int8."""
    result = []
    for r in range(ROWS):
        byte_val = (int(val) >> (r * DATA_W)) & 0xFF
        if byte_val >= 128:
            byte_val -= 256
        result.append(byte_val)
    return result


# ─────────────────────────────────────────────────────────────────────
# DUT drivers
# ─────────────────────────────────────────────────────────────────────

async def init_and_reset(dut):
    """Start clock and apply synchronous active-low reset."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())

    dut.rst_n.value         = 0
    dut.wr_addr.value       = 0
    dut.wr_data.value       = 0
    dut.wr_en.value         = 0
    dut.load_trigger.value  = 0
    dut.store_trigger.value = 0
    dut.rd_addr.value       = 0
    dut.rd_en.value         = 0

    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def write_bank_fill(dut, A):
    """Write an 8×8 matrix to the write bank (one column per cycle).
    A[r][c] = value at row r, column c.
    Wide write: all 8 rows for one column in a single cycle.
    """
    for c in range(COLS):
        col_data = [int(A[r][c]) for r in range(ROWS)]
        dut.wr_addr.value = c
        dut.wr_data.value = pack_row_data(col_data)
        dut.wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.wr_en.value = 0


async def trigger_load_and_capture(dut):
    """Assert load_trigger, wait through COPY, capture 8 cycles of streaming output.

    Timing: load_trigger (1 cyc) → COPY (1 cyc) → STREAM (8 cyc)

    Returns:
        captured_acts[c]  — list of 8 signed values for column c
        captured_valid[c] — valid signal value during column c
    """
    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # COPY state (1 cycle)
    await RisingEdge(dut.clk)

    # STREAM state (8 cycles) — capture each column
    captured_acts  = []
    captured_valid = []
    for _ in range(COLS):
        await RisingEdge(dut.clk)
        captured_acts.append(unpack_bus(dut.act_out.value))
        captured_valid.append(int(dut.valid.value))

    return captured_acts, captured_valid


async def trigger_store(dut):
    """Assert store_trigger, wait for STORE to complete (1 cycle)."""
    dut.store_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.store_trigger.value = 0
    # STORE state (1 cycle)
    await RisingEdge(dut.clk)


async def read_result_bank(dut):
    """Read all 8 columns from the result bank.
    rd_data is registered, so data appears one cycle after rd_en + rd_addr.

    Returns:
        result[c] — list of 8 signed int8 for column c
    """
    captured = []
    for c in range(COLS):
        dut.rd_addr.value = c
        dut.rd_en.value   = 1
        await RisingEdge(dut.clk)
        # Data appears after this clock edge — sample on next
        await RisingEdge(dut.clk)
        captured.append(unpack_bus(dut.rd_data.value))
    dut.rd_en.value = 0
    return captured


# ─────────────────────────────────────────────────────────────────────
# Tests — Original activation buffer tests (T1–T9), adapted
# ─────────────────────────────────────────────────────────────────────

@cocotb.test()
async def t1_reset(dut):
    """T1: After reset — ready=1, load_done=0, outputs zeroed."""
    await init_and_reset(dut)

    assert dut.ready.value             == 1, "ready should be 1 after reset"
    assert dut.load_done.value         == 0, "load_done should be 0 after reset"
    assert int(dut.act_out.value)      == 0, "act_out should be 0 after reset"
    assert int(dut.valid.value)        == 0, "valid should be 0 after reset"
    assert dut.store_done.value        == 0, "store_done should be 0 after reset"
    assert int(dut.rd_data.value)      == 0, "rd_data should be 0 after reset"

    dut._log.info("T1 PASSED — reset state correct")


@cocotb.test()
async def t2_basic_load(dut):
    """T2: Write identity matrix, trigger, verify column-by-column output."""
    await init_and_reset(dut)

    A = np.eye(ROWS, COLS, dtype=np.int8)
    await write_bank_fill(dut, A)

    captured_a, captured_v = await trigger_load_and_capture(dut)

    for c in range(COLS):
        expected = [int(A[r][c]) for r in range(ROWS)]
        assert captured_a[c] == expected, \
            f"Col {c}: expected {expected}, got {captured_a[c]}"
        assert captured_v[c] == (1 << ROWS) - 1, \
            f"Col {c}: valid expected 1, got {captured_v[c]}"

    dut._log.info("T2 PASSED — identity matrix load and streaming output")


@cocotb.test()
async def t3_ready_timing(dut):
    """T3: ready de-asserts during COPY and STORE, asserts during STREAM and IDLE."""
    await init_and_reset(dut)

    A = np.ones((ROWS, COLS), dtype=np.int8)
    await write_bank_fill(dut, A)

    # Test COPY path
    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    await RisingEdge(dut.clk)
    assert dut.ready.value == 0, "ready should be 0 during COPY"

    await RisingEdge(dut.clk)
    assert dut.ready.value == 1, "ready should be 1 during STREAM"

    # Let STREAM finish
    await ClockCycles(dut.clk, COLS - 1)

    # Test STORE path
    dut.store_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.store_trigger.value = 0

    await RisingEdge(dut.clk)
    assert dut.ready.value == 0, "ready should be 0 during STORE"

    await RisingEdge(dut.clk)
    assert dut.ready.value == 1, "ready should be 1 after STORE (back to IDLE)"

    dut._log.info("T3 PASSED — ready timing (0 during COPY/STORE, 1 during STREAM/IDLE)")


@cocotb.test()
async def t4_load_done_timing(dut):
    """T4: load_done pulses exactly once, on the last cycle of streaming."""
    await init_and_reset(dut)

    A = np.ones((ROWS, COLS), dtype=np.int8)
    await write_bank_fill(dut, A)

    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    done_count = 0
    done_cycle = -1
    for cycle in range(12):
        await RisingEdge(dut.clk)
        if dut.load_done.value == 1:
            done_count += 1
            done_cycle = cycle

    assert done_count == 1, f"load_done should pulse exactly once, got {done_count}"
    assert done_cycle == 8, f"load_done should fire at cycle 8, fired at {done_cycle}"

    dut._log.info("T4 PASSED — load_done pulses once at cycle 8")


@cocotb.test()
async def t5_double_buffer_isolation(dut):
    """T5: Writing new data to write bank during STREAM must not affect active bank."""
    await init_and_reset(dut)

    A1 = np.full((ROWS, COLS), 42, dtype=np.int8)
    await write_bank_fill(dut, A1)

    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    await RisingEdge(dut.clk)

    captured_a = []
    for c in range(COLS):
        dut.wr_addr.value = c
        dut.wr_data.value = pack_row_data([-1] * ROWS)
        dut.wr_en.value   = 1
        await RisingEdge(dut.clk)
        captured_a.append(unpack_bus(dut.act_out.value))
    dut.wr_en.value = 0

    for c in range(COLS):
        expected = [42] * ROWS
        assert captured_a[c] == expected, \
            f"Col {c}: expected {expected} (active), got {captured_a[c]}"

    dut._log.info("T5 PASSED — double buffer isolation (write bank ≠ active)")


@cocotb.test()
async def t6_random_matrix(dut):
    """T6: Random signed 8×8 matrix — verify all streaming outputs."""
    await init_and_reset(dut)

    rng = np.random.default_rng(seed=42)
    A = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)

    await write_bank_fill(dut, A)
    captured_a, _ = await trigger_load_and_capture(dut)

    for c in range(COLS):
        expected = [int(A[r][c]) for r in range(ROWS)]
        assert captured_a[c] == expected, \
            f"Col {c}: expected {expected}, got {captured_a[c]}"

    dut._log.info("T6 PASSED — random signed matrix (seed=42)")


@cocotb.test()
async def t7_back_to_back(dut):
    """T7: Two consecutive load operations without reset."""
    await init_and_reset(dut)

    rng = np.random.default_rng(seed=99)

    for pass_num in range(2):
        A = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)
        await write_bank_fill(dut, A)
        cap, _ = await trigger_load_and_capture(dut)

        for c in range(COLS):
            expected = [int(A[r][c]) for r in range(ROWS)]
            assert cap[c] == expected, \
                f"Pass {pass_num+1} col {c}: mismatch"

    dut._log.info("T7 PASSED — back-to-back load (seed=99, no reset)")


@cocotb.test()
async def t8_write_blocked_during_copy(dut):
    """T8: wr_en asserted during COPY cycle is ignored (ready=0 gates write)."""
    await init_and_reset(dut)

    A_orig = np.full((ROWS, COLS), 10, dtype=np.int8)
    await write_bank_fill(dut, A_orig)

    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    dut.wr_addr.value = 0
    dut.wr_data.value = pack_row_data([99] * ROWS)
    dut.wr_en.value   = 1
    await RisingEdge(dut.clk)
    dut.wr_en.value = 0

    await ClockCycles(dut.clk, COLS)

    cap, _ = await trigger_load_and_capture(dut)

    for c in range(COLS):
        expected = [10] * ROWS
        assert cap[c] == expected, \
            f"Col {c}: write bank should still be 10s, got {cap[c]}"

    dut._log.info("T8 PASSED — write blocked during COPY (ready=0)")


@cocotb.test()
async def t9_pipeline_overlap(dut):
    """T9: Write next matrix to write bank during STREAM, trigger immediately after."""
    await init_and_reset(dut)

    rng = np.random.default_rng(seed=77)

    A1 = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)
    await write_bank_fill(dut, A1)

    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    await RisingEdge(dut.clk)

    A2 = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)
    for c in range(COLS):
        col_data = [int(A2[r][c]) for r in range(ROWS)]
        dut.wr_addr.value = c
        dut.wr_data.value = pack_row_data(col_data)
        dut.wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.wr_en.value = 0

    cap2, _ = await trigger_load_and_capture(dut)

    for c in range(COLS):
        expected = [int(A2[r][c]) for r in range(ROWS)]
        assert cap2[c] == expected, \
            f"Col {c}: expected A2 {expected}, got {cap2[c]}"

    dut._log.info("T9 PASSED — pipeline overlap (write bank written during STREAM)")


# ─────────────────────────────────────────────────────────────────────
# Tests — New unified buffer features (T10–T14)
# ─────────────────────────────────────────────────────────────────────

@cocotb.test()
async def t10_store_and_read(dut):
    """T10: store_trigger copies write → result, host reads all 8 columns."""
    await init_and_reset(dut)

    rng = np.random.default_rng(seed=55)
    A = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)
    await write_bank_fill(dut, A)

    await trigger_store(dut)

    captured = await read_result_bank(dut)

    for c in range(COLS):
        expected = [int(A[r][c]) for r in range(ROWS)]
        assert captured[c] == expected, \
            f"Col {c}: expected {expected}, got {captured[c]}"

    dut._log.info("T10 PASSED — store and read all columns correct")


@cocotb.test()
async def t11_store_done_timing(dut):
    """T11: store_done pulses exactly once during STORE state."""
    await init_and_reset(dut)

    A = np.ones((ROWS, COLS), dtype=np.int8)
    await write_bank_fill(dut, A)

    dut.store_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.store_trigger.value = 0

    done_count = 0
    for cycle in range(4):
        await RisingEdge(dut.clk)
        if dut.store_done.value == 1:
            done_count += 1

    assert done_count == 1, f"store_done should pulse exactly once, got {done_count}"

    dut._log.info("T11 PASSED — store_done pulses once")


@cocotb.test()
async def t12_result_bank_isolation(dut):
    """T12: After store, new writes to write bank don't affect result bank."""
    await init_and_reset(dut)

    # Store 50s into result bank
    A1 = np.full((ROWS, COLS), 50, dtype=np.int8)
    await write_bank_fill(dut, A1)
    await trigger_store(dut)

    # Overwrite write bank with -1s
    A2 = np.full((ROWS, COLS), -1, dtype=np.int8)
    await write_bank_fill(dut, A2)

    # Result bank should still have 50s
    captured = await read_result_bank(dut)

    for c in range(COLS):
        expected = [50] * ROWS
        assert captured[c] == expected, \
            f"Col {c}: result bank should still be 50s, got {captured[c]}"

    dut._log.info("T12 PASSED — result bank isolation (write bank ≠ result)")


@cocotb.test()
async def t13_read_gating(dut):
    """T13: rd_data is zero when rd_en=0."""
    await init_and_reset(dut)

    # Store non-zero data into result bank
    A = np.full((ROWS, COLS), 77, dtype=np.int8)
    await write_bank_fill(dut, A)
    await trigger_store(dut)

    # Read with rd_en=0 — rd_data should be zero
    dut.rd_addr.value = 0
    dut.rd_en.value   = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    assert int(dut.rd_data.value) == 0, \
        f"rd_data should be 0 when rd_en=0, got {int(dut.rd_data.value)}"

    # Now read with rd_en=1 — should get 77s
    dut.rd_en.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    vals = unpack_bus(dut.rd_data.value)
    expected = [77] * ROWS
    assert vals == expected, \
        f"rd_data should be 77s when rd_en=1, got {vals}"

    dut.rd_en.value = 0

    dut._log.info("T13 PASSED — read gating (rd_data=0 when rd_en=0)")


@cocotb.test()
async def t14_full_pipeline(dut):
    """T14: Full pipeline — write, load, stream, store, read (end-to-end)."""
    await init_and_reset(dut)

    rng = np.random.default_rng(seed=123)
    A = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)

    # Step 1: Fill write bank
    await write_bank_fill(dut, A)

    # Step 2: Load and stream (verify streaming output)
    cap_stream, _ = await trigger_load_and_capture(dut)
    for c in range(COLS):
        expected = [int(A[r][c]) for r in range(ROWS)]
        assert cap_stream[c] == expected, \
            f"Stream col {c}: expected {expected}, got {cap_stream[c]}"

    # Step 3: Store write bank → result bank
    # (write bank still has the same data — it wasn't modified)
    await trigger_store(dut)

    # Step 4: Read back from result bank
    cap_read = await read_result_bank(dut)
    for c in range(COLS):
        expected = [int(A[r][c]) for r in range(ROWS)]
        assert cap_read[c] == expected, \
            f"Read col {c}: expected {expected}, got {cap_read[c]}"

    dut._log.info("T14 PASSED — full pipeline end-to-end correct")
    