# =============================================================================
# tb_activation_buffer.py
# Cocotb testbench for activation_buffer.sv (double-buffered, built-in sequencer)
#
# Architecture:
#   Shadow bank — host writes one column per cycle (wide write port)
#   Active bank — copy from shadow on load_trigger, sequencer streams to array
#   Internal FSM: IDLE → COPY (1 cyc) → STREAM (8 cyc) → IDLE
#
# Tests:
#   T1 — Reset: ready=1, done=0, outputs zeroed
#   T2 — Basic load: identity matrix, verify column-by-column streaming output
#   T3 — Ready timing: de-asserts for exactly 1 cycle during COPY
#   T4 — Done timing: pulses exactly once at end of streaming
#   T5 — Double buffer isolation: shadow writes during STREAM don't affect active
#   T6 — Random signed 8×8 matrix (seed=42)
#   T7 — Back-to-back: two loads without reset
#   T8 — Write blocked during COPY: wr_en gated by ready=0
#   T9 — Pipeline overlap: shadow written during STREAM, trigger immediately
#
# Run:    make  (from tb/activation_buffer/ directory)
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

def pack_row_activations(col_activations):
    """Pack 8 row activations (one column) into a single integer.
    col_activations[r] = activation for row r.
    Matches SystemVerilog packed dimension [ROWS-1:0][DATA_W-1:0]:
    row 0 in LSBs, row 7 in MSBs.
    """
    val = 0
    for r in range(ROWS):
        byte_val = int(col_activations[r]) & 0xFF
        val |= byte_val << (r * DATA_W)
    return val


def unpack_act_out(val):
    """Unpack act_out bus [ROWS-1:0][DATA_W-1:0] into list of 8 signed int8."""
    acts = []
    for r in range(ROWS):
        byte_val = (int(val) >> (r * DATA_W)) & 0xFF
        if byte_val >= 128:
            byte_val -= 256
        acts.append(byte_val)
    return acts


# ─────────────────────────────────────────────────────────────────────
# DUT drivers
# ─────────────────────────────────────────────────────────────────────

