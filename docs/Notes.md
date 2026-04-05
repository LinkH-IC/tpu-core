# TPU Core Design — Session Notes

> **How to use this file:**
> At the start of each new chat session, paste the contents of the latest session block to Claude.
> After each session, append a new block below with what was completed and what is next.

---

## Session 1 — 2026-03-18

### Project Overview
Personal resume project: a TPU systolic array core, focused purely on hardware design.

**Designer:** Digital IC designer, proficient in Verilog, transitioning to SystemVerilog.

**Toolchain:** Verilator, GTKWave, Yosys, OpenLane / OpenROAD / OpenSTA, Cocotb.

**Repo structure:**
```
rtl/
  pe.sv               ✅ Complete
  systolic_array.sv   ⬜ Not started
  weight_buffer.sv    ⬜ Not started
  activation_buffer.sv⬜ Not started
  accumulator.sv      ⬜ Not started
  control_fsm.sv      ⬜ Not started
  top.sv              ⬜ Not started
tb/
  tb_pe.sv            ⬜ Not started  ← Next session
  tb_systolic_array.py⬜ Not started
```

---

### Architecture Decisions (Locked In)

| Parameter | Decision |
|---|---|
| Array size | 8×8 |
| Dataflow | Weight-stationary |
| Weight type | Signed INT8 |
| Activation type | Signed INT8 |
| Accumulator width | 32-bit signed |
| `act_out` | Registered (1-cycle pipeline) |
| `valid_out` | Registered (stays in phase with `act_out`) |
| Reset style | Active-low synchronous (`rst_n`) |

---

### pe.sv — Design Notes

**Ports:**

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | Clock |
| `rst_n` | in | 1 | Active-low synchronous reset |
| `weight_in` | in | 8 | Weight value to preload |
| `weight_load` | in | 1 | 1-cycle strobe: latches weight into `weight_reg` |
| `act_in` | in | 8 | Activation from left neighbour |
| `act_out` | out | 8 | Activation to right neighbour (registered) |
| `psum_in` | in | 32 | Partial sum from top neighbour |
| `psum_out` | out | 32 | Accumulated sum to bottom neighbour |
| `valid_in` | in | 1 | Gates the MAC operation |
| `valid_out` | out | 1 | Registered propagation of `valid_in` |

**Key implementation details:**
- Weight is held in `weight_reg`; only updates when `weight_load` is asserted.
- MAC fires only when `valid_in` is high; `psum_out` holds its value otherwise.
- `act_out` is **always** registered regardless of `valid_in` — this maintains the correct systolic diagonal wavefront across the array.
- Product is sign-extended to 32-bit before accumulation: `ACC_W'(product)`.
- Module is parameterized: `DATA_W = 8`, `ACC_W = 32`.

---

## Session 2 — 2026-03-19

### What We Did

1. **Upgraded Verilator** from 4.038 (2020) to 5.046 (2026) by building from source.
2. **Wrote `tb_pe.sv`** — a SystemVerilog testbench for `pe.sv` covering 12 test groups:
   - Reset, weight load, weight sticky, MAC hold, `act_out` propagation, `valid_out` pipeline, accumulation chain, signed arithmetic, INT8 boundary values, mid-run reset.
3. **Ran the simulation** — 13/14 tests passed on first run.
4. **Verilator Command** — `verilator --binary --timing -Wall --trace -I../../rtl tb_pe.sv ../../rtl/pe.sv --top-module tb_pe`

### Known Issue (Testbench Bug — NOT a pe.sv bug)

T6 reports a false failure. The check expected `act_out=0` after de-asserting `valid_in`, but `act_in` was never driven to 0, so `act_out` correctly registered 1. Fix is to change the expected value in the T6 check from `8'sd0` to `8'sd1`.

```systemverilog
// De-assert valid_in — fix expected act_out from 8'sd0 → 8'sd1
check("valid_out: 0 one cycle after valid_in falls",
      psum_out, 32'sd1, act_out, 8'sd1, valid_out, 1'b0);
```

### Repo Status

```
rtl/
  pe.sv               ✅ Complete
  systolic_array.sv   ⬜ Not started ← Next session
  weight_buffer.sv    ⬜ Not started
  activation_buffer.sv⬜ Not started
  accumulator.sv      ⬜ Not started
  control_fsm.sv      ⬜ Not started
  top.sv              ⬜ Not started
tb/
  tb_pe.sv            ✅ Not started  
  tb_systolic_array.py⬜ Not started
```

