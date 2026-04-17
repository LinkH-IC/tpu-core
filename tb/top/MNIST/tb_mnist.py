"""
tb_mnist.py — MNIST handwritten digit recognition on the TPU core.

Loads pre-trained INT8 weights, biases, and 100 test samples from
mnist_tpu_test.npz, runs inference through the full two-layer MLP with
input tiling, and verifies bit-exact match against integer-only reference.

Network:  784 → 64 (ReLU) → 10 (bypass) → argmax

Tiling strategy:
  Layer 1:  [1×784] × [784×64]
    - Inner dim: 784/8 = 98 COMPUTE passes per output group (accumulator tiles)
    - Output dim: 64/8  = 8 column groups (weight reload per group)
    - Total: 98 × 8 = 784 COMPUTE commands per sample

  Layer 2:  [1×64] × [64×16]   (10 real + 6 zero-padded output columns)
    - Inner dim: 64/8 = 8 passes
    - Output dim: 16/8 = 2 column groups
    - Total: 8 × 2 = 16 COMPUTE commands per sample

Hardware pipeline per column group:
  1. Host writes weight tile [8×8] and bias chunk [8] 
  2. CLEAR accumulator
  3. For each inner pass:
     a. Host writes activation chunk [8] to UB write bank
     b. COMPUTE — weights load, activations stream, accumulator tiles
  4. DRAIN — bias add + activation + shift → UB write bank
  5. STORE — write bank → result bank
  6. Host reads column group outputs from result bank

Tests:
  T1: Single-sample — 100 samples, one row active, 7 rows idle
  T2: Batched — 100 samples in batches of 8, all rows active

Run:  make  (from tb/top/mnist/ directory)
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

ACT_RELU   = 0
ACT_BYPASS = 2

# Layer 1 tiling parameters
L1_INNER    = 98    # 784 / 8
L1_COLGRPS  = 8     # 64 / 8

# Layer 2 tiling parameters
L2_INNER    = 8     # 64 / 8
L2_COLGRPS  = 2     # 16 / 8  (10 real outputs, padded to 16)
L2_REAL_OUT = 10    # only first 10 outputs are real


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
    """Load mnist_tpu_test.npz from the test directory."""
    candidates = [
        "mnist_tpu_test.npz",
        os.path.join(os.path.dirname(__file__), "mnist_tpu_test.npz"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return np.load(path)
    raise FileNotFoundError(
        f"mnist_tpu_test.npz not found. Searched: {candidates}"
    )


def load_custom_data():
    """Load mnist_custom_test.npz from the test directory."""
    candidates = [
        "mnist_custom_test.npz",
        os.path.join(os.path.dirname(__file__), "mnist_custom_test.npz"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return np.load(path)
    raise FileNotFoundError(
        f"mnist_custom_test.npz not found. Searched: {candidates}"
    )


def get_sim_cycles(dut):
    """Current simulation time in clock cycles (10 ns period)."""
    return cocotb.utils.get_sim_time("ns") // 10


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


async def write_weights(dut, W_tile):
    """Write an 8×8 weight tile to the weight buffer shadow bank.
    At address c, write column c of W_tile (all 8 rows packed)."""
    for c in range(COLS):
        dut.wb_wr_addr.value = c
        dut.wb_wr_data.value = pack_row(W_tile[:, c])
        dut.wb_wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.wb_wr_en.value = 0


async def write_activation_row(dut, x_chunk):
    """Write an 8-element activation chunk into row 0 of the UB write bank.
    At column k, row 0 = x_chunk[k], rows 1-7 = 0."""
    for k in range(COLS):
        col_data = np.zeros(ROWS, dtype=np.int8)
        col_data[0] = x_chunk[k]
        dut.ub_wr_addr.value = k
        dut.ub_wr_data.value = pack_row(col_data)
        dut.ub_wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.ub_wr_en.value = 0


async def write_activation_batch(dut, x_chunks):
    """Write 8-element activation chunks for up to 8 samples.
    x_chunks: [n_samples, 8] — row r = sample r's chunk.
    At column k, row r = x_chunks[r][k]."""
    n = x_chunks.shape[0]
    for k in range(COLS):
        col_data = np.zeros(ROWS, dtype=np.int8)
        for r in range(n):
            col_data[r] = x_chunks[r, k]
        dut.ub_wr_addr.value = k
        dut.ub_wr_data.value = pack_row(col_data)
        dut.ub_wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.ub_wr_en.value = 0


async def write_bias(dut, b_chunk):
    """Write 8-element INT32 bias chunk into the bias_add register file."""
    for c in range(COLS):
        dut.bias_wr_addr.value = c
        dut.bias_wr_data.value = int(b_chunk[c]) & 0xFFFFFFFF
        dut.bias_wr_en.value   = 1
        await RisingEdge(dut.clk)
    dut.bias_wr_en.value = 0


async def issue_cmd(dut, cmd, timeout=2000):
    """Issue a command and wait for done."""
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


async def read_result_rows(dut, n_rows, n_cols):
    """Read n_rows × n_cols from the result bank.
    Returns: list of lists [row][col] of signed INT8 values."""
    result = [[0] * n_cols for _ in range(n_rows)]
    for k in range(n_cols):
        dut.ub_rd_addr.value = k
        dut.ub_rd_en.value   = 1
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        vals = unpack_row(dut.ub_rd_data.value, ROWS, 8)
        for r in range(n_rows):
            result[r][k] = vals[r]
    dut.ub_rd_en.value = 0
    return result


# ── Tiled Layer Execution ────────────────────────────────────

async def run_layer_single(dut, x, W, b, shift, act_sel, n_inner, n_col_groups):
    """Run one tiled layer for a single sample.

    Args:
        x:           [input_dim] INT8 activation vector
        W:           [input_dim, output_dim] INT8 weight matrix
        b:           [output_dim] INT32 bias vector
        shift:       right-shift amount for requantization
        act_sel:     activation function select (ACT_RELU or ACT_BYPASS)
        n_inner:     number of inner-dimension passes (input_dim / 8)
        n_col_groups: number of output column groups (output_dim / 8)

    Returns: [output_dim] INT8 output vector
    """
    dut.act_sel.value      = act_sel
    dut.shift_amount.value = shift

    output = np.zeros(n_col_groups * COLS, dtype=np.int8)

    for cg in range(n_col_groups):
        # Load bias for this column group
        await write_bias(dut, b[cg * 8:(cg + 1) * 8])

        # Clear accumulator for fresh column group
        await issue_cmd(dut, CMD_CLEAR)

        # Inner-dimension tiling: accumulate across all passes
        for ip in range(n_inner):
            w_tile  = W[ip * 8:(ip + 1) * 8, cg * 8:(cg + 1) * 8]
            x_chunk = x[ip * 8:(ip + 1) * 8]

            await write_weights(dut, w_tile)
            await write_activation_row(dut, x_chunk)
            await issue_cmd(dut, CMD_COMPUTE)

        # Drain through activation → write bank → result bank
        await issue_cmd(dut, CMD_DRAIN)
        await issue_cmd(dut, CMD_STORE)

        # Read row 0 (single sample) from result bank
        rows = await read_result_rows(dut, 1, COLS)
        output[cg * 8:(cg + 1) * 8] = rows[0]

    return output


async def run_layer_batch(dut, X_batch, W, b, shift, act_sel, n_inner, n_col_groups):
    """Run one tiled layer for a batch of up to 8 samples.

    Args:
        X_batch:     [n_samples, input_dim] INT8 (n_samples <= 8, zero-padded to 8)
        W, b, shift, act_sel, n_inner, n_col_groups: same as run_layer_single

    Returns: [n_samples, output_dim] INT8 output matrix
    """
    n_samples = X_batch.shape[0]
    dut.act_sel.value      = act_sel
    dut.shift_amount.value = shift

    output = np.zeros((n_samples, n_col_groups * COLS), dtype=np.int8)

    for cg in range(n_col_groups):
        await write_bias(dut, b[cg * 8:(cg + 1) * 8])
        await issue_cmd(dut, CMD_CLEAR)

        for ip in range(n_inner):
            w_tile   = W[ip * 8:(ip + 1) * 8, cg * 8:(cg + 1) * 8]
            x_chunks = X_batch[:, ip * 8:(ip + 1) * 8]   # [n_samples, 8]

            await write_weights(dut, w_tile)
            await write_activation_batch(dut, x_chunks)
            await issue_cmd(dut, CMD_COMPUTE)

        await issue_cmd(dut, CMD_DRAIN)
        await issue_cmd(dut, CMD_STORE)

        rows = await read_result_rows(dut, n_samples, COLS)
        for r in range(n_samples):
            output[r, cg * 8:(cg + 1) * 8] = rows[r]

    return output


# ── Tests ─────────────────────────────────────────────────────

@cocotb.test()
async def t1_single_sample(dut):
    """Run all 100 MNIST samples one at a time. Verify bit-exact vs y_ref."""
    await init_and_reset(dut)

    data    = load_test_data()
    W1, W2  = data["W1"], data["W2"]
    b1, b2  = data["b1"], data["b2"]
    shift1  = int(data["shift1"])
    shift2  = int(data["shift2"])
    X_test  = data["X_test"]
    y_test  = data["y_test"]
    y_ref   = data["y_ref"]
    n_samples = len(y_test)

    dut._log.info(f"T1: Single-sample inference — {n_samples} samples")
    dut._log.info(f"  Layer 1: {L1_INNER} inner × {L1_COLGRPS} col groups = {L1_INNER * L1_COLGRPS} COMPUTEs/sample")
    dut._log.info(f"  Layer 2: {L2_INNER} inner × {L2_COLGRPS} col groups = {L2_INNER * L2_COLGRPS} COMPUTEs/sample")
    dut._log.info(f"  shift1={shift1}, shift2={shift2}")

    start_cycles = get_sim_cycles(dut)
    correct     = 0
    mismatches  = []

    for i in range(n_samples):
        # Layer 1: 784 → 64, ReLU
        hidden = await run_layer_single(
            dut, X_test[i], W1, b1, shift1, ACT_RELU,
            n_inner=L1_INNER, n_col_groups=L1_COLGRPS,
        )

        # Layer 2: 64 → 16 (10 real), bypass
        output = await run_layer_single(
            dut, hidden, W2, b2, shift2, ACT_BYPASS,
            n_inner=L2_INNER, n_col_groups=L2_COLGRPS,
        )

        predicted = int(np.argmax(output[:L2_REAL_OUT].astype(np.int32)))
        ref_match = predicted == y_ref[i]
        correct  += ref_match

        if not ref_match:
            mismatches.append(i)
            dut._log.warning(
                f"  Sample {i:3d}: pred={predicted}, ref={y_ref[i]}, true={y_test[i]} ✗ MISMATCH"
            )
        elif i % 10 == 0:
            dut._log.info(
                f"  Sample {i:3d}: pred={predicted}, true={y_test[i]} ✓"
            )

    end_cycles   = get_sim_cycles(dut)
    total_cycles = end_cycles - start_cycles

    dut._log.info("")
    dut._log.info("═══ T1 RESULTS — SINGLE SAMPLE ═══")
    dut._log.info(f"Bit-exact vs y_ref:   {correct}/{n_samples}")
    dut._log.info(f"Total cycles:         {total_cycles:,}")
    dut._log.info(f"Cycles per sample:    {total_cycles // n_samples:,}")

    if mismatches:
        dut._log.error(f"Mismatches at samples: {mismatches}")

    assert correct == n_samples, (
        f"Hardware output does not match integer reference! "
        f"Mismatches at samples: {mismatches}"
    )
    dut._log.info(f"T1 PASS — all {n_samples} samples bit-exact with reference")


@cocotb.test()
async def t2_batched(dut):
    """Run 100 MNIST samples in batches of 8. Verify bit-exact vs y_ref."""
    await init_and_reset(dut)

    data    = load_test_data()
    W1, W2  = data["W1"], data["W2"]
    b1, b2  = data["b1"], data["b2"]
    shift1  = int(data["shift1"])
    shift2  = int(data["shift2"])
    X_test  = data["X_test"]
    y_test  = data["y_test"]
    y_ref   = data["y_ref"]
    n_samples = len(y_test)
    n_batches = (n_samples + ROWS - 1) // ROWS   # ceil(100/8) = 13

    dut._log.info(f"T2: Batched inference — {n_samples} samples in {n_batches} batches of {ROWS}")
    dut._log.info(f"  shift1={shift1}, shift2={shift2}")

    start_cycles = get_sim_cycles(dut)
    correct     = 0
    mismatches  = []

    for bi in range(n_batches):
        batch_start = bi * ROWS
        batch_end   = min(batch_start + ROWS, n_samples)
        batch_size  = batch_end - batch_start

        # Zero-pad to 8 samples
        X_batch = np.zeros((ROWS, 784), dtype=np.int8)
        X_batch[:batch_size] = X_test[batch_start:batch_end]

        # Layer 1: 784 → 64, ReLU
        hidden_batch = await run_layer_batch(
            dut, X_batch, W1, b1, shift1, ACT_RELU,
            n_inner=L1_INNER, n_col_groups=L1_COLGRPS,
        )

        # Layer 2: 64 → 16 (10 real), bypass
        output_batch = await run_layer_batch(
            dut, hidden_batch, W2, b2, shift2, ACT_BYPASS,
            n_inner=L2_INNER, n_col_groups=L2_COLGRPS,
        )

        # Check predictions for real samples in this batch
        for j in range(batch_size):
            idx       = batch_start + j
            predicted = int(np.argmax(output_batch[j, :L2_REAL_OUT].astype(np.int32)))
            ref_match = predicted == y_ref[idx]
            correct  += ref_match

            if not ref_match:
                mismatches.append(idx)
                dut._log.warning(
                    f"  Sample {idx:3d}: pred={predicted}, ref={y_ref[idx]}, true={y_test[idx]} ✗ MISMATCH"
                )

        dut._log.info(
            f"  Batch {bi:2d}: samples {batch_start:3d}–{batch_end - 1:3d} done"
        )

    end_cycles   = get_sim_cycles(dut)
    total_cycles = end_cycles - start_cycles

    dut._log.info("")
    dut._log.info("═══ T2 RESULTS — BATCHED (×8) ═══")
    dut._log.info(f"Bit-exact vs y_ref:   {correct}/{n_samples}")
    dut._log.info(f"Total cycles:         {total_cycles:,}")
    dut._log.info(f"Cycles per sample:    {total_cycles // n_samples:,}")

    if mismatches:
        dut._log.error(f"Mismatches at samples: {mismatches}")

    assert correct == n_samples, (
        f"Hardware output does not match integer reference! "
        f"Mismatches at samples: {mismatches}"
    )
    dut._log.info(f"T2 PASS — all {n_samples} samples bit-exact with reference")


@cocotb.test()
async def t3_custom_digits(dut):
    """Run custom hand-drawn digits through the TPU. Verify bit-exact vs y_ref."""
    await init_and_reset(dut)

    data    = load_custom_data()
    W1, W2  = data["W1"], data["W2"]
    b1, b2  = data["b1"], data["b2"]
    shift1  = int(data["shift1"])
    shift2  = int(data["shift2"])
    X_test  = data["X_test"]
    y_test  = data["y_test"]
    y_ref   = data["y_ref"]
    n_samples = len(y_test)
    n_batches = (n_samples + ROWS - 1) // ROWS

    dut._log.info(f"T3: Custom hand-drawn digits — {n_samples} samples in {n_batches} batch(es)")

    correct_vs_ref  = 0
    correct_vs_true = 0
    mismatches      = []

    for bi in range(n_batches):
        batch_start = bi * ROWS
        batch_end   = min(batch_start + ROWS, n_samples)
        batch_size  = batch_end - batch_start

        X_batch = np.zeros((ROWS, 784), dtype=np.int8)
        X_batch[:batch_size] = X_test[batch_start:batch_end]

        hidden_batch = await run_layer_batch(
            dut, X_batch, W1, b1, shift1, ACT_RELU,
            n_inner=L1_INNER, n_col_groups=L1_COLGRPS,
        )

        output_batch = await run_layer_batch(
            dut, hidden_batch, W2, b2, shift2, ACT_BYPASS,
            n_inner=L2_INNER, n_col_groups=L2_COLGRPS,
        )

        for j in range(batch_size):
            idx       = batch_start + j
            predicted = int(np.argmax(output_batch[j, :L2_REAL_OUT].astype(np.int32)))
            ref_match  = predicted == y_ref[idx]
            true_match = predicted == y_test[idx]
            correct_vs_ref  += ref_match
            correct_vs_true += true_match

            status = "✓" if true_match else f"✗ (network thinks {predicted})"
            dut._log.info(
                f"  Digit {y_test[idx]}: hw={predicted}, ref={y_ref[idx]}, "
                f"ref_match={'✓' if ref_match else '✗'}  {status}"
            )

            if not ref_match:
                mismatches.append(idx)

    dut._log.info("")
    dut._log.info("═══ T3 RESULTS — CUSTOM DIGITS ═══")
    dut._log.info(f"Bit-exact vs y_ref:   {correct_vs_ref}/{n_samples}")
    dut._log.info(f"Correct vs y_test:    {correct_vs_true}/{n_samples} (network accuracy)")

    if mismatches:
        dut._log.error(f"Hardware mismatches at samples: {mismatches}")

    assert correct_vs_ref == n_samples, (
        f"Hardware output does not match integer reference! "
        f"Mismatches at samples: {mismatches}"
    )
    dut._log.info(f"T3 PASS — all {n_samples} samples bit-exact with reference")
