# =============================================================================
# Makefile — cocotb testbench for weight_buffer.sv
# Run from tb/weight_buffer/ directory:  make
# Clean:                                 make clean
# =============================================================================

SIM           ?= verilator
TOPLEVEL_LANG ?= verilog

# RTL source
VERILOG_SOURCES = ../../rtl/activation_buffer.sv

TOPLEVEL = activation_buffer
MODULE   = tb_activation_buffer

# Verilator flags
EXTRA_ARGS += --timing --trace -Wall -Wno-DECLFILENAME

include $(shell cocotb-config --makefiles)/Makefile.sim