---

## Session 3 — 2026-03-23

### What We Did
1. Understood the obj_dir structure produced by Verilator
2. Confirmed the exact Verilator command:
   `verilator --binary --timing -Wall --trace -I../../rtl tb_pe.sv ../../rtl/pe.sv --top-module tb_pe`
   Run from inside the tb/ directory. Then: ./obj_dir/Vtb_pe
3. Understood tb_pe.sv structure: clock gen, apply_reset, drive, idle, check tasks, test stimulus, watchdog
4. Fixed the T6 expected value — pe.sv verified and complete
5. Discussed directed testbenches vs UVM

### Key Decisions
- UVM is not needed for this project (design portfolio, not verification role)
- Cocotb testbench for systolic_array is still the plan

---

## Session 4 — 2026-03-24

### What We Did

1. **Understood systolic array architecture** — physical structure, data flow directions, two-phase operation (weight preload then computation wavefront).
2. **Locked in `systolic_array.sv` design decisions:**

| Decision | Choice | Reason |
|---|---|---|
| Weight loading | Per-row broadcast | One `weight_in` bus per row, shared across all columns in that row |
| Activation staggering | Internal (inside module) | Cleaner external interface; controller just drives all rows simultaneously |
| Top-row `psum_in` | Tied to zero internally | Cleaner top-level interface; accumulation always starts from 0 |

3. **Understood internal signal arrays:**
   - `act_h[row][col]` — horizontal activation bus, col 0 = stagger output, col 8 = discarded
   - `psum_v[row][col]` — vertical psum bus, row 0 = 0 (boundary), row 8 = output
   - `valid_h[row][col]` — horizontal valid, mirrors `act_h` timing
   - `stagger_act[row][stage]` — second dimension is delay stages (0..ROWS-1), NOT columns

4. **Wrote `systolic_array.sv`** — complete RTL including:
   - `default_nettype none/wire` guards
   - Internal stagger shift registers (row i delayed by i FFs)
   - 2D generate loop instantiating 8×8 PE grid
   - Bottom-edge output assignments

5. **Understood key concepts:**
   - `default_nettype none` prevents silent implicit net creation from typos
   - `valid_out` purpose: tells downstream logic when `psum_out` is a complete, trustworthy result (not a partial accumulation)
   - Activations are fed as **columns of A**, not rows — TPU streams A in column-major order
   - `systolic_array.sv` is a pure datapath — it has no knowledge of matrix layout; that responsibility belongs to `control_fsm.sv` / `top.sv`

### systolic_array.sv — Port List

| Port | Width | Description |
|---|---|---|
| `clk`, `rst_n` | 1 | Clock, active-low sync reset |
| `weight_in` | `[ROWS-1:0][DATA_W-1:0]` | One weight bus per row |
| `weight_load` | `[ROWS-1:0]` | One load strobe per row |
| `act_in` | `[ROWS-1:0][DATA_W-1:0]` | One activation per row, un-staggered |
| `valid_in` | `[ROWS-1:0]` | One valid per row, un-staggered |
| `psum_out` | `[COLS-1:0][ACC_W-1:0]` | One result per column, bottom edge |
| `valid_out` | `[COLS-1:0]` | One valid per column, bottom edge |

### Repo Status

```
rtl/
  pe.sv               ✅ Complete
  systolic_array.sv   ✅ Complete
  weight_buffer.sv    ⬜ Not started
  activation_buffer.sv⬜ Not started
  accumulator.sv      ⬜ Not started
  control_fsm.sv      ⬜ Not started
  top.sv              ⬜ Not started
tb/
  tb_pe.sv            ✅ Complete
  tb_systolic_array.py⬜ Not started ← Next session
```
---

## Session 5 — 2026-03-25

### What We Did

1. **Fixed per-row weight broadcast bug** — original `systolic_array.sv` had `weight_load[ROWS-1:0]` (per-row), so all PEs in a row latched the same weight. Changed to `weight_load[COLS-1:0]` (per-column), so each PE(r,c) can hold a unique weight. This was a 1-line change: `.weight_load(weight_load[r])` → `.weight_load(weight_load[c])`.

2. **Chose per-column loading over shift chain** — simpler approach with no change to `pe.sv` needed. Loading sequence: each cycle assert one `weight_load[c]` while driving `weight_in[r]` = W[r][c] for all rows. 8 cycles loads the full 8×8 matrix.

