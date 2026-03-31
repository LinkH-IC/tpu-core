# =============================================================================
# tb_systolic_array.py
# Cocotb testbench for systolic_array.sv (8×8 weight-stationary systolic array)
#
# Output relationship:  psum_out = W^T @ A
#   Column c accumulates vertically: sum_r W[r][c] * A[r][k]
#   This equals (W^T @ A)[c][k]
#
# Tests:
#   T1 — Reset: all outputs zero
#   T2 — Weight load, no activations: no spurious valid_out
#   T3 — Identity weights, single activation column
#   T4 — Full 8×8 matmul vs NumPy reference
#   T5 — Signed arithmetic (negative weights and activations)
#   T6 — valid_out column-to-column stagger timing
#   T7 — Back-to-back: reload weights, compute without reset
#
# Run:    make  (from tb/ directory)
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
ACC_W  = 32
CLK_PERIOD_NS = 10


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def to_uint(val, width=8):
    """Signed Python int → unsigned two's complement of `width` bits.
    Because the DUT ports are unsigned bit vectors.
    """
    return int(val) & ((1 << width) - 1)


def to_sint(val, width=32):
    """Unsigned raw bits → signed Python int of `width` bits."""
    val = int(val) & ((1 << width) - 1)
    return val - (1 << width) if val >= (1 << (width - 1)) else val


def pack_bus(values, width=8):
    """Pack a list of integers into one wide bus.
    values[0] → LSBs, values[N-1] → MSBs.
    Matches SystemVerilog packed dimension [N-1:0][width-1:0].
    """
    packed = 0
    for i, v in enumerate(values):
        packed |= to_uint(int(v), width) << (i * width)
    return packed


def unpack_psum(psum_raw, col):
    """Extract the signed 32-bit psum for `col` from the 256-bit psum_out bus.
    psum_out is packed as [COLS-1:0][ACC_W-1:0], so col 0 is the LSBs.
    """
    raw = (int(psum_raw) >> (col * ACC_W)) & ((1 << ACC_W) - 1)
    return to_sint(raw, ACC_W)


# ─────────────────────────────────────────────────────────────────────
# DUT drivers
# ─────────────────────────────────────────────────────────────────────

