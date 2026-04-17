# Clock: 100 MHz, 10 ns period
create_clock -name clk -period 10.0 [get_ports clk]

# Clock uncertainty: jitter + skew estimate (pre-P&R)
set_clock_uncertainty 0.5 [get_clocks clk]

# Input delay: signals arrive 2 ns after clock edge
set_input_delay -clock clk 2.0 [all_outputs]

# Output delay: signals must settle 2 ns before next edge
set_output_delay -clock clk 2.0 [all_outputs]

# False paths: quasi-static configuration signals
set_false_path -from [get_ports rst_n]
set_false_path -from [get_ports {act_sel[*]}]
set_false_path -from [get_ports {leak_shift[*]}]
set_false_path -from [get_ports {shift_amount[*]}]