3. **Understood the array's math identity:**
   - We load W directly into PEs: PE(r,c) = W[r][c]
   - Loading is column-major: each cycle sends one column of W (all rows latch in parallel, one column selected)
   - Downward accumulation computes: `output[c][k] = Σ_r W[r][c] × A[r][k]`
   - This equals **W^T × A**
   - If the controller wants `M × x`, it loads M^T so the double-transpose cancels
   - The array is a pure datapath — what gets stored depends entirely on what the controller drives on `weight_in[r]` when `weight_load[c]` is asserted

4. **Wrote `tb_systolic_array.py`** — cocotb testbench with 7 tests:

| Test | Description |
|------|-------------|
| T1 | Reset clears all outputs |
| T2 | Weight load, no activations → no spurious valid_out |
| T3 | Identity W, known activation → output = input |
| T4 | Random 8×8 W and A → verify all 64 outputs vs NumPy W.T @ A (seed=42) |
| T5 | Signed arithmetic (W = all -1, A = all -1 → output = 8) |
| T6 | valid_out column stagger timing (col c fires c cycles after col 0) |
| T7 | Back-to-back matmul with weight reload, no reset (seed=99) |

5. **Wrote Makefile** — uses Verilator + cocotb, run with `make` from `tb/`

### Architecture Decision Updated

| Parameter | Old | New |
|---|---|---|
| `weight_load` | `[ROWS-1:0]` per-row | `[COLS-1:0]` per-column |

### systolic_array.sv — Updated Port List

| Port | Width | Description |
|---|---|---|
| `clk`, `rst_n` | 1 | Clock, active-low sync reset |
| `weight_in` | `[ROWS-1:0][DATA_W-1:0]` | One weight bus per row |
| `weight_load` | `[COLS-1:0]` | **Per-column** load strobe (changed from per-row) |
| `act_in` | `[ROWS-1:0][DATA_W-1:0]` | One activation per row, un-staggered |
| `valid_in` | `[ROWS-1:0]` | One valid per row, un-staggered |
| `psum_out` | `[COLS-1:0][ACC_W-1:0]` | One result per column, bottom edge |
| `valid_out` | `[COLS-1:0]` | One valid per column, bottom edge |

### Repo Status

```
rtl/
  pe.sv               ✅ Complete
  systolic_array.sv   ✅ Complete
  weight_buffer.sv    ⬜ Not started
  activation_buffer.sv⬜ Not started
  accumulator.sv      ⬜ Not started
  control_fsm.sv      ⬜ Not started
  top.sv              ⬜ Not started
tb/
  tb_pe.sv            ✅ Complete
  tb_systolic_array.py✅ Written — NOT YET RUN ← Next session
```

---

## Session 6 — 2026-03-26

### What We Did

1. **Reviewed testbench architecture in detail** — helpers (`to_uint`, `to_sint`, `pack_bus`, `unpack_psum`), drivers (`init_and_reset`, `load_weights`, `compute`), and all 7 test cases
2. **Learned cocotb fundamentals:**
   - `dut` is injected by the cocotb framework via `@cocotb.test()` decorator, connected to RTL through `TOPLEVEL` in the Makefile
   - Signal properties beyond `.value`: `.value_signed`, `.binstr`, `.is_resolvable`, `.integer`, `.buff`
   - `Clock()` API uses `unit="ns"` (singular), not `units="ns"` (deprecated plural)
   - `2>&1 | tee sim.log` captures both stdout and stderr to a log file
3. **Understood the `compute()` drain period** — `num_act + ROWS + COLS + 4` cycles accounts for vertical propagation (ROWS), horizontal stagger (COLS), and safety margin (+4)
4. **Understood the capture loop** — software stand-in for the accumulator and control FSM modules (not yet built)
5. **Ran all 7 tests — all passed first try**
6. **Converted `results.xml`** to readable log format via Python script

### Test Results

```
  t1_reset                        PASS    sim=    30.0 ns
  t2_weight_load_no_act           PASS    sim=   330.0 ns
  t3_identity                     PASS    sim=   340.0 ns
  t4_full_matmul                  PASS    sim=   410.0 ns
  t5_signed                       PASS    sim=   340.0 ns
  t6_valid_timing                 PASS    sim=   330.0 ns
  t7_back_to_back                 PASS    sim=   780.0 ns
```

### Repo Status

