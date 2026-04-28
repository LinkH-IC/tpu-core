# =============================================================================
# Makefile — cocotb testbench for accumulator.sv
# Run from tb/accumulator/ directory:  make
# Clean:                               make clean
# =============================================================================

SIM           ?= verilator
TOPLEVEL_LANG ?= verilog

# RTL source
VERILOG_SOURCES = ../../rtl/accumulator.sv

TOPLEVEL = accumulator
MODULE   = tb_accumulator

# Verilator flags
EXTRA_ARGS += --timing --trace -Wall --trace-structs

include $(shell cocotb-config --makefiles)/Makefile.sim

# Clean rule
clean::
	rm -rf sim_build results.xml __pycache__ dump.vcd