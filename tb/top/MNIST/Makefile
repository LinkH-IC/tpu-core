# =============================================================================
# Makefile — cocotb MNIST inference testbench for top.sv
# Run from tb/top/mnist/ directory:  make
# Clean:                             make clean
# =============================================================================

SIM           ?= verilator
TOPLEVEL_LANG ?= verilog

# RTL source
VERILOG_SOURCES = $(wildcard ../../../rtl/*.sv)

TOPLEVEL = top
MODULE   = tb_mnist

# Verilator flags
EXTRA_ARGS += --timing -Wall -Wno-fatal --trace
EXTRA_ARGS += -I../../rtl

include $(shell cocotb-config --makefiles)/Makefile.sim

# Clean rule
clean::
	rm -rf sim_build results.xml __pycache__ dump.vcd sim.log