```
rtl/
  pe.sv               ✅ Complete + verified
  systolic_array.sv   ✅ Complete + verified (all 7 tests pass)
  weight_buffer.sv    ⬜ Not started          ← Next
  activation_buffer.sv⬜ Not started
  accumulator.sv      ⬜ Not started
  control_fsm.sv      ⬜ Not started
  top.sv              ⬜ Not started
tb/
  tb_pe.sv            ✅ Complete
  tb_systolic_array.py✅ Complete — ALL 7 TESTS PASS
```

---

---

## Session 7 — 2026-03-29

### What We Did

1. **Discussed weight buffer architecture in depth:**
   - Double buffering: shadow bank (host writes) and active bank (sequencer reads), fixed roles, no swap
   - Copy mechanism: single-cycle parallel transfer from shadow to active on `load_trigger`
   - Built-in sequencer: walks columns 0–7, drives `weight_out` and `weight_load` to array in 8 cycles
   - Wide write port: `wr_data[ROWS-1:0][DATA_W-1:0]` with `wr_addr[2:0]` column select, 8 cycles to fill a bank
   - Register file implementation (no SRAM macro) — portable, no PDK dependency
   - Learned that SRAM macros tie RTL to a specific PDK via black-box instantiation with foundry-specific port names

2. **Understood handshake signals:**
   - `ready`: shadow bank is writable (de-asserts only during 1-cycle COPY)
   - `done`: single pulse meaning "sequencer finished, PEs now hold new weights"
   - No write acknowledgment needed — host tracks its own writes
   - `done` does NOT mean computation is complete — that's a separate event tracked by the FSM via `valid_out` from the array

3. **Understood `load_trigger` purpose:**
   - Buffer cannot know when host is done writing (random-address writes) or when array is done computing
   - `load_trigger` is the FSM's "commit" signal: safe to copy and reload
   - Kicks off internal FSM: IDLE → COPY (1 cyc) → SEQUENCE (8 cyc) → IDLE

4. **Understood pipeline balancing:**
   - Narrow write port (1 byte/cycle, 64 cycles) would starve the array
   - Wide write port (1 column/cycle, 8 cycles) matches sequencer bandwidth
   - Real accelerators (TPU v1) widen internal datapaths to keep the array fed
   - Tradeoff: widening doesn't eliminate complexity, it moves it (buffer vs bus adapter)
   - Bottleneck is the systolic array (~24 cycles for 8×8), not the buffer (9 cycles non-overlapped) — this is expected for weight-stationary

5. **Understood double buffer timing:**
   - `ready` re-asserts after COPY (cycle 1), not after `done` (cycle 9)
   - Host can start writing next matrix 7 cycles before sequencing finishes
   - Shadow fill (8 cyc) overlaps with computation (~24+ cyc), so buffer never stalls the pipeline
   - Back-to-back `load_trigger` without waiting for computation to drain would corrupt array weights mid-computation — FSM must enforce ordering

6. **Wrote `weight_buffer.sv`** — complete RTL with:
   - `default_nettype none/wire` guards
   - Parameterized counter width via `$clog2(COLS)` and SystemVerilog width cast `CNT_W'(...)`
   - Typedef enum FSM states
   - Shadow write gated by `wr_en && ready`

7. **Wrote `tb_weight_buffer.py`** — cocotb testbench with 9 tests

8. **Ran all 9 tests — all passed**

### Test Results

| Test | Description | Status |
|------|-------------|--------|
| T1 | Reset: ready=1, done=0, outputs zeroed | PASS |
| T2 | Identity matrix load, column-by-column sequencer output | PASS |
| T3 | Ready timing: 0 during COPY, 1 during SEQUENCE | PASS |
| T4 | Done timing: pulses exactly once at cycle 8 | PASS |
| T5 | Double buffer isolation: shadow writes don't affect active | PASS |
| T6 | Random signed 8×8 matrix (seed=42) | PASS |
| T7 | Back-to-back load without reset (seed=99) | PASS |
| T8 | Write blocked during COPY (ready=0 gates wr_en) | PASS |
| T9 | Pipeline overlap: shadow written during SEQUENCE, trigger immediately | PASS |

### Key Learnings