async def init_and_reset(dut):
    """Start clock and apply synchronous active-low reset."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())
    dut.rst_n.value       = 0
    dut.weight_in.value   = 0
    dut.weight_load.value = 0
    dut.act_in.value      = 0
    dut.valid_in.value    = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def load_weights(dut, W):
    """Load weight matrix W[row][col] into the PE array.

    Per-column loading: each cycle, assert weight_load[c] while driving
    weight_in[r] = W[r][c] for all rows simultaneously.
    After 8 cycles every PE holds its unique weight.
    """
    for c in range(COLS):
        dut.weight_in.value = pack_bus([int(W[r, c]) for r in range(ROWS)], DATA_W)
        dut.weight_load.value = 1 << c
        await RisingEdge(dut.clk)
    # De-assert after loading
    dut.weight_load.value = 0
    dut.weight_in.value   = 0
    await RisingEdge(dut.clk)


async def compute(dut, A):
    """Drive activation matrix A and capture results from the bottom edge.

    Activations are driven one column per cycle: act_in[r] = A[r][k] at cycle k.
    Internal stagger and PE pipeline produce results staggered across columns.

    Returns:
        R        — numpy array R[col][k] = (W^T @ A)[col][k]
        captured — list of per-column capture counts
    """
    num_act  = A.shape[1]
    R        = np.zeros((COLS, num_act), dtype=np.int64)
    captured = [0] * COLS

    # Drive phase + drain: pipeline depth is ROWS + COLS - 1 cycles
    # +4 for safety margin
    total = num_act + ROWS + COLS + 4

    for cyc in range(total):
        # ── Drive activations ──
        if cyc < num_act:
            dut.act_in.value   = pack_bus(
                [int(A[r, cyc]) for r in range(ROWS)], DATA_W)
            dut.valid_in.value = (1 << ROWS) - 1   # all rows valid
        else:
            dut.act_in.value   = 0
            dut.valid_in.value = 0

        await RisingEdge(dut.clk)

        # ── Capture outputs when valid ──
        vld = int(dut.valid_out.value)
        for c in range(COLS):
            if (vld >> c) & 1 and captured[c] < num_act:
                R[c, captured[c]] = unpack_psum(dut.psum_out.value, c)
                captured[c] += 1

    return R, captured


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────

@cocotb.test()
async def t1_reset(dut):
    """T1: After reset, psum_out and valid_out must all be zero."""
    await init_and_reset(dut)

    for c in range(COLS):
        val = unpack_psum(dut.psum_out.value, c)
        assert val == 0, f"psum_out[{c}] = {val}, expected 0 after reset"
    assert int(dut.valid_out.value) == 0, "valid_out != 0 after reset"

    dut._log.info("T1 PASSED — reset clears all outputs")


@cocotb.test()
async def t2_weight_load_no_act(dut):
    """T2: Load a full weight matrix, never assert valid_in → valid_out stays 0."""
    await init_and_reset(dut)

    W = np.arange(1, ROWS * COLS + 1, dtype=np.int8).reshape(ROWS, COLS)
    await load_weights(dut, W)

    for _ in range(20):
        await RisingEdge(dut.clk)
        assert int(dut.valid_out.value) == 0, "spurious valid_out after weight load"

    dut._log.info("T2 PASSED — no spurious valid_out")


@cocotb.test()
async def t3_identity(dut):
    """T3: W = I, activation = [1,2,...,8] → output equals input.
    W^T @ a = I^T @ a = a, so psum_out[c] should equal a[c].
    """
    await init_and_reset(dut)

    W = np.eye(ROWS, dtype=np.int8)
    a = np.arange(1, ROWS + 1, dtype=np.int8).reshape(ROWS, 1)

    await load_weights(dut, W)
    R, cap = await compute(dut, a)

    expected = W.astype(np.int64).T @ a.astype(np.int64)
    for c in range(COLS):
        assert cap[c] == 1, f"col {c}: captured {cap[c]} results, expected 1"
        assert R[c, 0] == expected[c, 0], \
            f"col {c}: got {R[c, 0]}, expected {expected[c, 0]}"

    dut._log.info("T3 PASSED — identity weight matrix")


@cocotb.test()
async def t4_full_matmul(dut):
    """T4: Random 8×8 W and A → verify all 64 outputs against NumPy W^T @ A."""
    await init_and_reset(dut)

    rng = np.random.default_rng(42)
    W = rng.integers(-10, 11, size=(ROWS, COLS)).astype(np.int8)
    A = rng.integers(-10, 11, size=(ROWS, COLS)).astype(np.int8)

    await load_weights(dut, W)
    R, cap = await compute(dut, A)

    expected = W.astype(np.int64).T @ A.astype(np.int64)

    errors = 0
    for c in range(COLS):
        assert cap[c] == COLS, f"col {c}: captured {cap[c]}, expected {COLS}"
        for k in range(COLS):
            if R[c, k] != expected[c, k]:
                dut._log.error(
                    f"MISMATCH R[{c}][{k}] = {R[c, k]}, expected {expected[c, k]}")
                errors += 1

    assert errors == 0, f"{errors} mismatches in 8×8 matmul"
    dut._log.info("T4 PASSED — full 8×8 matmul (seed=42)")


@cocotb.test()
async def t5_signed(dut):
    """T5: W = all -1, a = all -1 → each output = 8  (sum of 8 × (-1)×(-1))."""
    await init_and_reset(dut)

    W = np.full((ROWS, COLS), -1, dtype=np.int8)
    a = np.full((ROWS, 1),   -1, dtype=np.int8)

    await load_weights(dut, W)
    R, cap = await compute(dut, a)

    for c in range(COLS):
        assert cap[c] == 1, f"col {c}: captured {cap[c]}, expected 1"
        assert R[c, 0] == 8, f"col {c}: got {R[c, 0]}, expected 8"

    dut._log.info("T5 PASSED — signed arithmetic (-1 × -1 × 8 rows = 8)")


@cocotb.test()
async def t6_valid_timing(dut):
    """T6: With a single activation column, valid_out[c] must assert exactly
    c cycles after valid_out[0] — verifying the column stagger.
    """
    await init_and_reset(dut)

    W = np.eye(ROWS, dtype=np.int8)
    await load_weights(dut, W)

    first_high = [-1] * COLS
    total = ROWS + COLS + 4

    for cyc in range(total):
        # Drive one activation column at cycle 0 only
        if cyc == 0:
            dut.act_in.value   = pack_bus([1] * ROWS, DATA_W)
            dut.valid_in.value = (1 << ROWS) - 1
        else:
            dut.act_in.value   = 0
            dut.valid_in.value = 0

        await RisingEdge(dut.clk)

        vld = int(dut.valid_out.value)
        for c in range(COLS):
            if (vld >> c) & 1 and first_high[c] == -1:
                first_high[c] = cyc

    # All columns must have seen valid
    for c in range(COLS):
        assert first_high[c] != -1, f"valid_out[{c}] never asserted"

    # Column-to-column delta must be exactly 1 cycle
    for c in range(1, COLS):
        delta = first_high[c] - first_high[0]
        assert delta == c, \
            f"col {c}: delta from col 0 = {delta}, expected {c}"

    dut._log.info(f"T6 PASSED — valid_out stagger "
                  f"(first_high = {first_high})")


@cocotb.test()
async def t7_back_to_back(dut):
    """T7: Two full matmuls with different weights, no reset between them."""
    await init_and_reset(dut)

    rng = np.random.default_rng(99)

    for pass_num in range(2):
        W = rng.integers(-5, 6, size=(ROWS, COLS)).astype(np.int8)
        A = rng.integers(-5, 6, size=(ROWS, COLS)).astype(np.int8)

        await load_weights(dut, W)
        R, cap = await compute(dut, A)

        expected = W.astype(np.int64).T @ A.astype(np.int64)

        errors = 0
        for c in range(COLS):
            assert cap[c] == COLS, \
                f"Pass {pass_num+1} col {c}: captured {cap[c]}, expected {COLS}"
            for k in range(COLS):
                if R[c, k] != expected[c, k]:
                    dut._log.error(
                        f"Pass {pass_num+1} MISMATCH R[{c}][{k}] = "
                        f"{R[c, k]}, expected {expected[c, k]}")
                    errors += 1

        assert errors == 0, \
            f"Pass {pass_num+1}: {errors} mismatches"

    dut._log.info("T7 PASSED — back-to-back matmul (no reset)")
