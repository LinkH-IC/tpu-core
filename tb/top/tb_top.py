"""
tb_top.py — Top-level integration testbench for the TPU core.

Convention (with transposed copy in unified buffer):
  - Weight buffer: PE(r,c) = W[r][c]  (load column c of W at addr c)
  - Unified buffer: transposed copy means streaming step k feeds row k of
    the write bank as the activation column → array computes A × W
  - Accumulator: acc_reg[k][c] = (A × W)[k][c]  — stores A×W directly
  - Drain: UB write bank = relu(A × W)
  - Single-vector: input x in ROW 0 of A, results in ROW 0 of output

Activation functions (act_sel):
  00 = ReLU          clip neg -> shift -> clamp [0, 127]
  01 = Leaky ReLU    shift -> leak neg -> clamp [-128, 127]
  10 = Bypass        shift -> clamp [-128, 127]
  11 = Binary Step   x > 0 -> 1, else -> 0
 
Tests:
  T1: Reset state
  T2: Random 8x8 matmul with ReLU -- verify result bank
  T3: Two-layer MLP inference (Iris-like 4->8->3) -- full feedback loop
  T4: Bypass -- verify negatives are preserved in result bank
  T5: Leaky ReLU -- verify negative attenuation
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge
import numpy as np

# ── Constants ─────────────────────────────────────────────────
ROWS = 8
COLS = 8

CMD_COMPUTE = 0
CMD_DRAIN   = 1
CMD_STORE   = 2
CMD_CLEAR   = 3

ACT_RELU        = 0
ACT_LEAKY_RELU  = 1
ACT_BYPASS      = 2
ACT_BINARY_STEP = 3

# ── Helpers ───────────────────────────────────────────────────

def to_uint(val, width=8):
    return int(val) & ((1 << width) - 1)


def to_sint(val, width=8):
    val = int(val) & ((1 << width) - 1)
    return val - (1 << width) if val >= (1 << (width - 1)) else val


def relu_elem(val, shift):
    v = int(val)
    if v < 0:
        v = 0
    v = v >> shift
    if v > 127:
        v = 127
    return np.int8(v)

def bypass_elem(val, shift):
    v = int(val) >> shift
    if v > 127:
        return np.int8(127)
    elif v < -128:
        return np.int8(-128)
    return np.int8(v)
 
 
def leaky_elem(val, shift, leak_shift):
    v = int(val) >> shift
    if v < 0:
        v = v >> leak_shift
    if v > 127:
        return np.int8(127)
    elif v < -128:
        return np.int8(-128)
    return np.int8(v)
 
 
def apply_act(M, act_sel, shift, leak_shift=0):
    out = np.zeros(M.shape, dtype=np.int8)
    for idx in np.ndindex(M.shape):
        v = int(M[idx])
        if act_sel == ACT_RELU:
            out[idx] = relu_elem(v, shift)
        elif act_sel == ACT_BYPASS:
            out[idx] = bypass_elem(v, shift)
        elif act_sel == ACT_LEAKY_RELU:
            out[idx] = leaky_elem(v, shift, leak_shift)
        elif act_sel == ACT_BINARY_STEP:
            out[idx] = np.int8(1) if v > 0 else np.int8(0)
    return out


def pack_row(values, width=8):
    packed = 0
    for i, v in enumerate(values):
        packed |= to_uint(v, width) << (i * width)
    return packed


def unpack_row(raw, count, width):
    mask = (1 << width) - 1
    return [to_sint((int(raw) >> (i * width)) & mask, width) for i in range(count)]


# ── Drivers ───────────────────────────────────────────────────

async def init_and_reset(dut):
    cocotb.start_soon(Clock(dut.clk, 10, "ns").start())
    dut.rst_n.value         = 0
    dut.wb_wr_addr.value    = 0
    dut.wb_wr_data.value    = 0
    dut.wb_wr_en.value      = 0
    dut.ub_wr_addr.value    = 0
    dut.ub_wr_data.value    = 0
    dut.ub_wr_en.value      = 0
    dut.ub_rd_addr.value    = 0
    dut.ub_rd_en.value      = 0
    dut.cmd.value           = 0
    dut.start.value         = 0
    dut.act_sel.value       = 0
    dut.shift_amount.value  = 0
    dut.leak_shift.value    = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def write_weights(dut, W):
    """Write weight matrix so PE(r,c) = W[r][c].

    At address c, we write COLUMN c of W: wr_data[r] = W[r][c].
    The weight buffer stores shadow[r][c] = W[r][c], and the sequencer
    loads PE(r,c) = W[r][c].
    """
    for c in range(COLS):
        dut.wb_wr_addr.value = c
        dut.wb_wr_data.value = pack_row(W[:, c])   # column c of W
        dut.wb_wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.wb_wr_en.value = 0


async def write_activations(dut, A):
    """Write activation matrix to UB write bank.

    At address k, write column k of A: wr_data[r] = A[r][k].
    After the transposed copy, streaming step k will feed row k of A.
    """
    for k in range(COLS):
        dut.ub_wr_addr.value = k
        dut.ub_wr_data.value = pack_row(A[:, k])
        dut.ub_wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.ub_wr_en.value = 0


async def issue_cmd(dut, cmd, timeout=600):
    dut.cmd.value   = cmd
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    for _ in range(timeout):
        await FallingEdge(dut.clk)
        if int(dut.done.value) == 1:
            await RisingEdge(dut.clk)
            return
        await RisingEdge(dut.clk)
    raise TimeoutError(f"Command {cmd} did not complete in {timeout} cycles")


async def read_result_bank(dut):
    """Read 8×8 INT8 from unified buffer result bank (registered read)."""
    R = np.zeros((ROWS, COLS), dtype=np.int8)
    for k in range(COLS):
        dut.ub_rd_addr.value = k
        dut.ub_rd_en.value   = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        vals = unpack_row(dut.ub_rd_data.value, ROWS, 8)
        for r in range(ROWS):
            R[r][k] = vals[r]
    dut.ub_rd_en.value = 0
    return R

# ── Tests ─────────────────────────────────────────────────────

@cocotb.test()
async def t1_reset(dut):
    """After reset: done=0, wb_ready=1, ub_ready=1."""
    await init_and_reset(dut)
    await FallingEdge(dut.clk)
    assert int(dut.done.value)     == 0, "done != 0"
    assert int(dut.wb_ready.value) == 1, "wb_ready != 1"
    assert int(dut.ub_ready.value) == 1, "ub_ready != 1"
    dut._log.info("T1 PASS — reset state correct")


@cocotb.test()
async def t2_single_matmul(dut):
    """Random 8×8 A and W (seed=42) — verify accumulator and result bank.

    Array computes A × W.
    Accumulator holds A×W directly (32-bit).
    Result bank holds relu(A×W) (INT8).
    """
    await init_and_reset(dut)

    rng = np.random.default_rng(42)
    W = rng.integers(-10, 11, size=(8, 8)).astype(np.int8)
    A = rng.integers(-10, 11, size=(8, 8)).astype(np.int8)
    shift = 2

    dut.act_sel.value       = ACT_RELU
    dut.shift_amount.value  = shift
    dut.leak_shift.value    = 0

    expected_32 = A.astype(np.int32) @ W.astype(np.int32)
    expected_8  = apply_act(expected_32, ACT_RELU, shift)

    await write_weights(dut, W)
    await write_activations(dut, A)
    await issue_cmd(dut, CMD_CLEAR)
    await issue_cmd(dut, CMD_COMPUTE)
    await issue_cmd(dut, CMD_DRAIN)
    await issue_cmd(dut, CMD_STORE)


    result_8 = await read_result_bank(dut)
 
    for r in range(ROWS):
        for c in range(COLS):
            assert result_8[r][c] == expected_8[r][c], (
                f"RESULT[{r}][{c}] = {result_8[r][c]}, expected {expected_8[r][c]}"
            )
    dut._log.info("T2 PASS -- single matmul AxW with ReLU verified")


@cocotb.test()
async def t3_iris_two_layer(dut):
    """Two-layer MLP: 4 inputs → 8 hidden (ReLU) → 3 outputs.

    Convention: input x as ROW 0 of A, right-multiply by W.
      Layer 1:  hidden = relu(x @ W1)     — shape (1,8)
      Layer 2:  output = relu(hidden @ W2) — shape (1,3), only cols 0–2 used

    Verifies the full feedback loop:
      Layer 1: host loads W1 + input → CLEAR → COMPUTE → DRAIN
      Layer 2: host loads W2 only → CLEAR → COMPUTE → DRAIN → STORE → read
    """
    await init_and_reset(dut)

    # ── Layer 1 setup ─────────────────────────────────────────
    #   W1 is (4,8) — 4 inputs, 8 hidden neurons.
    #   Padded to (8,8) with zero rows 4–7.
    W1_raw = np.array([
        [ 2,  0, -1,  1,  1, -1,  0,  3],
        [ 1,  3,  0, -2,  1,  2,  2,  0],
        [-1,  0,  2,  0,  1, -1, -3,  0],
        [ 0, -1,  1,  3,  1,  2,  1, -2],
    ], dtype=np.int8)   # shape (4, 8)

    W1 = np.zeros((8, 8), dtype=np.int8)
    W1[:4, :] = W1_raw

    x = np.array([5, 3, 2, 1], dtype=np.int8)

    # Activation matrix: x in ROW 0, spread across columns 0–3
    A1 = np.zeros((8, 8), dtype=np.int8)
    A1[0, :4] = x

    shift1 = 0
    dut.act_sel.value       = ACT_RELU
    dut.shift_amount.value  = shift1
    dut.leak_shift.value    = 0

    # Expected: A1 × W1 — only row 0 is non-zero
    hidden_32 = A1.astype(np.int32) @ W1.astype(np.int32)
    hidden_relu = apply_act(hidden_32, ACT_RELU, shift1)

    dut._log.info(f"Layer 1 — hidden_32 row 0 = {hidden_32[0, :].tolist()}")
    dut._log.info(f"Layer 1 — hidden_relu row 0 = {hidden_relu[0, :].tolist()}")

    # ── Layer 1 execution ─────────────────────────────────────
    await write_weights(dut, W1)
    await write_activations(dut, A1)

    await issue_cmd(dut, CMD_CLEAR)
    await issue_cmd(dut, CMD_COMPUTE)
    await issue_cmd(dut, CMD_DRAIN)

    # ── Layer 2 setup ─────────────────────────────────────────
    #   W2 is (8,3) — 8 hidden inputs, 3 output classes.
    #   Padded to (8,8) with zero columns 3–7.
    W2_raw = np.array([
        [1, 0, 1],
        [2, 1, 0],
        [1, 0, 2],
        [0, 2, 1],
        [1, 0, 0],
        [0, 1, 0],
        [0, 1, 0],
        [1, 0, 1],
    ], dtype=np.int8)   # shape (8, 3)

    W2 = np.zeros((8, 8), dtype=np.int8)
    W2[:, :3] = W2_raw

    shift2 = 0
    dut.shift_amount.value = shift2

    # After drain, UB write bank = relu(A1 × W1) = hidden_relu.
    # Layer 2 activation = hidden_relu (already in UB write bank).
    expected_out_32 = hidden_relu.astype(np.int32) @ W2.astype(np.int32)
    expected_out_8  = apply_act(expected_out_32, ACT_RELU, shift2)

    dut._log.info(f"Layer 2 — expected row 0, cols 0–2: {expected_out_32[0, :3].tolist()}")

    # ── Layer 2 execution (only write W2, activations from drain) ──
    await write_weights(dut, W2)

    await issue_cmd(dut, CMD_CLEAR)
    await issue_cmd(dut, CMD_COMPUTE)
    await issue_cmd(dut, CMD_DRAIN)
    await issue_cmd(dut, CMD_STORE)

    result = await read_result_bank(dut)

    # ── Verify 3 output neurons (row 0, columns 0–2) ─────────
    outputs  = [int(result[0][c]) for c in range(3)]
    expected = [int(expected_out_8[0][c]) for c in range(3)]

    dut._log.info(f"T3 — got      {outputs}")
    dut._log.info(f"T3 — expected {expected}")

    for c in range(3):
        assert result[0][c] == expected_out_8[0][c], (
            f"OUTPUT[{c}] = {result[0][c]}, expected {expected_out_8[0][c]}"
        )

    predicted = int(np.argmax(outputs))
    dut._log.info(f"T3 PASS — Iris inference complete. "
                  f"Outputs: {outputs}, predicted class: {predicted}")


@cocotb.test()
async def t4_bypass(dut):
    """Bypass activation -- negatives preserved in result bank."""
    await init_and_reset(dut)
 
    W = np.eye(8, dtype=np.int8)
    A = np.array([
        [ 10, -20,  30, -40,  50, -60,  70, -80],
        [-10,  20, -30,  40, -50,  60, -70,  80],
        [  0,   0,   0,   0,   0,   0,   0,   0],
        [  0,   0,   0,   0,   0,   0,   0,   0],
        [  0,   0,   0,   0,   0,   0,   0,   0],
        [  0,   0,   0,   0,   0,   0,   0,   0],
        [  0,   0,   0,   0,   0,   0,   0,   0],
        [  0,   0,   0,   0,   0,   0,   0,   0],
    ], dtype=np.int8)
 
    shift = 0
    dut.act_sel.value       = ACT_BYPASS
    dut.shift_amount.value  = shift
    dut.leak_shift.value    = 0
 
    expected_32 = A.astype(np.int32) @ W.astype(np.int32)
    expected_8  = apply_act(expected_32, ACT_BYPASS, shift)
 
    await write_weights(dut, W)
    await write_activations(dut, A)
    await issue_cmd(dut, CMD_CLEAR)
    await issue_cmd(dut, CMD_COMPUTE)
    await issue_cmd(dut, CMD_DRAIN)
    await issue_cmd(dut, CMD_STORE)
 
    result = await read_result_bank(dut)
 
    neg_count = 0
    for r in range(ROWS):
        for c in range(COLS):
            assert result[r][c] == expected_8[r][c], (
                f"RESULT[{r}][{c}] = {result[r][c]}, expected {expected_8[r][c]}"
            )
            if result[r][c] < 0:
                neg_count += 1
 
    assert neg_count > 0, "No negative values in result -- bypass not working"
    dut._log.info(f"T4 PASS -- bypass verified, {neg_count} negative values preserved")
 
 
@cocotb.test()
async def t5_leaky_relu(dut):
    """Leaky ReLU -- verify negative attenuation.
 
    With leak_shift=2, negatives are divided by 4 (right-shift by 2).
    Positives pass through unchanged (after shift+clamp).
    """
    await init_and_reset(dut)
 
    W = np.eye(8, dtype=np.int8)
    A = np.array([
        [ 100, -100,  50, -50,  25, -25,  10, -10],
        [ -80,   80, -40,  40, -20,  20, -10,  10],
        [   0,    0,   0,   0,   0,   0,   0,   0],
        [   0,    0,   0,   0,   0,   0,   0,   0],
        [   0,    0,   0,   0,   0,   0,   0,   0],
        [   0,    0,   0,   0,   0,   0,   0,   0],
        [   0,    0,   0,   0,   0,   0,   0,   0],
        [   0,    0,   0,   0,   0,   0,   0,   0],
    ], dtype=np.int8)
 
    shift = 0
    leak = 2
    dut.act_sel.value       = ACT_LEAKY_RELU
    dut.shift_amount.value  = shift
    dut.leak_shift.value    = leak
 
    expected_32 = A.astype(np.int32) @ W.astype(np.int32)
    expected_8  = apply_act(expected_32, ACT_LEAKY_RELU, shift, leak)
 
    await write_weights(dut, W)
    await write_activations(dut, A)
    await issue_cmd(dut, CMD_CLEAR)
    await issue_cmd(dut, CMD_COMPUTE)
    await issue_cmd(dut, CMD_DRAIN)
    await issue_cmd(dut, CMD_STORE)
 
    result = await read_result_bank(dut)
 
    for r in range(2):
        for c in range(COLS):
            assert result[r][c] == expected_8[r][c], (
                f"RESULT[{r}][{c}] = {result[r][c]}, expected {expected_8[r][c]}"
            )
 
    # Spot-check: -100 with leak_shift=2 -> -100 >> 2 = -25
    assert result[0][1] == -25, f"Leaky(-100, leak=2) = {result[0][1]}, expected -25"
    # Spot-check: 100 passes through unchanged
    assert result[0][0] == 100, f"Positive(100) = {result[0][0]}, expected 100"
 
    dut._log.info(f"T5 PASS -- leaky ReLU verified (leak_shift={leak})")
 