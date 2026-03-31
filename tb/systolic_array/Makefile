# =============================================================================
# Makefile — cocotb testbench for systolic_array.sv
# Run from tb/ directory:  make
# Clean:                   make clean
# =============================================================================

SIM           ?= verilator
TOPLEVEL_LANG ?= verilog

# RTL sources — pe.sv must come first (instantiated by systolic_array)
VERILOG_SOURCES = \
    ../../rtl/pe.sv \
    ../../rtl/systolic_array.sv

TOPLEVEL = systolic_array
MODULE   = tb_systolic_array

# Verilator flags
EXTRA_ARGS += --timing --trace -Wall -Wno-DECLFILENAME

include $(shell cocotb-config --makefiles)/Makefile.sim