- **SRAM macro vs register file:** SRAM macros are black-box IP tied to a specific PDK (foundry port names, `.lib`/`.lef` files). Register files are pure synthesizable RTL — portable across tools and processes. At 64 bytes per bank, register file is the right choice.
- **cocotb `FallingEdge` for combinational outputs:** Reading combinational signals immediately after `RisingEdge` in Verilator can return stale values (NBA not yet resolved). Sampling at `FallingEdge` (mid-cycle) guarantees all non-blocking assignments and combinational propagation have settled. Registered outputs don't have this issue.
- **`Timer` removed in cocotb 2.0:** Use `FallingEdge` as the settle mechanism instead.
- **Two meanings of "done":** Buffer `done` = weights in PEs. Computation complete = activations fully drained. FSM must track these separately and use buffer `done` to gate activation start, not next `load_trigger`.

### Architecture Decisions

| Parameter | Decision |
|---|---|
| Buffer style | Double-buffered (shadow + active), fixed roles, copy not swap |
| Copy mechanism | Single-cycle parallel transfer, triggered by `load_trigger` |
| Write port | Wide: `[ROWS-1:0][DATA_W-1:0]` + `wr_addr[2:0]`, 8 cycles to fill |
| Storage | Register file (flip-flops), no SRAM macro |
| Internal FSM | IDLE → COPY (1 cyc) → SEQUENCE (8 cyc) → IDLE |
| Handshake | `load_trigger` (in), `ready` (out), `done` (out) |

### weight_buffer.sv — Port List

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | Clock |
| `rst_n` | in | 1 | Active-low synchronous reset |
| `wr_addr` | in | 3 | Column index 0–7 for shadow bank |
| `wr_data` | in | `[ROWS-1:0][DATA_W-1:0]` | All 8 row weights for one column |
| `wr_en` | in | 1 | Write enable for shadow bank |
| `load_trigger` | in | 1 | Strobe: copy shadow → active, then sequence |
| `ready` | out | 1 | Shadow bank writable (0 only during COPY) |
| `done` | out | 1 | Pulse: sequencer finished, PEs loaded |
| `weight_out` | out | `[ROWS-1:0][DATA_W-1:0]` | Weight bus to systolic array |
| `weight_load` | out | `[COLS-1:0]` | Per-column load strobe to systolic array |

### Repo Status

```
rtl/
  pe.sv                 ✅ Complete + verified
  systolic_array.sv     ✅ Complete + verified
  weight_buffer.sv      ✅ Complete + verified (all 9 tests pass)
  activation_buffer.sv  ⬜ Not started          ← Next
  accumulator.sv        ⬜ Not started
  control_fsm.sv        ⬜ Not started
  top.sv                ⬜ Not started
tb/
  pe/
    tb_pe.sv              ✅ Complete
  systolic_array/
    tb_systolic_array.py  ✅ Complete
    Makefile
  weight_buffer/
    tb_weight_buffer.py   ✅ Complete — ALL 9 TESTS PASS
    Makefile
```

---

## Session 8 — 2026-03-30

### What We Did

1. **Discussed activation buffer architecture:**
   - Reviewed Google TPU v1 paper (Jouppi et al., ISCA 2017) to understand the real TPU's data flow
   - Clarified that the "Activation" block in Figure 1 is the **nonlinear function unit** (ReLU, sigmoid), not activation storage
   - Activation storage in the real TPU lives in the **Unified Buffer** (24 MiB), which serves dual duty as both input and output activation storage
   - Our dedicated `activation_buffer.sv` is a modular equivalent of part of the Unified Buffer — justified at our scale by modularity and independent verifiability

2. **Discussed TPU core vs supporting blocks:**
   - Core compute engine: Matrix Multiply Unit (systolic array) + Accumulators + Unified Buffer
   - Supporting: Activation function unit, Weight FIFO, DMA controller, control (only 2% of die)
   - Our project builds the core — array, buffers, accumulator, control FSM
   - Nonlinear activation functions would be a natural extension but are not part of the MAC datapath

3. **Discussed accumulator purpose:**
   - For our 8×8 array, `psum_out` at the bottom edge is already a **complete** dot product — no multi-pass tiling needed
   - The real TPU's 4 MiB accumulator exists for tiling large matrices across multiple passes through the 256×256 array
   - What we need is an **output capture block**, not a multi-pass accumulator — will revisit in a future session

4. **Discussed `valid` signal ownership:**
   - Option A (chosen): `valid` generated inside activation buffer — sequencer knows which cycles carry real data
   - Option B (rejected): `valid` generated by FSM — breaks encapsulation, requires FSM to track buffer's internal cycle count
   - Parallel with weight buffer: `weight_load` is tightly coupled with `weight_out`, so the buffer generates both. Same logic applies to `valid` + `act_out`

