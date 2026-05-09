# FPGA Bring-up: Timing Closure, BRAM Weight Subsystem, and Benchmark

This document covers the FPGA-side engineering for the TPU core: deploying the verified RTL onto a Digilent Arty A7-100T (Xilinx Artix-7), closing timing at 100 MHz post-route, scaling the weight delivery path to handle MNIST without UART becoming the bottleneck, and constructing a PicoRV32 RISC-V SoC as the baseline for the headline benchmark.

The FPGA-specific RTL itself (UART stack, BRAM weight subsystem, top-level wrapper, PicoRV32 SoC) is not in this repository — it's tightly coupled to the Arty A7-100T pinout and clock topology. What's documented here is the engineering reasoning, with concrete numbers from the actual implementation.

---

## Contents

1. [System Architecture on FPGA](#system-architecture-on-fpga)
2. [Timing Closure: 100 MHz on the Drain Path](#timing-closure-100-mhz-on-the-drain-path)
3. [BRAM Weight Subsystem](#bram-weight-subsystem)
4. [PicoRV32 Baseline SoC](#picorv32-baseline-soc)
5. [Benchmark Methodology](#benchmark-methodology)
6. [Results](#results)
7. [Lessons and Deferred Work](#lessons-and-deferred-work)

---

## System Architecture on FPGA

Two separate bitstreams are built from the same FPGA — one with the TPU as the compute engine, one with the PicoRV32 SoC. Building two separate bitstreams (rather than one fabric containing both) avoids any shared-resource ambiguity in the comparison.

### TPU bitstream

```
PC (USB)
 │
 ▼  UART @ 100 MHz, 921600 baud
┌────────────────────────────────────────────────────────┐
│ uart_top  (rx + tx + host_controller protocol bridge)  │
│   - 11 production opcodes                              │
│   - request-response flow control                      │
└────────────────────────────────────────────────────────┘
 ├──▶ weight_mem (64 KB BRAM, byte-write / 64-bit read)
 │      ▲                                  │
 │      │ WRITE_WEIGHT_BULK (boot)         │ LOAD_WEIGHT_TILE
 │      │                                  ▼
 │      │                       weight_loader (autonomous, 10 cycles)
 │      │                                  │
 │      │                                  ▼
 ├──▶ ──┴──▶ TPU core (top.sv, this repo's RTL)
 │              - UART path: WRITE_WEIGHT (legacy, kept as regression smoke test)
 │              - Memory path: weight_loader → wb_wr_*  (production)
 │              - mux on wb_wr_*, registered select latched on opcode capture
 │
 ▼  status outputs
LEDs (busy / RX activity / error / heartbeat)
BTN1 → physical COMPUTE trigger (debounced, edge-detected, gated)
```

### PicoRV32 bitstream

```
PC (USB)
 │
 ▼  UART @ 100 MHz, 115200 or 921600 baud
┌────────────────────────────────────────────────────────┐
│ mmio_uart  (memory-mapped UART, single 32-bit register │
│             at 0x80000000)                             │
└────────────────────────────────────────────────────────┘
 ▲
 │ bus_decoder  (one bit: mem_addr[31] selects RAM vs UART)
 ▼
┌────────────────────────────────────────────────────────┐
│ picorv32  (RV32I, no MUL/DIV, ENABLE_COUNTERS=1)       │
│   - 128 KB unified BRAM (instruction + data)           │
│   - Software multiply via libgcc __mulsi3              │
└────────────────────────────────────────────────────────┘
 │
 ▼  RGB rainbow indicator (PWM, 4 LEDs, ~2.7 s color cycle)
```

Both designs share the UART protocol shape (`[OPCODE:1][LEN:1][PAYLOAD]` → ack) so the same host-side Python infrastructure drives them.

### Reset architecture

Both designs use a 2-flop async-assert / sync-deassert reset synchronizer on `BTN0`. The TPU bitstream additionally synthesizes a soft-reset path (`tpu_soft_reset`) that resets the FSM and TPU datapath state without wiping the BRAM weight memory — important because re-uploading 51 KB of MNIST weights every reset would dominate debug iteration time.

```
rst_n_physical  ── always resets weight_mem, weight_loader, host_controller
tpu_rst_n       = rst_n_physical & ~tpu_soft_reset  ── resets only the TPU core
```

This split is consistent with the project's general discipline of treating BRAM contents as separately-managed state.

---

## Timing Closure: 100 MHz on the Drain Path

This is the engineering result the writeup leads with. It demonstrates the loop that defines RTL design at scale: read STA, identify the limiting path, propose architecturally clean changes, balance stage delays, verify in regression, confirm post-route. You can check the details of timming summary at `docs/top_fpga_timing*`.

### Initial state

The first integration attempt instantiated the verified TPU core directly into the Arty board wrapper at 100 MHz. Vivado's post-route STA reported a hard violation on the drain path:

| | First-pass post-route |
|---|---|
| WNS (drain path) | **−4.495 ns** |
| Logic levels on critical path | 24 |
| Total combinational delay | 14.468 ns |
| Logic / route split | 35.9% / 64.1% |
| Carry chains in series | 12 × CARRY4 |

The violation was real, not synthesis noise. The path is the requantization chain inside the drain:

```
accumulator (32-bit register file)
 │
 ▼
bias_add (32-bit signed add: acc[r][col_idx] + bias[col_idx])
 │
 ▼
arithmetic right shift (configurable, 0–31 positions)
 │
 ▼
activation function (ReLU / leaky / bypass / binary step, 4:1 mux)
 │
 ▼
unified_buffer write-port mux (HOST vs DRAIN)
 │
 ▼
unified_buffer write_reg (D flip-flop setup)
```

Five logic operations between two consecutive flip-flops, with two of them (the 32-bit add and the 32-bit shift) being carry-chain-heavy. 14.5 ns of combinational delay does not fit in a 10 ns clock period.

### Tactical workaround: 50 MHz via MMCM

The first response was an MMCM divide-down: Vivado Clocking Wizard taking the 100 MHz pad clock and producing a 50 MHz internal clock. All time-based counter parameters (debounce intervals, heartbeat, RX-activity stretch) were halved in tandem. Post-route at 50 MHz reported WNS = +1.318 ns — closed with healthy margin, but at half the headline frequency.

This was useful for unblocking initial bring-up — Iris ran end-to-end on real silicon at 50 MHz, 30/30 bit-exact — but it left the architectural question open: can the design actually run at 100 MHz?

### Architectural fix: two pipeline registers

The path's own STA report drove the placement decision. Per-stage delay breakdown:

| Stage candidate | Approx delay |
|---|---|
| Bias mux + 32-bit `bias_add` | ~5.0 ns |
| Right shift + activation function + saturation | ~5.5 ns |
| Final write-port mux + `write_reg` setup | ~4.0 ns |

Three roughly equal thirds, not two halves. A single pipeline register would have left the dominant stage at ~9.5 ns and closed at maybe 0.3 ns of slack — likely flipping back to negative on placer-seed variance. Two registers gave comfortable margin: 5.0 / 4.5 / 5.0 ns.

The two registers were placed in `top.sv`:

- **R1: `biased_reg`** (8 × 32 bits) — between `bias_add` output and the activation function inputs
- **R2: `act_reg`** (8 × 8 bits) — between the activation mux and the unified buffer write-port mux

Both are pure pipeline registers — no logic between them and the surrounding stages, just D flip-flops.

### Encapsulation preserved

A core property of the change: **none of the submodules were touched.** Not `accumulator.sv`, not `bias_add.sv`, not any of the four activation modules, not `unified_buffer.sv`, not `control_fsm.sv`. All five edits live in `top.sv`. Pipelining is a top-level architectural decision about latency; submodules stay topology-agnostic and remain reusable in different integration contexts.

This is the encapsulation principle in action — the same principle that earlier let the BRAM weight subsystem swap in without modifying the TPU core (see [BRAM Weight Subsystem](#bram-weight-subsystem) below).

### The subtle one: drain_done delay line

The accumulator's `drain_done` signal had to be retimed by 2 cycles before reaching the FSM. This is the kind of pipelining bug that breaks designs silently and is worth recording.

The accumulator emits its last column on cycle N. Without pipeline registers, that column lands in `unified_buffer.write_reg` on cycle N+1 (one register layer between drain output and write port). The FSM observes `drain_done` on cycle N and deasserts `mux_sel` on cycle N+1 — exactly when the last write needs to commit through the mux. Tight, but functionally correct.

With the two new pipeline registers, the actual last write happens 2 cycles *later* — the column traverses `biased_reg` (1 cycle), then `act_reg` (1 more cycle), then the write port. The FSM still sees `drain_done` on cycle N and tries to deassert `mux_sel` on cycle N+1 — but the last two writes are still in flight, behind the new pipeline. They would land with the wrong mux selection (HOST instead of DRAIN), corrupting the result.

The fix is a 2-cycle shift register on `drain_done` between the accumulator and the FSM. The FSM now sees `drain_done` aligned with the *actual* last write, not the accumulator's emission.

Cost: 2 extra cycles per drain phase. With 8 emissions, drain grows from 8 cycles to 10. Total per-sample latency cost across two layers: +4 cycles. Negligible against MNIST's ~37,000 cycles/sample compute.

### Result

| | Before | After |
|---|---|---|
| WNS (post-route) | **−4.495 ns** | **+0.310 ns** |
| Logic levels on critical path | 24 | 12 |
| Total combinational delay | 14.468 ns | 9.588 ns |
| Logic / route split | 35.9% / 64.1% | 31% / 69% |
| Per-sample drain cycle cost | 8 | 10 (+2) |

All 22,383 endpoints pass post-route timing at 100 MHz. MNIST inference runs end-to-end at the headline clock with the headline accuracy.

---

## BRAM Weight Subsystem

The MNIST scale-up exposed an architectural limitation of the original design: the weight buffer was fed directly by the UART host, so weights were re-streamed from PC to FPGA for every tile, every sample. For Iris this was fine — 4 inputs, single tile, one upload. For MNIST's 51,200 layer-1 weights with 800 tiles per inference, weight TX dominated per-sample wall-clock time.

The fix: an on-chip BRAM weight memory plus an autonomous loader, sitting *above* the TPU boundary. The TPU core's weight buffer write interface (`wb_wr_addr`, `wb_wr_data`, `wb_wr_en`) is preserved unchanged — this is, again, the encapsulation principle. The TPU has no opinion about where its weight writes originate.

### Result

| | Legacy UART path | Memory path |
|---|---|---|
| Weight TX per batch (MNIST L1) | ~69 KB | ~3 KB |
| Weight TX per batch (MNIST L2) | ~1.4 KB | ~64 B |
| Per-tile load latency | ~6.4 ms (UART) | ~100 ns (HW) |
| MNIST 100 samples wall-clock | ~13.8 s/batch | **~8.2 s/batch** |
| Wall-clock speedup | 1× | **1.68×** |

The 1.68× wall-clock speedup is smaller than the 22× UART traffic reduction because activations, biases, and control still go over UART and now dominate. The interesting observation: this is the first point in the project where UART is provably the bottleneck. Removing the per-tile UART round-trip for weights exposes activations as the next ceiling.

A future activation-side BRAM is plausible but lower priority. The headline benchmark (cycles/sample, compute-only) bypasses UART entirely on both sides, so the comparison is fair as-is.

---

## PicoRV32 Baseline SoC

Without a baseline, the TPU's compute numbers are meaningless. The PicoRV32 baseline runs the same MNIST inference as the TPU, on the same FPGA, with the same input data, and produces bit-exact predictions against the same Python reference. Whatever cycle count it takes to reach those predictions is the comparison number.

### CPU configuration

[PicoRV32](https://github.com/YosysHQ/picorv32) is a small, well-documented RV32I CPU core (YosysHQ, MIT-licensed). The upstream `picorv32.v` is a single ~3000-line file containing the CPU plus several alternative bus wrappers. Only the `picorv32` module is instantiated; everything else (AXI / Wishbone wrappers, optional coprocessors) is unused.

| Parameter | Value | Reason |
|---|---|---|
| `ENABLE_COUNTERS` | 1 | `RDCYCLE` for per-sample cycle measurement |
| `ENABLE_MUL` | 0 | Software multiply via libgcc — naive baseline, the standard "general-purpose CPU" reference |
| `ENABLE_DIV` | 0 | Not needed by inference |
| `COMPRESSED_ISA` | 0 | RV32I, not RV32IC |
| `ENABLE_IRQ` | 0 | Polling is simpler and equivalent in wall-clock terms for this workload |
| `PROGADDR_RESET` | 0 | Boot from address zero |
| `STACKADDR` | 0x0001_FFFC | Top of 128 KB BRAM |

Software-multiply (`ENABLE_MUL=0`) is the deliberate choice. The point of the comparison is what naive RV32I looks like as a baseline, not what an optimized embedded CPU could do. Hardware multiply would collapse a meaningful chunk of the gap.

### SoC structure

Three hand-written modules around the CPU core:

- **`mem.v`** — 128 KB unified instruction+data BRAM, BRAM-backed via `$readmemh` from `firmware.hex` at bitstream load. Word-addressed, byte-strobed writes.
- **`mmio_uart.v`** — memory-mapped UART wrapper around the existing `uart_rx.sv` / `uart_tx.sv`. Single 32-bit register at `0x80000000`. Write = TX byte. Read = `[7:0]` rx_data, `[8]` rx_valid, `[9]` tx_busy, `[10]` frame_error, `[11]` overrun.
- **`bus_decoder.v`** — combinational address decoder. `mem_addr[31]` selects RAM (0) or UART (1). One bit, one mux. RV32I has no I/O instructions; sending a UART byte is `sw t0, 0(s0)` where `s0 = 0x80000000`. The same instruction stores to RAM if `s0` points there. Address is the only difference — that's the whole MMIO concept in one observation.

Plus `picorv32_top.v` integrating the four modules and a 4-LED RGB rainbow indicator (PWM, 28-bit hue counter, 90° phase offsets, ~12.5% peak duty cycle). The status indicator is cosmetic — it doesn't affect the benchmark — but it makes the bitstream visibly alive.

### Firmware

MNIST inference in C, ~200 lines, single file (`mnist.c`). Static buffers in `.bss`: layer1_weights (50 KB), layer2_weights (1 KB), biases (320 B), activations (784 B), outputs (80 B). Total ~52 KB resident.

Inference is a triple-nested INT8 matmul per layer with bias add, signed shift, ReLU/saturate (layer 1), or bias add and signed shift only (layer 2, BYPASS), followed by argmax over 10 classes. All accumulation in `int32_t`; right shifts compile to `sra` on RISC-V, matching the Python reference and TPU hardware shifter exactly.

```c
// Conceptual inner loop (layer 1)
for (int o = 0; o < 64; o++) {
  int32_t acc = bias1[o];
  for (int i = 0; i < 784; i++) {
    acc += (int32_t)act_in[i] * (int32_t)w1[o * 784 + i];  // __mulsi3
  }
  acc >>= shift1;
  if (acc < 0) acc = 0;
  if (acc > 127) acc = 127;
  act_h[o] = (int8_t)acc;
}
```

Per-sample cycle counter reads use inline assembly:

```c
uint32_t c0, c1;
asm volatile ("rdcycle %0" : "=r"(c0));
run_inference();
asm volatile ("rdcycle %0" : "=r"(c1));
uint32_t cycles = c1 - c0;
```

### Build

Toolchain: `gcc-riscv64-unknown-elf` (Ubuntu 20.04+ multilib, supports `-march=rv32i -mabi=ilp32`).

```
gcc -O1 -ffreestanding -nostdlib -march=rv32i -mabi=ilp32 -c *.c
gcc -T linker.ld -nostartfiles -lgcc -o firmware.elf *.o
objcopy -O binary firmware.elf firmware.bin
hexdump-to-readmemh firmware.bin > firmware.hex
```

`-nostdlib` excludes libc; `-lgcc` re-adds the compiler-helper library (needed for `__mulsi3`). The first build without `-lgcc` failed at link time on the `*` operator in the inference loop — useful gotcha to record. Hello World had compiled cleanly because it has no multiply.

### Result

100 / 100 bit-exact match against `y_ref` on the same MNIST test subset the TPU runs. Per-sample cycle counts in the [Results](#results) section.

---

## Benchmark Methodology

### What's being measured

The headline number is **cycles per sample, compute only**. Both designs measure between the same conceptual brackets:

- **TPU side:** cycles between idle-to-idle FSM transitions on the FSM's busy gate, captured by a hardware perf counter on the FPGA.
- **CPU side:** cycles between two `rdcycle` reads bracketing the inference function call on the CPU.

UART transmission of inputs and outputs is **excluded** on both sides. This is the architectural number — what the silicon does at the math, independent of the host-protocol design that happens to surround it.

### TPU cycle counter

A 4-line `always_ff` block in `top_fpga.sv` counts cycles when either the TPU's FSM is busy or the weight loader is busy. Inlined rather than factored into a separate module because a 4-line accumulator with one input and one output isn't carrying its own weight as a module:

```systemverilog
// Conceptual perf counter, inlined in top_fpga.sv
always_ff @(posedge clk) begin
  if (!rst_n_physical || perf_read_clear) begin
    perf_cycles <= 32'b0;
  end else if (fsm_busy || loader_busy) begin
    perf_cycles <= perf_cycles + 32'b1;
  end
end
```

Reset domain is `rst_n_physical`, so the counter persists across `tpu_soft_reset` — same as the BRAM weight memory.

### Read-and-clear opcode

A new opcode, `OP_READ_CYCLES` (0x0B), snapshots the counter into a host_controller-owned register and clears the counter on the same clock edge. Response shape: 4 bytes LE + ACK = 5 bytes total.

The clear-on-read design uses dedicated opcode semantics rather than overloading `OP_RESET`. This is a hygiene call — adding a hidden side effect to an existing opcode would have worked, no test would have caught the change, but the opcode contract gets murkier with each such overload. A dedicated opcode keeps each opcode meaning exactly one thing, which pays off the next time someone (or future-me) reads the protocol spec without the implementation in front of them.

The snapshot timing relies on same-edge non-blocking semantics: `cycles_latch <= perf_cycles` captures the value before the clear takes effect on the next edge. Correct-by-construction in the SystemVerilog scheduling model.

### CPU cycle counter

Standard RISC-V `rdcycle` CSR read. PicoRV32 with `ENABLE_COUNTERS=1` exposes a 64-bit free-running cycle counter that increments every CPU cycle. The 32-bit `rdcycle` reads the lower half, which is sufficient for individual sample measurements (~5M cycles, well under 2³²).

### Symmetry check

Both counters cover analogous work:

- TPU `fsm_busy | loader_busy` — FSM cycles plus weight loader cycles. Captures matmul + drain + activation + BRAM-to-buffer fetch.
- CPU `rdcycle` window — matmul (with implicit RAM loads of weights into CPU registers) + activation + saturation, all in software.

Both exclude UART RX / TX and opcode dispatch. The comparison is fair: same workload, same data, same arithmetic, same output verification.

---

## Results

### MNIST, 100 samples, Arty A7-100T at 100 MHz

| | TPU (single mode) | TPU (batch ×8) | PicoRV32 |
|---|---|---|---|
| Bit-exact accuracy | 100% | 100% | 100% |
| Avg cycles / sample | 36,940 | **4,618** | 5,353,626 |
| Min / max cycles | 36,940 / 36,940 | 36,940 / 36,940 | 4,409,430 / 6,714,237 |
| Cycle variance | 0 | **0** | ±1.2M |
| Compute time @ 100 MHz | 0.37 ms | **0.046 ms** | 53.5 ms |
| Speedup vs PicoRV32 | 145× | **1,160×** | 1× |

### Wall-clock vs cycle-count: the Amdahl divergence

Per-sample wall-clock numbers, on the same hardware:

| | Wall-clock per sample | Compute time @ 100 MHz |
|---|---|---|
| TPU (batch ×8, 921600 baud) | ~1.0 s | 0.046 ms |
| PicoRV32 (115200 baud) | ~0.25 s | 53.5 ms |

The wall-clock number reverses the apparent winner. The CPU is faster wall-clock-wise even though the TPU is ~1000× faster at the math.

This is Amdahl's Law in an I/O-bound system. The TPU performs many small per-tile transactions over UART (one EXEC per inner pass, one LOAD_WEIGHT_TILE per tile group), each costing tens of milliseconds in USB-stack round trip. The CPU does a single large round trip per sample. With compute being a small fraction of total time on both sides, the design with fewer round trips wins wall-clock — independent of how fast it is at the math.

The architectural number is the cycle ratio (1,160×, batch). The wall-clock number reflects the host-protocol design, not the silicon. Both are honest; they answer different questions.

The next architectural fix — composite opcodes that run many COMPUTEs autonomously per host frame — would close most of the wall-clock gap. It's deferred because the headline benchmark is already in hand and the demonstration of architectural reasoning matters more than the wall-clock improvement.

### Iris, 30 samples, same conditions

| | TPU |
|---|---|
| Bit-exact accuracy | 30 / 30 |
| Classification accuracy | 100% |
| Per-sample cycles | (single tile per layer, no tiling) |

Iris is a feasibility check rather than a performance benchmark — the network fits in one 8×8 pass per layer, so there's nothing for the systolic array's tiling machinery or batching to demonstrate. Its value is verifying the integer-only reference model lines up bit-for-bit with hardware on a real (small) inference workload.

---

## Lessons and Deferred Work

### Lessons worth recording

- **Pipelining is a top-level architectural decision.** Two pipeline registers in `top.sv` closed timing at 100 MHz without modifying any submodule. Submodule encapsulation held end-to-end. The same principle let the BRAM weight subsystem swap in transparently above the TPU boundary.

- **Latch-point matters for mux selects.** Registering a control signal is necessary but not sufficient. *When* it's latched determines correctness. Latching in the same state that uses the signal creates a 1-cycle race; latching at decision time (opcode capture) gives the signal many cycles to stabilize before any datapath operation depends on it.

- **Cycle counts and wall-clock measure different things.** Both are honest; both belong in the writeup. Hiding the wall-clock divergence would make the cycle ratio less credible, not more — engineers who've built FPGA systems before will assume there's a wall-clock catch and read the document looking for it. Surfacing it directly gets ahead of the question.

- **Amdahl's Law applies to I/O too.** Removing the per-tile UART overhead for weights (BRAM subsystem) gave 1.68× wall-clock speedup but exposed activations as the next bottleneck. Knowing where the next bottleneck moves is half the work; chasing the previous one further has diminishing returns.

- **`-nostdlib` blocks libgcc as well as libc.** Hello World worked because it has no multiply. MNIST's `*` operator compiled to `__mulsi3` and the linker couldn't find it. Fix: `-lgcc` in LDFLAGS. Generic gotcha, easy to miss the first time.

- **Two separate bitstreams for the comparison.** Cleanest fairness story, no shared-resource muddying. Same FPGA, same clock, same input data — only the compute architecture differs.

---

## References

- Jouppi et al., *In-Datacenter Performance Analysis of a Tensor Processing Unit*, ISCA 2017 — [arXiv:1704.04760](https://arxiv.org/abs/1704.04760)
- [PicoRV32](https://github.com/YosysHQ/picorv32) — RV32I CPU core, YosysHQ, MIT-licensed
- Xilinx UG901 — *Vivado Design Suite User Guide: Synthesis* (BRAM byte-write inference templates)
- Digilent — *Arty A7 Reference Manual* (board pinout and clock topology)
