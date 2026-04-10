"""
tb_iris.py — Real application test: Iris flower classification on the TPU core.
 
Loads pre-trained INT8 weights, biases, and 30 test samples from
iris_tpu_test.npz, runs each sample through the full two-layer MLP pipeline
with leaky ReLU activation and bias addition, and verifies bit-exact match
against the integer-only reference predictions.
 
Hardware pipeline per sample:
  1. Host writes W1 to weight buffer, b1 to bias_add, x to UB write bank (row 0)
  2. CLEAR → COMPUTE → DRAIN  (layer 1: leaky_relu(x @ W1 + b1) → UB write bank)
  3. Host writes W2 to weight buffer, b2 to bias_add
  4. CLEAR → COMPUTE → DRAIN → STORE  (layer 2: leaky_relu(h @ W2 + b2) → result bank)
  5. Host reads result bank row 0, columns 0–2 → argmax → predicted class
 
Tests:
  T1: Full inference — all 30 samples, bit-exact against y_ref
 
Run:  make  (from tb/iris/ directory, with iris_tpu_test.npz in same dir)
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge
import numpy as np
import os

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

CLASS_NAMES = ["setosa", "versicolor", "virginica"]


# ── Helpers ───────────────────────────────────────────────────

def to_uint(val, width=8):
    return int(val) & ((1 << width) - 1)


def to_sint(val, width=8):
    val = int(val) & ((1 << width) - 1)
    return val - (1 << width) if val >= (1 << (width - 1)) else val


def pack_row(values, width=8):
    packed = 0
    for i, v in enumerate(values):
        packed |= to_uint(v, width) << (i * width)
    return packed


def unpack_row(raw, count, width):
    mask = (1 << width) - 1
    return [to_sint((int(raw) >> (i * width)) & mask, width) for i in range(count)]


def load_test_data():
    """Load iris_tpu_test.npz from the test directory."""
    # Try multiple paths — cocotb may run from different working dirs
    candidates = [
        "iris_tpu_test.npz",
        os.path.join(os.path.dirname(__file__), "iris_tpu_test.npz"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return np.load(path)
    raise FileNotFoundError(
        f"iris_tpu_test.npz not found. Searched: {candidates}"
    )


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
    dut.bias_wr_addr.value  = 0
    dut.bias_wr_data.value  = 0
    dut.bias_wr_en.value    = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def write_weights(dut, W):
    """Write weight matrix so PE(r,c) = W[r][c].
    At address c, write column c of W."""
    for c in range(COLS):
        dut.wb_wr_addr.value = c
        dut.wb_wr_data.value = pack_row(W[:, c])
        dut.wb_wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.wb_wr_en.value = 0


async def write_activation_row(dut, x):
    """Write a single input vector x (length 8) into row 0 of the UB write bank.

    The UB write port writes one column per cycle: wr_data[r] at column wr_addr.
    To place x in row 0: at address k, write x[k] into row 0, zeros elsewhere.
    """
    for k in range(COLS):
        col_data = np.zeros(ROWS, dtype=np.int8)
        col_data[0] = x[k]
        dut.ub_wr_addr.value = k
        dut.ub_wr_data.value = pack_row(col_data)
        dut.ub_wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.ub_wr_en.value = 0


async def write_bias(dut, b):
    """Write bias vector (8 × int32) into bias_add register file."""
    for c in range(COLS):
        dut.bias_wr_addr.value = c
        dut.bias_wr_data.value = int(b[c]) & 0xFFFFFFFF
        dut.bias_wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.bias_wr_en.value = 0


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


async def read_result_row0(dut):
    """Read row 0 of the result bank (3 output neurons in columns 0–2)."""
    outputs = []
    for k in range(3):
        dut.ub_rd_addr.value = k
        dut.ub_rd_en.value   = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        vals = unpack_row(dut.ub_rd_data.value, ROWS, 8)
        outputs.append(vals[0])    # row 0 only
    dut.ub_rd_en.value = 0
    return outputs



# ── Tests ─────────────────────────────────────────────────────

@cocotb.test()
async def t1_full_iris_inference(dut):
    """Run all 30 Iris test samples through the TPU. Verify bit-exact against y_ref."""
    await init_and_reset(dut)

    data = load_test_data()
    W1       = data['W1']
    W2       = data['W2']
    b1         = data['b1']
    b2         = data['b2']
    shift1   = int(data['shift1'])
    shift2   = int(data['shift2'])
    leak_shift = int(data['leak_shift'])
    X_test   = data['X_test']
    y_test   = data['y_test']
    y_ref    = data['y_ref']
    n_samples = len(y_test)

    dut._log.info(f"Loaded {n_samples} samples, shift1={shift1}, shift2={shift2}, leak_shift={leak_shift}")

    # Pre-load W1 and b1 into weight buffer and bias registers
    await write_weights(dut, W1)
    await write_bias(dut, b1)

    correct_vs_ref  = 0
    correct_vs_true = 0
    mismatches      = []

    for i in range(n_samples):
        x = X_test[i]

        # Layer 1: load W1 (already in shadow from previous iteration or init)
        # For sample 0, W1 is already loaded above.
        # For subsequent samples, we must reload W1 before layer 1.
        if i > 0:
            await write_weights(dut, W1)
            await write_bias(dut, b1)

        dut.act_sel.value       = ACT_RELU
        dut.shift_amount.value  = shift1
        dut.leak_shift.value    = 0
        await write_activation_row(dut, x)
        await issue_cmd(dut, CMD_CLEAR)
        await issue_cmd(dut, CMD_COMPUTE)
        await issue_cmd(dut, CMD_DRAIN)
        # Hidden activations now in UB write bank

        # Layer 2: load W2
        await write_weights(dut, W2)
        await write_bias(dut, b2)
        dut.act_sel.value      = ACT_LEAKY_RELU
        dut.shift_amount.value = shift2
        await issue_cmd(dut, CMD_CLEAR)
        await issue_cmd(dut, CMD_COMPUTE)
        await issue_cmd(dut, CMD_DRAIN)
        await issue_cmd(dut, CMD_STORE)

        outputs = await read_result_row0(dut)
        predicted = int(np.argmax(outputs))

        ref_match  = (predicted == y_ref[i])
        true_match = (predicted == y_test[i])
        correct_vs_ref  += ref_match
        correct_vs_true += true_match

        status = "✓ REF_MATCH" if ref_match else "✗ MISMATCH"
        label  = CLASS_NAMES[predicted]
        dut._log.info(
            f"Sample {i:2d}: outputs={outputs}, "
            f"pred={predicted}({label}), ref={y_ref[i]}, true={y_test[i]} {status}"
        )

        if not ref_match:
            mismatches.append(i)

    dut._log.info(f"")
    dut._log.info(f"═══ RESULTS ═══")
    dut._log.info(f"Bit-exact vs y_ref:    {correct_vs_ref}/{n_samples}")
    dut._log.info(f"Correct vs y_test:     {correct_vs_true}/{n_samples}")

    if mismatches:
        dut._log.error(f"Hardware mismatches at samples: {mismatches}")

    assert correct_vs_ref == n_samples, (
        f"Hardware output does not match integer reference! "
        f"Mismatches at samples: {mismatches}"
    )

    dut._log.info(f"T1 PASS — all {n_samples} samples bit-exact with reference")
    