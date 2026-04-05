# =============================================================================
# Makefile — cocotb testbench for weight_buffer.sv
# Run from tb/weight_buffer/ directory:  make
# Clean:                                 make clean
# =============================================================================

SIM           ?= verilator
TOPLEVEL_LANG ?= verilog

# RTL source
VERILOG_SOURCES = ../../rtl/weight_buffer.sv

TOPLEVEL = weight_buffer
MODULE   = tb_weight_buffer

# Verilator flags
EXTRA_ARGS += --timing --trace -Wall -Wno-DECLFILENAME

include $(shell cocotb-config --makefiles)/Makefile.sim

# Clean rule
clean::
	rm -rf sim_build results.xml __pycache__ dump.vcd