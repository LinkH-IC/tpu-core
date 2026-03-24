// =============================================================================
// tb_pe.sv — Testbench for pe.sv (Processing Element)
// Project  : TPU Systolic Array Core
// Toolchain: Verilator + GTKWave
// =============================================================================

`timescale 1ns/1ps

module tb_pe;

  // ---------------------------------------------------------------------------
  // Parameters (must match pe.sv)
  // ---------------------------------------------------------------------------
  localparam DATA_W = 8;
  localparam ACC_W  = 32;
  localparam CLK_PERIOD = 10; // ns

  // ---------------------------------------------------------------------------
  // DUT signals
  // ---------------------------------------------------------------------------
  logic                clk;
  logic                rst_n;
  logic signed [DATA_W-1:0] weight_in;
  logic                weight_load;
  logic signed [DATA_W-1:0] act_in;
  logic signed [DATA_W-1:0] act_out;
  logic signed [ACC_W-1:0]  psum_in;
  logic signed [ACC_W-1:0]  psum_out;
  logic                valid_in;
  logic                valid_out;

  // ---------------------------------------------------------------------------
  // DUT instantiation
  // ---------------------------------------------------------------------------
  pe #(
    .DATA_W(DATA_W),
    .ACC_W (ACC_W)
  ) dut (
    .clk        (clk),
    .rst_n      (rst_n),
    .weight_in  (weight_in),
    .weight_load(weight_load),
    .act_in     (act_in),
    .act_out    (act_out),
    .psum_in    (psum_in),
    .psum_out   (psum_out),
    .valid_in   (valid_in),
    .valid_out  (valid_out)
  );

  // ---------------------------------------------------------------------------
  // Clock generation
  // ---------------------------------------------------------------------------
  initial clk = 0;
  always #(CLK_PERIOD/2) clk = ~clk;

  // ---------------------------------------------------------------------------
  // VCD dump for GTKWave
  // ---------------------------------------------------------------------------
  initial begin
    $dumpfile("dump.vcd");
    $dumpvars(0, tb_pe);
  end

  // ---------------------------------------------------------------------------
  // Test tracking
  // ---------------------------------------------------------------------------
  int pass_count = 0;
  int fail_count = 0;

  // ---------------------------------------------------------------------------
  // Tasks
  // ---------------------------------------------------------------------------

  // Apply synchronous active-low reset for N cycles
  task automatic apply_reset(input int cycles = 2);
    rst_n = 0;
    repeat (cycles) @(posedge clk);
    #1; // small delta after clock edge before releasing
    rst_n = 1;
  endtask

  // Drive a single cycle of inputs and advance the clock
  task automatic drive(
    input logic signed [DATA_W-1:0] w_in,
    input logic                     w_load,
    input logic signed [DATA_W-1:0] a_in,
    input logic signed [ACC_W-1:0]  ps_in,
    input logic                     v_in
  );
    weight_in   = w_in;
    weight_load = w_load;
    act_in      = a_in;
    psum_in     = ps_in;
    valid_in    = v_in;
    @(posedge clk);
    #1; // sample outputs just after clock edge
  endtask

  // Idle inputs — no load, no valid
  task automatic idle();
    drive(0, 0, 0, 0, 0);
  endtask

  // Check helper — prints PASS/FAIL and tracks count
  task automatic check(
    input string          test_name,
    input logic signed [ACC_W-1:0]  got_psum,
    input logic signed [ACC_W-1:0]  exp_psum,
    input logic signed [DATA_W-1:0] got_act,
    input logic signed [DATA_W-1:0] exp_act,
    input logic                     got_valid,
    input logic                     exp_valid
  );
    bit psum_ok  = (got_psum  === exp_psum);
    bit act_ok   = (got_act   === exp_act);
    bit valid_ok = (got_valid === exp_valid);

    if (psum_ok && act_ok && valid_ok) begin
      $display("  PASS  %s", test_name);
      pass_count++;
    end else begin
      $display("  FAIL  %s", test_name);
      if (!psum_ok)
        $display("         psum_out : got %0d, expected %0d", got_psum, exp_psum);
      if (!act_ok)
        $display("         act_out  : got %0d, expected %0d", got_act, exp_act);
      if (!valid_ok)
        $display("         valid_out: got %0b, expected %0b", got_valid, exp_valid);
      fail_count++;
    end
  endtask

  // ---------------------------------------------------------------------------
  // Test stimulus
  // ---------------------------------------------------------------------------
  initial begin
    // ------------------------------------------------------------------
    // Initialise all inputs before reset
    // ------------------------------------------------------------------
    weight_in   = 0;
    weight_load = 0;
    act_in      = 0;
    psum_in     = 0;
    valid_in    = 0;

    $display("=== tb_pe: Processing Element Testbench ===");

    // ==================================================================
    // TEST 1 — Reset clears all outputs
    // ==================================================================
    $display("\n[1] Reset behaviour");
    apply_reset(3);
    #1;
    check("Reset: psum_out=0, act_out=0, valid_out=0",
          psum_out, 32'sd0, act_out, 8'sd0, valid_out, 1'b0);

    // ==================================================================
    // TEST 2 — Weight load: weight latched on weight_load strobe
    // ==================================================================
    $display("\n[2] Weight loading");

    // Load weight = 5, then do one MAC with act_in = 3, psum_in = 0
    drive(8'sd5, 1, 8'sd0, 32'sd0, 0); // cycle: load weight=5, no MAC
    drive(8'sd0, 0, 8'sd3, 32'sd0, 1); // cycle: valid MAC
    // After this edge: psum_out should = 0 + 5*3 = 15
    check("Weight load: 5*3 = 15",
          psum_out, 32'sd15, act_out, 8'sd3, valid_out, 1'b1);

    // ==================================================================
    // TEST 3 — Weight sticky: weight holds when weight_load de-asserted
    // ==================================================================
    $display("\n[3] Weight sticky");

    apply_reset();
    // Load weight = 7
    drive(8'sd7, 1, 8'sd0, 32'sd0, 0);
    // Drive weight_in = 99 WITHOUT weight_load; weight should stay 7
    drive(8'sd99, 0, 8'sd2, 32'sd0, 1); // should use weight=7, not 99
    // psum_out = 0 + 7*2 = 14
    check("Weight sticky: 7*2=14 (weight_in=99 ignored)",
          psum_out, 32'sd14, act_out, 8'sd2, valid_out, 1'b1);

    // ==================================================================
    // TEST 4 — MAC holds when valid_in is low
    // ==================================================================
    $display("\n[4] MAC hold on valid_in=0");

    apply_reset();
    drive(8'sd4, 1, 8'sd0, 32'sd0, 0); // load weight=4
    drive(8'sd0, 0, 8'sd5, 32'sd0, 1); // valid MAC: psum=4*5=20
    drive(8'sd0, 0, 8'sd9, 32'sd99, 0); // valid_in=0: psum should HOLD at 20
    check("MAC hold: psum stays 20 when valid_in=0",
          psum_out, 32'sd20, act_out, 8'sd9, valid_out, 1'b0);

    // ==================================================================
    // TEST 5 — act_out always shifts (even when valid_in=0)
    // ==================================================================
    $display("\n[5] act_out always propagates");

    apply_reset();
    // Push act_in=42 with valid_in=0 — act_out should still register it
    drive(8'sd0,  0, 8'sd42, 32'sd0, 0);
    // After this edge: act_out should be 42
    check("act_out: 42 registered even with valid_in=0",
          psum_out, 32'sd0, act_out, 8'sd42, valid_out, 1'b0);

    // Push act_in=-7 with valid_in=0
    drive(8'sd0,  0, -8'sd7, 32'sd0, 0);
    check("act_out: -7 registered with valid_in=0",
          psum_out, 32'sd0, act_out, -8'sd7, valid_out, 1'b0);

    // ==================================================================
    // TEST 6 — valid_out propagates with 1-cycle delay
    // ==================================================================
    $display("\n[6] valid_out pipeline");

    apply_reset();
    drive(8'sd1, 1, 8'sd0, 32'sd0, 0); // load weight=1
    // valid_in goes high
    weight_in   = 0;
    weight_load = 0;
    act_in      = 8'sd1;
    psum_in     = 32'sd0;
    valid_in    = 1;
    @(posedge clk); #1;
    // valid_out should now be 1
    check("valid_out: 1 after 1 cycle delay",
          psum_out, 32'sd1, act_out, 8'sd1, valid_out, 1'b1);
    // De-assert valid_in
    valid_in = 0;
    @(posedge clk); #1;
    check("valid_out: 0 one cycle after valid_in falls",
          psum_out, 32'sd1, act_out, 8'sd0, valid_out, 1'b0);

    // ==================================================================
    // TEST 7 — Accumulation chain: psum_in feeds into accumulation
    // ==================================================================
    $display("\n[7] Accumulation chain");

    apply_reset();
    drive(8'sd3,  1, 8'sd0,  32'sd0,   0); // load weight=3
    drive(8'sd0,  0, 8'sd2,  32'sd0,   1); // psum=0  + 3*2 = 6
    drive(8'sd0,  0, 8'sd4,  32'sd6,   1); // psum=6  + 3*4 = 18
    drive(8'sd0,  0, 8'sd10, 32'sd18,  1); // psum=18 + 3*10= 48
    check("Accumulation chain: 3*(2+4+10)=48",
          psum_out, 32'sd48, act_out, 8'sd10, valid_out, 1'b1);

    // ==================================================================
    // TEST 8 — Signed: negative weight × positive activation
    // ==================================================================
    $display("\n[8] Signed arithmetic");

    apply_reset();
    drive(-8'sd4, 1, 8'sd0,  32'sd0,  0); // load weight=-4
    drive(8'sd0,  0, 8'sd5,  32'sd0,  1); // psum=0 + (-4)*5 = -20
    check("Signed: (-4)*5 = -20",
          psum_out, -32'sd20, act_out, 8'sd5, valid_out, 1'b1);

    // ==================================================================
    // TEST 9 — Signed: negative × negative → positive
    // ==================================================================
    apply_reset();
    drive(-8'sd6, 1, 8'sd0,   32'sd0, 0); // load weight=-6
    drive(8'sd0,  0, -8'sd3,  32'sd0, 1); // psum=0 + (-6)*(-3) = 18
    check("Signed: (-6)*(-3) = 18",
          psum_out, 32'sd18, act_out, -8'sd3, valid_out, 1'b1);

    // ==================================================================
    // TEST 10 — Edge: max INT8 × max INT8 (127 * 127 = 16129)
    // ==================================================================
    $display("\n[10] Max INT8 edge case");

    apply_reset();
    drive(8'sd127, 1, 8'sd0,   32'sd0, 0); // load weight=127
    drive(8'sd0,   0, 8'sd127, 32'sd0, 1); // psum=127*127=16129
    check("Max INT8: 127*127=16129",
          psum_out, 32'sd16129, act_out, 8'sd127, valid_out, 1'b1);

    // ==================================================================
    // TEST 11 — Edge: min INT8 × min INT8 (-128 * -128 = 16384)
    // ==================================================================
    apply_reset();
    drive(-8'sd128, 1, 8'sd0,   32'sd0, 0); // load weight=-128
    drive(8'sd0,    0, -8'sd128, 32'sd0, 1);
    check("Min INT8: (-128)*(-128)=16384",
          psum_out, 32'sd16384, act_out, -8'sd128, valid_out, 1'b1);

    // ==================================================================
    // TEST 12 — Re-reset clears state mid-run
    // ==================================================================
    $display("\n[12] Mid-run reset");

    // Accumulate something first
    drive(8'sd10, 1, 8'sd0,  32'sd0,  0);
    drive(8'sd0,  0, 8'sd10, 32'sd0,  1); // psum=100
    // Now reset
    apply_reset(2);
    #1;
    check("Mid-run reset: all outputs = 0",
          psum_out, 32'sd0, act_out, 8'sd0, valid_out, 1'b0);

    // ==================================================================
    // Summary
    // ==================================================================
    $display("\n==============================================");
    $display("  Results: %0d passed, %0d failed", pass_count, fail_count);
    $display("==============================================");

    if (fail_count == 0)
      $display("  ALL TESTS PASSED");
    else
      $display("  SOME TESTS FAILED — review above");

    $finish;
  end

  // ---------------------------------------------------------------------------
  // Timeout watchdog — catches infinite loops / stalls
  // ---------------------------------------------------------------------------
  initial begin
    #(CLK_PERIOD * 10000);
    $display("TIMEOUT: simulation exceeded limit");
    $finish;
  end

endmodule