5. **Confirmed high-level data flow with FSM:**
   - Both buffers can be filled simultaneously (independent shadow write ports)
   - FSM triggers weight buffer first → waits for `done` → triggers activation buffer
   - Activation buffer `done` means "all columns driven," not "computation complete"
   - For back-to-back with same weights: skip weight reload, just refill and retrigger activation buffer
   - Fill time hidden behind computation drain via double-buffering

6. **Wrote `activation_buffer.sv`** — structurally identical to `weight_buffer.sv` with three differences:
   - Output: `act_out` + scalar `valid` instead of `weight_out` + per-column `weight_load[COLS-1:0]`
   - `valid` asserted for entire STREAM phase (all rows driven simultaneously)
   - FSM state named STREAM instead of SEQUENCE

7. **Wrote `tb_activation_buffer.py`** — cocotb testbench with 9 tests, pattern-matched to `tb_weight_buffer.py`

8. **Discussed how the systolic array maps to real ML workloads:**
   - Every major NN operation reduces to matrix multiplication — the array doesn't know it's doing ML
   - **MLP**: fully connected layer is directly W × input — maps 1:1 onto the array
   - **CNN**: convolution is reshaped into matrix multiply via **im2col** transformation (software side)
   - **LSTM**: each gate (forget, input, output) is a matrix multiply followed by a nonlinear function

9. **Discussed what our 8×8 core can actually do:**
   - Pure matrix multiplication alone is a calculator, not an accelerator
   - To run real inference, the core needs a **layer-by-layer feedback loop**: matrix multiply → activation function → feed result back as next layer's input
   - **Iris flower classification** (4→8→3 MLP, 2 layers) fits natively in our 8×8 array with no tiling
   - On FPGA: load pre-trained INT8 weights, send measurements over UART, get back a classification — a live inference demo

10. **Discussed multi-layer inference architecture:**
    - The real TPU's Unified Buffer achieves the feedback loop via two write sources: host DMA and activation function output
    - Our modular approach: add a **mux on the activation buffer write port** — host vs feedback path, selected by FSM
    - The "Unified Buffer" behavior emerges from FSM coordination, not from one monolithic block
    - FSM state flow for two-layer inference: IDLE → LOAD_W → TRIG_W → WAIT_W → TRIG_A → WAIT_A → DRAIN → RELU → NEXT (loop or DONE)
    - Each FSM state is trivial — assert a trigger, wait for a done signal. No cycle-level micromanagement.

11. **Clarified what is actually new hardware for multi-layer support:**
    - **Already on roadmap (unchanged):** output buffer, control FSM, top-level wiring
    - **New for multi-layer:** a mux on activation buffer write port (~5 lines RTL), a ReLU unit (~20 lines RTL)
    - Everything else is FSM state definition — which was always needed
    - Training, quantization, data formatting are all host-side software — hardware just sees matrices

### Architecture Decisions

| Parameter | Decision |
|---|---|
| Buffer style | Double-buffered (shadow + active), fixed roles, copy not swap |
| Copy mechanism | Single-cycle parallel transfer, triggered by `load_trigger` |
| Write port | Wide: `[ROWS-1:0][DATA_W-1:0]` + `wr_addr[2:0]`, 8 cycles to fill |
| Storage | Register file (flip-flops), no SRAM macro |
| Internal FSM | IDLE → COPY (1 cyc) → STREAM (8 cyc) → IDLE |
| Handshake | `load_trigger` (in), `ready` (out), `done` (out) |
| `valid` ownership | Generated inside buffer (Option A), not by external FSM |
| Multi-layer support | Mux on activation buffer write port (host vs feedback), controlled by FSM |
| Activation function | ReLU unit between output buffer and feedback path |
| Target demo | Iris classification (4→8→3 MLP), 2 layers, fits natively in 8×8 array |

### activation_buffer.sv — Port List

| Port | Dir | Width | Description |
|---|---|---|---|
| `clk` | in | 1 | Clock |
| `rst_n` | in | 1 | Active-low synchronous reset |
| `wr_addr` | in | 3 | Column index 0–7 for shadow bank |
| `wr_data` | in | `[ROWS-1:0][DATA_W-1:0]` | All 8 row activations for one column |
| `wr_en` | in | 1 | Write enable for shadow bank |
| `load_trigger` | in | 1 | Strobe: copy shadow → active, then stream |
| `ready` | out | 1 | Shadow bank writable (0 only during COPY) |
| `done` | out | 1 | Pulse: sequencer finished streaming |
| `act_out` | out | `[ROWS-1:0][DATA_W-1:0]` | Activation bus to systolic array |
| `valid` | out | 1 | Asserted during STREAM phase |

