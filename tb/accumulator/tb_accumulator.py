# =============================================================================
# tb_accumulator.py
# Cocotb testbench for accumulator.sv (8×8 register file with multi-pass tiling)
#
# Architecture:
#   8×8 × 32-bit register file — captures and accumulates partial sums
#   Per-column row counters — each column tracks its own result row
#   Internal FSM: IDLE (accumulate) → DRAIN (8 cyc, one row/cycle) → IDLE
#   Handshake: clear (zero all), drain_trigger (start output),
#              pass_done (all cols received), done (drain finished)
#
# Tests:
#   T1 — Reset: all outputs zero
#   T2 — Clear: zeroes registers after data accumulated
#   T3 — Single-pass aligned: all columns valid simultaneously, verify capture
#   T4 — Single-pass staggered: realistic wavefront, columns offset by 1 cycle
#   T5 — Drain sequencing: verify col_idx, acc_valid, row-by-row output
#   T6 — pass_done timing: pulses when all columns complete, counters auto-reset
#   T7 — Multi-pass accumulation: 2 passes, verify values add correctly
#   T8 — done timing: pulses on last drain cycle only
#   T9 — Back-to-back: clear → accumulate → drain → clear → accumulate → drain
#
# Run:    make  (from tb/accumulator/ directory)
# Sim:    Verilator 5+, cocotb, numpy
# =============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
import numpy as np

# Design parameters — must match RTL
ROWS   = 8
COLS   = 8
ACC_W  = 32
CLK_PERIOD_NS = 10

MASK_32   = (1 << ACC_W) - 1
MASK_COL  = (1 << COLS) - 1


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def pack_psum(values):
    """Pack 8 × 32-bit values into a single wide integer.
    values[c] maps to psum_in[c].
    Matches SystemVerilog packed dimension [COLS-1:0][ACC_W-1:0]:
    col 0 in LSBs, col 7 in MSBs.
    """
    packed = 0
    for c in range(COLS):
        v = int(values[c]) & MASK_32
        packed |= v << (c * ACC_W)
    return packed


def unpack_acc_out(val):
    """Unpack acc_out bus [COLS-1:0][ACC_W-1:0] into list of 8 signed int32."""
    result = []
    for r in range(ROWS):
        v = (int(val) >> (r * ACC_W)) & MASK_32
        if v >= (1 << (ACC_W - 1)):
            v -= (1 << ACC_W)
        result.append(v)
    return result


# ─────────────────────────────────────────────────────────────────────
# DUT drivers
# ─────────────────────────────────────────────────────────────────────

