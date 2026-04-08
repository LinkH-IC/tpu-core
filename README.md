# 8×8 Systolic Array TPU Core

A weight-stationary 8×8 systolic array TPU core implemented in SystemVerilog, capable of running multi-layer INT8 neural network inference. Designed from first principles referencing the [Google TPU v1 paper](https://arxiv.org/abs/1704.04760).

**Current status:** End-to-end Iris flower classification verified (93.3% INT8 accuracy). MNIST inference with input tiling in progress.

---

## Architecture Overview

```
Host
 │
 ▼
Control FSM
 ├──▶ Weight Buffer (double-buffered) ──▶ Systolic Array (8×8 PEs)
 ├──▶ Unified Buffer (activation in/out)──▶        │
 │                                                  ▼
 │                                           Accumulator
 │                                                  │
 │                                          Bias Add + Activation Mux
 │                                       (ReLU / Leaky ReLU / Bypass / Binary Step)
 │                                                  │
 └──────────────────────────────────────────────────▶ Write-back to Unified Buffer
```

### Key design decisions

- **Weight-stationary dataflow** — weights are pre-loaded into PEs before each compute pass; activations stream through
- **Host-stepped FSM** — the control FSM executes one phase per host command (LOAD_WEIGHTS → COMPUTE → DRAIN → ACTIVATE), enabling flexible multi-layer chaining without hardcoded layer logic
- **Unified Buffer with transposed write-back** — activations written back as `active[r][c] <= write[c][r]` during COPY, correcting the inherent transpose of the drain output and making the array self-consistent across layers
- **Tiling support** — matrices larger than 8×8 are handled by multiple COMPUTE passes with accumulate-on-write in the accumulator; first pass overwrites, subsequent passes accumulate
- **Register file over SRAM macros** — avoids PDK-specific black-box instantiation, keeping RTL portable across ASIC and FPGA flows

---

## Module Breakdown

| Module | Description |
|--------|-------------|
| `pe.sv` | Single MAC processing element. Multiplies weight × activation, accumulates into psum. Passes both weight and activation to adjacent PEs |
| `systolic_array.sv` | 8×8 grid of PEs. Manages weight loading (per-column strobe), activation streaming, and valid propagation |
| `weight_buffer.sv` | Double-buffered register file. Shadow bank accepts host writes while active bank sequences into array. Internal FSM: IDLE → COPY → SEQUENCE |
| `unified_buffer.sv` | Dual-bank activation storage. Serves as both input buffer and write-back target for layer-to-layer feedback. Includes transposed copy for datapath correctness |
| `accumulator.sv` | Per-column 32-bit accumulation registers. Accumulate-on-write with pass counter: overwrite on pass 0, accumulate on subsequent passes. Includes combinational bias add before drain |
| `relu.sv` `bypass.sv` `leaky_relu.sv` `binary_step.sv` | Combinational activation units. Configurable right-shift scaling, clamp to INT8. Supports ReLU, leaky ReLU (α=0.125), bypass, and binary step via 2-bit select |
| `control_fsm.sv` | Host-stepped FSM. Accepts single-cycle command strobes, coordinates buffer triggers, tracks compute and drain completion independently |
| `top.sv` | Integration wrapper. Wires all modules, exposes host interface |

---

## Verified Inference

### Iris Flower Classification (4→8→3 MLP)

- Trained in PyTorch, quantized to INT8 via symmetric per-tensor quantization
- Float accuracy: 93.3% | INT8 accuracy: 93.3% (28/30 test samples)
- 2 misclassified samples are versicolor boundary cases — consistent with quantization rounding, not a hardware error
- Single-tile inference (fits in one 8×8 pass per layer, no tiling required)

### MNIST (784→64→10 MLP) — In Progress

- Requires input tiling: 98 COMPUTE passes per output group for layer 1
- 8 output groups for layer 1 (64 outputs / 8 columns)
- Tests the accumulator's accumulate-on-write path under real workload

---

## Toolchain

| Tool | Purpose |
|------|---------|
| SystemVerilog | RTL implementation |
| Verilator 5.x | Simulation (`--binary --timing -Wall --trace`) |
| cocotb 2.0 + NumPy | Python testbenches with floating-point reference models |
| GTKWave | Waveform inspection |
| Yosys | Synthesis |
| OpenLane / OpenROAD / OpenSTA | ASIC place-and-route, STA targeting sky130 PDK |

---

## Repository Structure

```
rtl/                  SystemVerilog source
  pe.sv
  systolic_array.sv
  weight_buffer.sv
  unified_buffer.sv
  accumulator.sv
  relu.sv
  bypass.sv
  leaky_relu.sv
  binary_step.sv 
  control_fsm.sv
  top.sv
tb/                   cocotb testbenches (per-module subdirectories)
  pe/
  systolic_array/
  weight_buffer/
  unified_buffer/
  accumulator/
  relu/
  top/
    Iris/
        tb_iris.py    End-to-end Iris inference
    tb_top.py         Integration tests
syn/                  Synthesis outputs
```

---

## Running Simulations

Each module has an independent cocotb testbench. Example for the systolic array:

```bash
cd tb/systolic_array
make
```

Requires Verilator 5.x and cocotb 2.0 installed. Waveforms are written to `dump.vcd`, viewable in GTKWave.

---

## Background & Motivation

This project is a personal portfolio piece aimed at demonstrating RTL design skills at the architecture level. The goal was not to build a toy example but a programmable, model-agnostic accelerator — weights are loaded at runtime, the same hardware runs any compatible MLP without modification.

The design deliberately follows the original TPU paper's philosophy: a matrix multiply unit feeding an accumulator, with a unified buffer serving as the on-chip activation store. Every architectural decision traces back to a reason.

---

## Planned Work

- MNIST inference with input tiling
- FPGA implementation on Arty A7, benchmarked against PicoRV32 soft-core running the same inference in software
- Synthesis area and timing report (sky130)

---

## References

- Jouppi et al., *In-Datacenter Performance Analysis of a Tensor Processing Unit*, ISCA 2017 — [arXiv:1704.04760](https://arxiv.org/abs/1704.04760)