### Repo Status

```
rtl/
  pe.sv                 ✅ Complete + verified
  systolic_array.sv     ✅ Complete + verified
  weight_buffer.sv      ✅ Complete + verified
  activation_buffer.sv  ✅ Complete + verified (all 9 tests pass)
  accumulator.sv        ⬜ Not started          ← Next
  control_fsm.sv        ⬜ Not started
  top.sv                ⬜ Not started
tb/
  pe/
    tb_pe.sv              ✅ Complete
  systolic_array/
    tb_systolic_array.py  ✅ Complete
    Makefile
  weight_buffer/
    tb_weight_buffer.py   ✅ Complete
    Makefile
  activation_buffer/
    tb_activation_buffer.py ✅ Complete — ALL 9 TESTS PASS
    Makefile
```

---

## Session 9 — 2026-03-31 - 2026-04-03

### What We Did

1. **Clarified accumulator purpose from the TPU paper:**
   - The accumulator is not just an output capture register — it performs genuine partial sum accumulation across tiling passes when the inner matrix dimension exceeds the array size (8 for us, 256 for Google)
   - The MatrixMultiply instruction in the real TPU includes an accumulator address; same address = accumulate, new address = fresh write
   - Without multi-pass support, matrices larger than 8×8 cannot be computed — accumulation is essential for generality

2. **Designed and wrote `accumulator.sv`:**
   - 8×8 × 32-bit register file storing intermediate/final results
   - Per-column row counters: each column independently tracks which result row it is writing to, handling the staggered wavefront from the systolic array
   - `clear` signal (distinct from `rst_n`): zeroes registers before a new matmul without resetting the entire system. Buffers don't need this because they use store semantics (overwrite); the accumulator uses accumulate semantics (additive)
   - `pass_done` with auto-reset: pulses when all 8 columns complete one pass, resets counters but preserves accumulated values for the next tiling pass
   - Drain sequencer: outputs one **column** per cycle (not row), matching the unified buffer's column-oriented write port
   - `col_idx` output maps directly to unified buffer `wr_addr` during writeback

3. **Designed and wrote `relu.sv`:**
   - Pure combinational module, no clock — sits between accumulator drain and unified buffer write port
   - Three operations per element: ReLU (clip negatives to 0), scale (configurable right-shift for requantization), clamp (saturate to signed INT8 [0, 127])
   - `shift_amount` is set by the host per layer based on training-time quantization — compresses 32-bit accumulator values back to 8-bit for the next layer
   - Parameterized by ROWS (processes all rows of one column per cycle)

4. **Evolved `activation_buffer.sv` into `unified_buffer.sv`:**
   - Three banks: **write bank** (was shadow), **active bank** (unchanged), **result bank** (new)
   - Write bank: staging area for incoming data from host or ReLU feedback (mux lives in top.sv)
   - Active bank: copied from write bank on `load_trigger`, sequencer streams to array
   - Result bank: copied from write bank on `store_trigger`, host reads via `rd_addr`/`rd_en`/`rd_data`
   - FSM expanded: IDLE → COPY → STREAM → IDLE (existing), IDLE → STORE → IDLE (new)
   - `load_trigger` takes priority over `store_trigger` if both arrive simultaneously
   - `ready` blocks writes during both COPY and STORE states
   - Host read port is **registered** (one-cycle latency) to avoid glitches
   - `rd_data` driven to zero when `rd_en` is low to save power
   - Renamed: `done` → `load_done`, parallel with `store_done`

5. **Fixed accumulator drain orientation:**
   - Original design drained row-by-row, but unified buffer writes column-by-column — dimensional mismatch
   - Changed drain to column-by-column: `acc_out[r] = acc_reg[r][drain_cnt]` — all rows for one column
   - `row_idx` → `col_idx`, which maps directly to `wr_addr` during writeback
   - ReLU parameter changed from `COLS` to `ROWS` to match the new orientation

6. **Wrote and verified all testbenches:**
   - `tb_accumulator.py` — 9 tests: reset, clear, single-pass aligned/staggered, drain sequencing, pass_done timing, multi-pass accumulation, done timing, back-to-back
   - `tb_relu.sv` — 9 tests: zeros, positive passthrough, negative clipping, mixed, shift scaling, saturation, boundary, max shift, per-row independence
   - `tb_unified_buffer.py` — 14 tests: all 9 original activation buffer tests adapted + store/read, store_done timing, result bank isolation, read gating, full pipeline end-to-end

