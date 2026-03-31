# =============================================================================
# tb_weight_buffer.py
# Cocotb testbench for weight_buffer.sv (double-buffered, built-in sequencer)
#
# Architecture:
#   Shadow bank — host writes one column per cycle (wide write port)
#   Active bank — copy from shadow on load_trigger, sequencer reads to array
#   Internal FSM: IDLE → COPY (1 cyc) → SEQUENCE (8 cyc) → IDLE
#
# Tests:
#   T1 — Reset: ready=1, done=0, outputs zeroed
#   T2 — Basic load: identity matrix, verify column-by-column sequencer output
#   T3 — Ready timing: de-asserts for exactly 1 cycle during COPY
#   T4 — Done timing: pulses exactly once at end of sequencing
#   T5 — Double buffer isolation: shadow writes during SEQUENCE don't affect active
#   T6 — Random signed 8×8 matrix (seed=42)
#   T7 — Back-to-back: two loads without reset
#   T8 — Write blocked during COPY: wr_en gated by ready=0
#
# Run:    make  (from tb/weight_buffer/ directory)
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

def pack_row_weights(col_weights):
    """Pack 8 row weights (one column) into a single integer.
    col_weights[r] = weight for row r.
    Matches SystemVerilog packed dimension [ROWS-1:0][DATA_W-1:0]:
    row 0 in LSBs, row 7 in MSBs.
    """
    val = 0
    for r in range(ROWS):
        byte_val = int(col_weights[r]) & 0xFF
        val |= byte_val << (r * DATA_W)
    return val


def unpack_weight_out(val):
    """Unpack weight_out bus [ROWS-1:0][DATA_W-1:0] into list of 8 signed int8."""
    weights = []
    for r in range(ROWS):
        byte_val = (int(val) >> (r * DATA_W)) & 0xFF
        if byte_val >= 128:
            byte_val -= 256
        weights.append(byte_val)
    return weights


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


async def write_shadow(dut, W):
    """Write an 8×8 weight matrix to the shadow bank (one column per cycle).
    W[r][c] = weight at row r, column c.
    Wide write: all 8 rows for one column in a single cycle.
    """
    for c in range(COLS):
        col_data = [int(W[r][c]) for r in range(ROWS)]
        dut.wr_addr.value = c
        dut.wr_data.value = pack_row_weights(col_data)
        dut.wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.wr_en.value = 0


async def trigger_and_capture(dut):
    """Assert load_trigger, wait through COPY, capture 8 cycles of sequencer output.

    Timing: load_trigger (1 cyc) → COPY (1 cyc) → SEQUENCE (8 cyc)

    Returns:
        captured_weights[c] — list of 8 signed weights for column c
        captured_load[c]    — weight_load bus value during column c
    """
    # Assert load_trigger for 1 cycle
    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # COPY state (1 cycle) — outputs still idle
    await RisingEdge(dut.clk)

    # SEQUENCE state (8 cycles) — capture each column
    captured_weights = []
    captured_load    = []
    for _ in range(COLS):
        await RisingEdge(dut.clk)
        captured_weights.append(unpack_weight_out(dut.weight_out.value))
        captured_load.append(int(dut.weight_load.value))

    return captured_weights, captured_load


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────

@cocotb.test()
async def t1_reset(dut):
    """T1: After reset — ready=1, done=0, outputs zeroed."""
    await init_and_reset(dut)

    assert dut.ready.value        == 1, "ready should be 1 after reset"
    assert dut.done.value         == 0, "done should be 0 after reset"
    assert int(dut.weight_out.value)  == 0, "weight_out should be 0 after reset"
    assert int(dut.weight_load.value) == 0, "weight_load should be 0 after reset"

    dut._log.info("T1 PASSED — reset state correct")


@cocotb.test()
async def t2_basic_load(dut):
    """T2: Write identity matrix, trigger, verify column-by-column output."""
    await init_and_reset(dut)

    W = np.eye(ROWS, COLS, dtype=np.int8)
    await write_shadow(dut, W)

    captured_w, captured_l = await trigger_and_capture(dut)

    for c in range(COLS):
        expected = [int(W[r][c]) for r in range(ROWS)]
        assert captured_w[c] == expected, \
            f"Col {c}: expected {expected}, got {captured_w[c]}"
        assert captured_l[c] == (1 << c), \
            f"Col {c}: weight_load expected {1 << c:#04x}, got {captured_l[c]:#04x}"

    dut._log.info("T2 PASSED — identity matrix load and sequencer output")


@cocotb.test()
async def t3_ready_timing(dut):
    """T3: ready de-asserts for exactly 1 cycle during COPY, re-asserts for SEQUENCE."""
    await init_and_reset(dut)

    W = np.ones((ROWS, COLS), dtype=np.int8)
    await write_shadow(dut, W)

    # Trigger
    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # Now in COPY state — ready must be 0
    await RisingEdge(dut.clk)
    assert dut.ready.value == 0, "ready should be 0 during COPY"    

    # Now in SEQUENCE — ready must be back to 1
    await RisingEdge(dut.clk)
    assert dut.ready.value == 1, "ready should be 1 during SEQUENCE"

    dut._log.info("T3 PASSED — ready timing (0 during COPY, 1 during SEQUENCE)")


