# =============================================================================
# Makefile — cocotb testbench for unified_buffer.sv
# Run from tb/unified_buffer/ directory:  make
# Clean:                                  make clean
# =============================================================================

SIM           ?= verilator
TOPLEVEL_LANG ?= verilog

# RTL source
VERILOG_SOURCES = ../../rtl/unified_buffer.sv

TOPLEVEL = unified_buffer
MODULE   = tb_unified_buffer

# Verilator flags
EXTRA_ARGS += --timing --trace -Wall -Wno-DECLFILENAME

include $(shell cocotb-config --makefiles)/Makefile.sim

# Clean rule
clean::
	rm -rf sim_build results.xml __pycache__ dump.vcd