### Architecture Decisions

| Parameter | Decision |
|---|---|
| Accumulator size | 8×8 × 32-bit register file (full output matrix) |
| Accumulator operation | `acc_reg[row][col] += psum_in[col]` with per-column row counters |
| Clear vs reset | `clear` zeroes data registers only; `rst_n` resets entire module including FSM |
| Pass tracking | `col_done` packed vector, `pass_done = &col_done`, auto-reset on pulse |
| Drain orientation | Column-by-column (matches unified buffer write port) |
| ReLU style | Pure combinational: clip → shift → clamp |
| Requantization | Configurable right-shift (`shift_amount[4:0]`), set by host per layer |
| Unified buffer banks | Write (staging), Active (array feed), Result (host readback) |
| Result bank population | Single-cycle copy from write bank on `store_trigger` |
| Host read port | Registered, gated by `rd_en` |
| Write port mux location | External, in top.sv — buffer is source-agnostic |
| Port style | All `logic` (aligned with pe.sv) |

### Key Learnings

- **Store vs accumulate semantics:** Buffers naturally overwrite old data (store), so they don't need a clear signal. The accumulator adds to existing values (accumulate), so stale data corrupts results without explicit clearing.
- **Drain orientation must match consumer:** The accumulator drain must output in the same orientation the downstream write port expects. Column-wise drain → column-wise write — no transpose buffer needed.
- **Neural network outputs are not always 1D:** But the hardware doesn't care — it always produces 8×8 tiles. The host knows which entries are padding and ignores them.
- **General-purpose design:** Any matrix multiply decomposes into 8×8 tiles. The accumulator handles inner-dimension tiling, the FSM handles outer loops, the host handles padding. No hardware changes needed for different matrix sizes.
- **`final` is a SystemVerilog keyword:** cannot be used as a signal/variable name.

### Repo Status

```
rtl/
  pe.sv                 ✅ Complete + verified
  systolic_array.sv     ✅ Complete + verified
  weight_buffer.sv      ✅ Complete + verified
  unified_buffer.sv     ✅ Complete + verified (14 tests pass) — replaces activation_buffer.sv
  accumulator.sv        ✅ Complete + verified (9 tests pass)
  relu.sv               ✅ Complete + verified (9 tests pass)
  control_fsm.sv        ⬜ Not started          ← Next
  top.sv                ⬜ Not started
tb/
  pe/
    tb_pe.sv                ✅ Complete
  systolic_array/
    tb_systolic_array.py    ✅ Complete
    Makefile
  weight_buffer/
    tb_weight_buffer.py     ✅ Complete
    Makefile
  unified_buffer/
    tb_unified_buffer.py    ✅ Complete — ALL 14 TESTS PASS
    Makefile
  accumulator/
    tb_accumulator.py       ✅ Complete — ALL 9 TESTS PASS
    Makefile
  relu/
    tb_relu.sv              ✅ Complete — ALL 9 TESTS PASS
```
---

## Session 11 — TODO

Next module: **Control FSM** (`control_fsm.sv`)

Design questions resolved so far:
- **Host-stepped FSM:** FSM executes one phase at a time, returns to idle, waits for host command. No internal layer/tiling loop — host controls the sequence.
- **Handoff boundary:** Host owns the write ports during loading. Host asserts `start` after loading is complete. FSM takes over datapath during computation and feedback.
- **Write port mux:** Separate small module in top.sv, selects host vs ReLU feedback based on FSM phase.
- **Drain-to-writeback wiring:** `col_idx` → `wr_addr`, `relu_out` → `wr_data`, `acc_valid` → `wr_en` — FSM bridges accumulator drain to unified buffer write port.

Open questions for next session:
- Exact FSM state list and transitions
- Host interface signals: what commands does the host send? Configuration registers for `shift_amount`, tiling count?
- Status signals back to host: computation complete, drain complete, results ready?
- Write port mux module design
- How does `store_trigger` get asserted — by FSM or host directly?

---

*"Here is a summary of our TPU core design project so far. [paste this file contents]. Today I want to run tb_systolic_array.py and debug any failures."*

---

> **After each session:** update the repo status table above, add a new session block, and update the TODO prompt at the bottom.