@cocotb.test()
async def t4_done_timing(dut):
    """T4: done pulses exactly once, on the last cycle of sequencing."""
    await init_and_reset(dut)

    W = np.ones((ROWS, COLS), dtype=np.int8)
    await write_shadow(dut, W)

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
    # cycle 0 = COPY, cycles 1–8 = SEQUENCE (col 0–7), done at cycle 8
    assert done_cycle == 8, f"done should fire at cycle 8, fired at {done_cycle}"

    dut._log.info("T4 PASSED — done pulses once at cycle 8")


@cocotb.test()
async def t5_double_buffer_isolation(dut):
    """T5: Writing new data to shadow during SEQUENCE must not affect active bank."""
    await init_and_reset(dut)

    # Load 42s into shadow, trigger
    W1 = np.full((ROWS, COLS), 42, dtype=np.int8)
    await write_shadow(dut, W1)

    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # Wait for COPY to finish
    await RisingEdge(dut.clk)

    # During SEQUENCE, overwrite shadow with -1s
    captured_w = []
    for c in range(COLS):
        dut.wr_addr.value = c
        dut.wr_data.value = pack_row_weights([-1] * ROWS)
        dut.wr_en.value   = 1
        await RisingEdge(dut.clk)
        captured_w.append(unpack_weight_out(dut.weight_out.value))
    dut.wr_en.value = 0

    # Sequencer must output 42s from active, not -1s from shadow
    for c in range(COLS):
        expected = [42] * ROWS
        assert captured_w[c] == expected, \
            f"Col {c}: expected {expected} (active), got {captured_w[c]}"

    dut._log.info("T5 PASSED — double buffer isolation (shadow ≠ active)")


@cocotb.test()
async def t6_random_matrix(dut):
    """T6: Random signed 8×8 weight matrix — verify all sequencer outputs."""
    await init_and_reset(dut)

    rng = np.random.default_rng(seed=42)
    W = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)

    await write_shadow(dut, W)
    captured_w, _ = await trigger_and_capture(dut)

    for c in range(COLS):
        expected = [int(W[r][c]) for r in range(ROWS)]
        assert captured_w[c] == expected, \
            f"Col {c}: expected {expected}, got {captured_w[c]}"

    dut._log.info("T6 PASSED — random signed matrix (seed=42)")


@cocotb.test()
async def t7_back_to_back(dut):
    """T7: Two consecutive load operations without reset."""
    await init_and_reset(dut)

    rng = np.random.default_rng(seed=99)

    for pass_num in range(2):
        W = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)
        await write_shadow(dut, W)
        cap, _ = await trigger_and_capture(dut)

        for c in range(COLS):
            expected = [int(W[r][c]) for r in range(ROWS)]
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
    W_orig = np.full((ROWS, COLS), 10, dtype=np.int8)
    await write_shadow(dut, W_orig)

    # Trigger — next posedge enters COPY
    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0

    # Now in COPY state — attempt to overwrite shadow col 0 with 99s
    dut.wr_addr.value = 0
    dut.wr_data.value = pack_row_weights([99] * ROWS)
    dut.wr_en.value   = 1
    await RisingEdge(dut.clk)       # COPY cycle; ready=0, write gated
    dut.wr_en.value = 0

    # Let current sequencing complete
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
    """T9: Write next matrix to shadow during SEQUENCE, trigger immediately after done.
    This is the double-buffering throughput test: overlap shadow fill with active readout,
    then verify the new matrix is correctly loaded on the next trigger.
    """
    await init_and_reset(dut)
 
    rng = np.random.default_rng(seed=77)
 
    # First matrix — load and trigger normally
    W1 = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)
    await write_shadow(dut, W1)
 
    dut.load_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.load_trigger.value = 0
 
    # Wait for COPY to finish — shadow is now free (ready=1)
    await RisingEdge(dut.clk)
 
    # Write W2 to shadow DURING sequencing of W1
    W2 = rng.integers(-128, 127, size=(ROWS, COLS), dtype=np.int8)
    for c in range(COLS):
        col_data = [int(W2[r][c]) for r in range(ROWS)]
        dut.wr_addr.value = c
        dut.wr_data.value = pack_row_weights(col_data)
        dut.wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.wr_en.value = 0
 
    # Sequencing of W1 should be done by now — trigger W2 immediately
    cap2, _ = await trigger_and_capture(dut)
 
    for c in range(COLS):
        expected = [int(W2[r][c]) for r in range(ROWS)]
        assert cap2[c] == expected, \
            f"Col {c}: expected W2 {expected}, got {cap2[c]}"
 
    dut._log.info("T9 PASSED — pipeline overlap (shadow written during SEQUENCE)")
 