async def init_and_reset(dut):
    """Start clock and apply synchronous active-low reset."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())

    dut.rst_n.value        = 0
    dut.wr_addr.value      = 0
    dut.wr_data.value      = 0
    dut.wr_en.value        = 0
    dut.load_trigger.value = 0

    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def write_shadow(dut, A):
    """Write an 8×8 activation matrix to the shadow bank (one column per cycle).
    A[r][c] = activation at row r, column c.
    Wide write: all 8 rows for one column in a single cycle.
    """
    for c in range(COLS):
        col_data = [int(A[r][c]) for r in range(ROWS)]
        dut.wr_addr.value = c
        dut.wr_data.value = pack_row_activations(col_data)
        dut.wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.wr_en.value = 0


async def trigger_and_capture(dut):
    """Assert load_trigger, wait through COPY, capture 8 cycles of streaming output.

    Timing: load_trigger (1 cyc) → COPY (1 cyc) → STREAM (8 cyc)

    Returns:
        captured_acts[c]  — list of 8 signed activations for column c
        captured_valid[c] — valid signal value during column c
    """
    # Assert load_trigger for 1 cycle
    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # COPY state (1 cycle) — outputs still idle
    await RisingEdge(dut.clk)

    # STREAM state (8 cycles) — capture each column
    captured_acts  = []
    captured_valid = []
    for _ in range(COLS):
        await RisingEdge(dut.clk)
        captured_acts.append(unpack_act_out(dut.act_out.value))
        captured_valid.append(int(dut.valid.value))

    return captured_acts, captured_valid


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────

@cocotb.test()
async def t1_reset(dut):
    """T1: After reset — ready=1, done=0, outputs zeroed."""
    await init_and_reset(dut)

    assert dut.ready.value        == 1, "ready should be 1 after reset"
    assert dut.done.value         == 0, "done should be 0 after reset"
    assert int(dut.act_out.value) == 0, "act_out should be 0 after reset"
    assert dut.valid.value        == 0, "valid should be 0 after reset"

    dut._log.info("T1 PASSED — reset state correct")


@cocotb.test()
async def t2_basic_load(dut):
    """T2: Write identity matrix, trigger, verify column-by-column output."""
    await init_and_reset(dut)

    A = np.eye(ROWS, COLS, dtype=np.int8)
    await write_shadow(dut, A)

    captured_a, captured_v = await trigger_and_capture(dut)

    for c in range(COLS):
        expected = [int(A[r][c]) for r in range(ROWS)]
        assert captured_a[c] == expected, \
            f"Col {c}: expected {expected}, got {captured_a[c]}"
        assert captured_v[c] == 1, \
            f"Col {c}: valid expected 1, got {captured_v[c]}"

    dut._log.info("T2 PASSED — identity matrix load and streaming output")


@cocotb.test()
async def t3_ready_timing(dut):
    """T3: ready de-asserts for exactly 1 cycle during COPY, re-asserts for STREAM."""
    await init_and_reset(dut)

    A = np.ones((ROWS, COLS), dtype=np.int8)
    await write_shadow(dut, A)

    # Trigger
    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # Now in COPY state — ready must be 0
    await RisingEdge(dut.clk)
    assert dut.ready.value == 0, "ready should be 0 during COPY"

    # Now in STREAM — ready must be back to 1
    await RisingEdge(dut.clk)
    assert dut.ready.value == 1, "ready should be 1 during STREAM"

    dut._log.info("T3 PASSED — ready timing (0 during COPY, 1 during STREAM)")


@cocotb.test()
async def t4_done_timing(dut):
    """T4: done pulses exactly once, on the last cycle of streaming."""
    await init_and_reset(dut)

    A = np.ones((ROWS, COLS), dtype=np.int8)
    await write_shadow(dut, A)

    # Trigger
    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # Count done pulses over the full operation
    done_count = 0
    done_cycle = -1
    for cycle in range(12):
        await RisingEdge(dut.clk)
        if dut.done.value == 1:
            done_count += 1
            done_cycle = cycle

    assert done_count == 1, f"done should pulse exactly once, got {done_count}"
    # cycle 0 = COPY, cycles 1–8 = STREAM (col 0–7), done at cycle 8
    assert done_cycle == 8, f"done should fire at cycle 8, fired at {done_cycle}"

    dut._log.info("T4 PASSED — done pulses once at cycle 8")


@cocotb.test()
async def t5_double_buffer_isolation(dut):
    """T5: Writing new data to shadow during STREAM must not affect active bank."""
    await init_and_reset(dut)

    # Load 42s into shadow, trigger
    A1 = np.full((ROWS, COLS), 42, dtype=np.int8)
    await write_shadow(dut, A1)

    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # Wait for COPY to finish
    await RisingEdge(dut.clk)

    # During STREAM, overwrite shadow with -1s
    captured_a = []
    for c in range(COLS):
        dut.wr_addr.value = c
        dut.wr_data.value = pack_row_activations([-1] * ROWS)
        dut.wr_en.value   = 1
        await RisingEdge(dut.clk)
        captured_a.append(unpack_act_out(dut.act_out.value))
    dut.wr_en.value = 0

    # Sequencer must output 42s from active, not -1s from shadow
    for c in range(COLS):
        expected = [42] * ROWS
        assert captured_a[c] == expected, \
            f"Col {c}: expected {expected} (active), got {captured_a[c]}"

    dut._log.info("T5 PASSED — double buffer isolation (shadow ≠ active)")


@cocotb.test()
async def t6_random_matrix(dut):
    """T6: Random signed 8×8 activation matrix — verify all streaming outputs."""
    await init_and_reset(dut)

    rng = np.random.default_rng(seed=42)
    A = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)

    await write_shadow(dut, A)
    captured_a, _ = await trigger_and_capture(dut)

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
        await write_shadow(dut, A)
        cap, _ = await trigger_and_capture(dut)

        for c in range(COLS):
            expected = [int(A[r][c]) for r in range(ROWS)]
            assert cap[c] == expected, \
                f"Pass {pass_num+1} col {c}: mismatch"

    dut._log.info("T7 PASSED — back-to-back load (seed=99, no reset)")


@cocotb.test()
async def t8_write_blocked_during_copy(dut):
    """T8: wr_en asserted during COPY cycle is ignored (ready=0 gates write).
    Verified by re-triggering — shadow must still hold original data.
    """
    await init_and_reset(dut)

    # Fill shadow with 10s
    A_orig = np.full((ROWS, COLS), 10, dtype=np.int8)
    await write_shadow(dut, A_orig)

    # Trigger — next posedge enters COPY
    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # Now in COPY state — attempt to overwrite shadow col 0 with 99s
    dut.wr_addr.value = 0
    dut.wr_data.value = pack_row_activations([99] * ROWS)
    dut.wr_en.value   = 1
    await RisingEdge(dut.clk)       # COPY cycle; ready=0, write gated
    dut.wr_en.value = 0

    # Let current streaming complete
    await ClockCycles(dut.clk, COLS)

    # Trigger again — if write was blocked, shadow still has 10s
    cap, _ = await trigger_and_capture(dut)

    for c in range(COLS):
        expected = [10] * ROWS
        assert cap[c] == expected, \
            f"Col {c}: shadow should still be 10s, got {cap[c]}"

    dut._log.info("T8 PASSED — write blocked during COPY (ready=0)")


@cocotb.test()
async def t9_pipeline_overlap(dut):
    """T9: Write next matrix to shadow during STREAM, trigger immediately after done.
    This is the double-buffering throughput test: overlap shadow fill with active readout,
    then verify the new matrix is correctly loaded on the next trigger.
    """
    await init_and_reset(dut)

    rng = np.random.default_rng(seed=77)

    # First matrix — load and trigger normally
    A1 = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)
    await write_shadow(dut, A1)

    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # Wait for COPY to finish — shadow is now free (ready=1)
    await RisingEdge(dut.clk)

    # Write A2 to shadow DURING streaming of A1
    A2 = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)
    for c in range(COLS):
        col_data = [int(A2[r][c]) for r in range(ROWS)]
        dut.wr_addr.value = c
        dut.wr_data.value = pack_row_activations(col_data)
        dut.wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.wr_en.value = 0

    # Streaming of A1 should be done by now — trigger A2 immediately
    cap2, _ = await trigger_and_capture(dut)

    for c in range(COLS):
        expected = [int(A2[r][c]) for r in range(ROWS)]
        assert cap2[c] == expected, \
            f"Col {c}: expected A2 {expected}, got {cap2[c]}"

    dut._log.info("T9 PASSED — pipeline overlap (shadow written during STREAM)")
