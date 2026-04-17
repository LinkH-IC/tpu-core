# ============================================================================
# TPU Core — OpenSTA Timing Analysis Script
# Usage:  sta run_sta.tcl 2>&1 | tee sta.log
# Prerequisites: synth.ys must have been run first (netlist must exist)
# ============================================================================


# ---- Read Liberty ----
read_liberty sky130_fd_sc_hd__tt_025C_1v80.lib

# ---- Read Gate-Level Netlist ----
read_verilog netlist/top_sky130.v

# ---- Link Design ----
link_design top

# ---- Read Constraints ----
read_sdc timing.sdc

# ============================================================================
# TIMING REPORTS
# ============================================================================

puts "\n================================================================"
puts " SETUP (max-delay) — Worst Paths"
puts "================================================================\n"

# Print summary to stdout
report_checks -path_delay max -sort_by_slack -digits 3

puts "\n================================================================"
puts " HOLD (min-delay) — Worst Paths"
puts "================================================================\n"

report_checks -path_delay min -sort_by_slack -digits 3

puts "\n================================================================"
puts " TIMING SUMMARY"
puts "================================================================\n"

# Total negative slack (TNS) and worst negative slack (WNS)
puts "--- Setup ---"
report_tns
report_wns

puts "\n--- Hold ---"
report_tns -min
report_wns -min

exit