async def init_and_reset(dut):
    """Start clock and apply synchronous active-low reset."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())

    dut.rst_n.value         = 0
    dut.psum_in.value       = 0
    dut.valid_in.value      = 0
    dut.clear.value         = 0
    dut.drain_trigger.value = 0

    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def assert_clear(dut):
    """Assert clear for one cycle, then wait one cycle for it to take effect."""
    dut.clear.value = 1
    await RisingEdge(dut.clk)
    dut.clear.value = 0
    await RisingEdge(dut.clk)


async def drive_aligned(dut, matrix):
    """Drive 8 rows of psum data with all columns valid simultaneously.
    matrix[row][col] = psum value for that position.
    All 8 columns receive valid on the same cycle for each of the 8 rows.
    """
    for row in range(ROWS):
        row_vals = [int(matrix[row][c]) for c in range(COLS)]
        dut.psum_in.value  = pack_psum(row_vals)
        dut.valid_in.value = MASK_COL
        await RisingEdge(dut.clk)
    dut.valid_in.value = 0
    dut.psum_in.value  = 0


async def drive_staggered(dut, matrix):
    """Drive 8 rows of psum data with staggered valid (realistic wavefront).
    Column c's valid arrives c cycles after column 0, mimicking the
    systolic array's horizontal propagation delay.
    """
    total_cycles = ROWS + COLS - 1   # 15 cycles
    for cycle in range(total_cycles):
        valid_bits = 0
        row_vals = [0] * COLS
        for c in range(COLS):
            row = cycle - c
            if 0 <= row < ROWS:
                valid_bits |= (1 << c)
                row_vals[c] = int(matrix[row][c])
        dut.psum_in.value  = pack_psum(row_vals)
        dut.valid_in.value = valid_bits
        await RisingEdge(dut.clk)
    dut.valid_in.value = 0
    dut.psum_in.value  = 0


async def trigger_drain_and_capture(dut):
    """Assert drain_trigger, capture all 8 rows of output.

    Timing: drain_trigger (1 cyc) → DRAIN (8 cyc, one row per cycle)

    Returns:
        captured[row] — list of 8 signed int32 for that row
    """
    dut.drain_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.drain_trigger.value = 0

    captured = []
    for _ in range(COLS):
        await RisingEdge(dut.clk)
        captured.append(unpack_acc_out(dut.acc_out.value))

    return captured


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────

@cocotb.test()
async def t1_reset(dut):
    """T1: After reset — all outputs zero."""
    await init_and_reset(dut)

    assert int(dut.acc_out.value)   == 0, "acc_out should be 0 after reset"
    assert int(dut.acc_valid.value) == 0, "acc_valid should be 0 after reset"
    assert int(dut.pass_done.value) == 0, "pass_done should be 0 after reset"
    assert int(dut.drain_done.value)== 0, "drain_done should be 0 after reset"
    assert int(dut.col_idx.value)   == 0, "col_idx should be 0 after reset"

    dut._log.info("T1 PASSED — reset state correct")


@cocotb.test()
async def t2_clear(dut):
    """T2: Clear zeroes all registers after data has been accumulated."""
    await init_and_reset(dut)

    # Drive one row of data into column counters
    dut.psum_in.value  = pack_psum([100] * COLS)
    dut.valid_in.value = MASK_COL
    await RisingEdge(dut.clk)
    dut.valid_in.value = 0
    dut.psum_in.value  = 0
    await RisingEdge(dut.clk)

    # Clear everything
    await assert_clear(dut)

    # Drain and verify all zeros
    captured = await trigger_drain_and_capture(dut)
    for c in range(COLS):
        for r in range(ROWS):
            assert captured[c][r] == 0, \
                f"acc_reg[{r}][{c}] should be 0 after clear, got {captured[c][r]}"

    dut._log.info("T2 PASSED — clear zeroes all registers")


@cocotb.test()
async def t3_single_pass_aligned(dut):
    """T3: Single pass, all columns valid simultaneously — verify exact capture."""
    await init_and_reset(dut)
    await assert_clear(dut)

    # row*10 + col — distinct values everywhere
    matrix = np.array([[r * 10 + c for c in range(COLS)] for r in range(ROWS)],
                       dtype=np.int32)

    await drive_aligned(dut, matrix)
    # Wait for pass_done to propagate
    await RisingEdge(dut.clk)

    captured = await trigger_drain_and_capture(dut)
    for c in range(COLS):
        for r in range(ROWS):
            assert captured[c][r] == int(matrix[r][c]), \
                f"[{r}][{c}]: expected {matrix[r][c]}, got {captured[c][r]}"

    dut._log.info("T3 PASSED — single pass aligned capture correct")


@cocotb.test()
async def t4_single_pass_staggered(dut):
    """T4: Single pass, staggered valid (realistic wavefront) — verify capture."""
    await init_and_reset(dut)
    await assert_clear(dut)

    # (r+1)*(c+1) — distinct values
    matrix = np.array([[(r + 1) * (c + 1) for c in range(COLS)] for r in range(ROWS)],
                       dtype=np.int32)

    await drive_staggered(dut, matrix)
    # Allow pass_done to propagate and counters to reset
    await ClockCycles(dut.clk, 2)

    captured = await trigger_drain_and_capture(dut)
    for c in range(COLS):
        for r in range(ROWS):
            assert captured[c][r] == int(matrix[r][c]), \
                f"[{r}][{c}]: expected {matrix[r][c]}, got {captured[c][r]}"

    dut._log.info("T4 PASSED — staggered valid capture correct")


@cocotb.test()
async def t5_drain_sequencing(dut):
    """T5: Verify drain outputs rows in order with correct col_idx and acc_valid."""
    await init_and_reset(dut)
    await assert_clear(dut)

    matrix = np.array([[r * 100 + c for c in range(COLS)] for r in range(ROWS)],
                       dtype=np.int32)
    await drive_aligned(dut, matrix)
    await RisingEdge(dut.clk)

    # Start drain
    dut.drain_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.drain_trigger.value = 0

    for col in range(COLS):
        await RisingEdge(dut.clk)
        assert int(dut.acc_valid.value) == 1, \
            f"acc_valid should be high during drain (col {col})"
        assert int(dut.col_idx.value) == col, \
            f"col_idx: expected {col}, got {int(dut.col_idx.value)}"
        vals = unpack_acc_out(dut.acc_out.value)
        for r in range(ROWS):
            assert vals[r] == int(matrix[r][col]), \
                f"Drain col {col} row {r}: expected {matrix[r][col]}, got {vals[r]}"

    # After drain completes, acc_valid must be low
    await RisingEdge(dut.clk)
    assert int(dut.acc_valid.value) == 0, "acc_valid should be 0 after drain"

    dut._log.info("T5 PASSED — drain sequencing correct")


@cocotb.test()
async def t6_pass_done_timing(dut):
    """T6: pass_done pulses when all columns complete, counters auto-reset.
    Verified by running two passes without clear — values must accumulate.
    """
    await init_and_reset(dut)
    await assert_clear(dut)

    ones = np.ones((ROWS, COLS), dtype=np.int32)

    # Pass 1
    await drive_aligned(dut, ones)
    await RisingEdge(dut.clk)
    assert int(dut.pass_done.value) == 1, "pass_done should pulse after pass 1"
    await RisingEdge(dut.clk)

    # Pass 2 — counters should have auto-reset after pass_done
    await drive_aligned(dut, ones)
    await RisingEdge(dut.clk)

    # Drain — each cell should be 1 + 1 = 2
    captured = await trigger_drain_and_capture(dut)
    for c in range(COLS):
        for r in range(ROWS):
            assert captured[r][c] == 2, \
                f"After 2 passes of 1s: expected 2 at [{r}][{c}], got {captured[c][r]}"

    dut._log.info("T6 PASSED — pass_done timing and counter auto-reset correct")


@cocotb.test()
async def t7_multi_pass_accumulation(dut):
    """T7: Two tiling passes with distinct values — verify accumulation."""
    await init_and_reset(dut)
    await assert_clear(dut)

    rng = np.random.default_rng(seed=42)

    # Pass 1
    pass1 = rng.integers(-50, 50, size=(ROWS, COLS), dtype=np.int32)
    await drive_aligned(dut, pass1)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Pass 2
    pass2 = rng.integers(-50, 50, size=(ROWS, COLS), dtype=np.int32)
    await drive_aligned(dut, pass2)
    await RisingEdge(dut.clk)

    expected = pass1 + pass2
    captured = await trigger_drain_and_capture(dut)
    for c in range(COLS):
        for r in range(ROWS):
            assert captured[c][r] == int(expected[r][c]), \
                f"Multi-pass [{r}][{c}]: expected {expected[r][c]}, got {captured[c][r]}"

    dut._log.info("T7 PASSED — multi-pass accumulation correct (seed=42)")


@cocotb.test()
async def t8_done_timing(dut):
    """T8: done pulses exactly once, on the last cycle of drain."""
    await init_and_reset(dut)
    await assert_clear(dut)

    matrix = np.ones((ROWS, COLS), dtype=np.int32)
    await drive_aligned(dut, matrix)
    await RisingEdge(dut.clk)

    # Start drain
    dut.drain_trigger.value = 1
    await RisingEdge(dut.clk)
    dut.drain_trigger.value = 0

    # Count done pulses over the drain window
    done_count = 0
    done_cycle = -1
    for cycle in range(COLS + 2):
        await RisingEdge(dut.clk)
        if int(dut.drain_done.value) == 1:
            done_count += 1
            done_cycle = cycle

    assert done_count == 1, f"done should pulse exactly once, got {done_count}"
    assert done_cycle == COLS - 1, \
        f"done should fire at cycle {COLS - 1}, fired at {done_cycle}"

    dut._log.info("T8 PASSED — done pulses once on last drain cycle")


@cocotb.test()
async def t9_back_to_back(dut):
    """T9: Two independent operations — clear, accumulate, drain, repeat."""
    await init_and_reset(dut)

    rng = np.random.default_rng(seed=99)

    for pass_num in range(2):
        await assert_clear(dut)

        W = rng.integers(-100, 100, size=(ROWS, COLS), dtype=np.int32)
        await drive_aligned(dut, W)
        await RisingEdge(dut.clk)

        captured = await trigger_drain_and_capture(dut)
        for c in range(COLS):
            for r in range(ROWS):
                assert captured[c][r] == int(W[r][c]), \
                    f"Pass {pass_num + 1} [{r}][{c}]: expected {W[r][c]}, got {captured[c][r]}"

        # Wait for drain to finish before next iteration
        await RisingEdge(dut.clk)

    dut._log.info("T9 PASSED — back-to-back operations correct (seed=99)")
