// =============================================================================
// tb_relu.sv — Testbench for relu.sv (ReLU + Scale + Clamp)
// Project  : TPU Systolic Array Core
// Toolchain: Verilator + GTKWave
//
// Tests:
//   T1 — All zeros input
//   T2 — All positive, no shift — pass through, clamp check
//   T3 — All negative — output should be zero (ReLU clips)
//   T4 — Mixed positive/negative
//   T5 — Shift amount: right-shift reduces value
//   T6 — Clamp: large positive saturates to 127 after shift
//   T7 — Shift boundary: value exactly 127 after shift
//   T8 — Maximum shift (31): any reasonable value goes to 0
//   T9 — Per-row independence: each row operates independently
// =============================================================================

`timescale 1ns/1ps

module tb_relu;

    // -----------------------------------------------------------------------
    // Parameters (must match relu.sv)
    // -----------------------------------------------------------------------
    localparam ROWS   = 8;
    localparam ACC_W  = 32;
    localparam DATA_W = 8;

    // -----------------------------------------------------------------------
    // DUT signals
    // -----------------------------------------------------------------------
    logic [ROWS-1:0][ACC_W-1:0]  data_in;
    logic [4:0]                  shift_amount;
    logic [ROWS-1:0][DATA_W-1:0] data_out;

    // -----------------------------------------------------------------------
    // DUT instantiation
    // -----------------------------------------------------------------------
    relu #(
        .ROWS   (ROWS),
        .ACC_W  (ACC_W),
        .DATA_W (DATA_W)
    ) dut (
        .data_in      (data_in),
        .shift_amount (shift_amount),
        .data_out     (data_out)
    );

    // -----------------------------------------------------------------------
    // VCD dump for GTKWave
    // -----------------------------------------------------------------------
    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, tb_relu);
    end

    // -----------------------------------------------------------------------
    // Test tracking
    // -----------------------------------------------------------------------
    int pass_count = 0;
    int fail_count = 0;

    // -----------------------------------------------------------------------
    // Helper functions
    // -----------------------------------------------------------------------

    // Compute expected ReLU + shift + clamp for a single row
    function automatic logic signed [DATA_W-1:0] relu_ref(
        input logic signed [ACC_W-1:0] val,
        input int shift
    );
        logic signed [ACC_W-1:0] clipped;
        logic signed [ACC_W-1:0] shifted;

        // Step 1: ReLU
        if (val < 0)
            clipped = 0;
        else
            clipped = val;

        // Step 2: Arithmetic right shift
        shifted = clipped >>> shift;

        // Step 3: Clamp to [0, 127]
        if (shifted > 127)
            return DATA_W'(127);
        else
            return DATA_W'(shifted);
    endfunction

    // Extract signed int8 from row r of data_out
    function automatic logic signed [DATA_W-1:0] get_row(input int r);
        return data_out[r];
    endfunction

    // -----------------------------------------------------------------------
    // Tasks
    // -----------------------------------------------------------------------

    // Drive all 8 rows with the same value
    task automatic drive_uniform(
        input logic signed [ACC_W-1:0] val,
        input logic [4:0] shift
    );
        for (int r = 0; r < ROWS; r++)
            data_in[r] = val;
        shift_amount = shift;
        #1;
    endtask

    // Drive each row with a different value
    task automatic drive_per_row(
        input logic signed [ACC_W-1:0] vals [ROWS],
        input logic [4:0] shift
    );
        for (int r = 0; r < ROWS; r++)
            data_in[r] = vals[r];
        shift_amount = shift;
        #1;
    endtask

    // Check all rows against expected (uniform)
    task automatic check_uniform(
        input string test_name,
        input logic signed [DATA_W-1:0] expected
    );
        bit all_ok = 1;
        for (int r = 0; r < ROWS; r++) begin
            if (get_row(r) !== expected) begin
                all_ok = 0;
                $display("  FAIL  %s — row %0d: got %0d, expected %0d",
                         test_name, r, get_row(r), expected);
            end
        end
        if (all_ok) begin
            $display("  PASS  %s", test_name);
            pass_count++;
        end else begin
            fail_count++;
        end
    endtask

    // Check all rows against per-row expected values
    task automatic check_per_row(
        input string test_name,
        input logic signed [DATA_W-1:0] expected [ROWS]
    );
        bit all_ok = 1;
        for (int r = 0; r < ROWS; r++) begin
            if (get_row(r) !== expected[r]) begin
                all_ok = 0;
                $display("  FAIL  %s — row %0d: got %0d, expected %0d",
                         test_name, r, get_row(r), expected[r]);
            end
        end
        if (all_ok) begin
            $display("  PASS  %s", test_name);
            pass_count++;
        end else begin
            fail_count++;
        end
    endtask

    // -----------------------------------------------------------------------
    // Test stimulus
    // -----------------------------------------------------------------------
    initial begin
        // Initialise
        data_in      = '0;
        shift_amount = 0;

        $display("=== tb_relu: ReLU + Scale + Clamp Testbench ===");

        // ==============================================================
        // TEST 1 — All zeros
        // ==============================================================
        $display("\n[1] All zeros");
        drive_uniform(32'sd0, 5'd0);
        check_uniform("All zeros, shift=0: output 0", 8'sd0);

        // ==============================================================
        // TEST 2 — All positive, no shift
        // ==============================================================
        $display("\n[2] Positive passthrough");
        drive_uniform(32'sd42, 5'd0);
        check_uniform("Positive 42, shift=0: output 42", 8'sd42);

        drive_uniform(32'sd127, 5'd0);
        check_uniform("Positive 127, shift=0: output 127", 8'sd127);

        // ==============================================================
        // TEST 3 — All negative (ReLU clips to 0)
        // ==============================================================
        $display("\n[3] Negative clipping");
        drive_uniform(-32'sd1, 5'd0);
        check_uniform("Negative -1, shift=0: output 0", 8'sd0);

        drive_uniform(-32'sd1000, 5'd0);
        check_uniform("Negative -1000, shift=0: output 0", 8'sd0);

        drive_uniform(32'sh80000000, 5'd0);  // INT32_MIN
        check_uniform("INT32_MIN, shift=0: output 0", 8'sd0);

        // ==============================================================
        // TEST 4 — Mixed positive/negative
        // ==============================================================
        $display("\n[4] Mixed positive/negative");
        begin
            logic signed [ACC_W-1:0] mixed_in  [ROWS];
            logic signed [DATA_W-1:0] mixed_exp [ROWS];
            mixed_in[0] = 32'sd10;   mixed_exp[0] = 8'sd10;
            mixed_in[1] = -32'sd5;   mixed_exp[1] = 8'sd0;
            mixed_in[2] = 32'sd100;  mixed_exp[2] = 8'sd100;
            mixed_in[3] = -32'sd200; mixed_exp[3] = 8'sd0;
            mixed_in[4] = 32'sd0;    mixed_exp[4] = 8'sd0;
            mixed_in[5] = 32'sd1;    mixed_exp[5] = 8'sd1;
            mixed_in[6] = -32'sd1;   mixed_exp[6] = 8'sd0;
            mixed_in[7] = 32'sd127;  mixed_exp[7] = 8'sd127;
            drive_per_row(mixed_in, 5'd0);
            check_per_row("Mixed values, shift=0", mixed_exp);
        end

        // ==============================================================
        // TEST 5 — Shift reduces value
        // ==============================================================
        $display("\n[5] Shift scaling");
        // 256 >> 1 = 128 → clamps to 127
        drive_uniform(32'sd256, 5'd1);
        check_uniform("256 >> 1 = 128 → clamp 127", 8'sd127);

        // 256 >> 2 = 64
        drive_uniform(32'sd256, 5'd2);
        check_uniform("256 >> 2 = 64", 8'sd64);

        // 1024 >> 4 = 64
        drive_uniform(32'sd1024, 5'd4);
        check_uniform("1024 >> 4 = 64", 8'sd64);

        // 16384 >> 8 = 64
        drive_uniform(32'sd16384, 5'd8);
        check_uniform("16384 >> 8 = 64", 8'sd64);

        // ==============================================================
        // TEST 6 — Large positive saturates to 127
        // ==============================================================
        $display("\n[6] Saturation clamp");
        // 10000 >> 0 → clamp to 127
        drive_uniform(32'sd10000, 5'd0);
        check_uniform("10000 >> 0 → clamp 127", 8'sd127);

        // 10000 >> 3 = 1250 → clamp to 127
        drive_uniform(32'sd10000, 5'd3);
        check_uniform("10000 >> 3 = 1250 → clamp 127", 8'sd127);

        // 10000 >> 7 = 78
        drive_uniform(32'sd10000, 5'd7);
        check_uniform("10000 >> 7 = 78", 8'sd78);

        // ==============================================================
        // TEST 7 — Exact boundary: value is exactly 127 after shift
        // ==============================================================
        $display("\n[7] Exact boundary");
        // 127 >> 0 = 127 — exactly at max, no clamp
        drive_uniform(32'sd127, 5'd0);
        check_uniform("127 >> 0 = 127 (exact boundary)", 8'sd127);

        // 254 >> 1 = 127
        drive_uniform(32'sd254, 5'd1);
        check_uniform("254 >> 1 = 127 (exact boundary)", 8'sd127);

        // 128 >> 0 = 128 → clamp to 127 (one above)
        drive_uniform(32'sd128, 5'd0);
        check_uniform("128 >> 0 → clamp 127 (one above boundary)", 8'sd127);

        // ==============================================================
        // TEST 8 — Maximum shift (31)
        // ==============================================================
        $display("\n[8] Maximum shift");
        // 2^30 = 1073741824 >> 31 = 0
        drive_uniform(32'sd1073741824, 5'd31);
        check_uniform("2^30 >> 31 = 0", 8'sd0);

        // INT32_MAX = 2147483647 >> 31 = 0
        drive_uniform(32'sh7FFFFFFF, 5'd31);
        check_uniform("INT32_MAX >> 31 = 0", 8'sd0);

        // ==============================================================
        // TEST 9 — Per-row independence
        // ==============================================================
        $display("\n[9] Per-row independence");
        begin
            logic signed [ACC_W-1:0]  indep_in  [ROWS];
            logic signed [DATA_W-1:0] indep_exp [ROWS];
            indep_in[0] = 32'sd0;            indep_exp[0] = 8'sd0;     // 0 >> 4 = 0
            indep_in[1] = 32'sd16;           indep_exp[1] = 8'sd1;     // 16 >> 4 = 1
            indep_in[2] = -32'sd100;         indep_exp[2] = 8'sd0;     // neg → 0
            indep_in[3] = 32'sd2048;         indep_exp[3] = 8'sd127;   // 2048 >> 4 = 128 → 127
            indep_in[4] = 32'sd2032;         indep_exp[4] = 8'sd127;   // 2032 >> 4 = 127
            indep_in[5] = 32'sd1;            indep_exp[5] = 8'sd0;     // 1 >> 4 = 0
            indep_in[6] = 32'sd160;          indep_exp[6] = 8'sd10;    // 160 >> 4 = 10
            indep_in[7] = -32'sd2147483648;  indep_exp[7] = 8'sd0;     // INT32_MIN → 0
            drive_per_row(indep_in, 5'd4);
            check_per_row("Per-row independence, shift=4", indep_exp);
        end

        // ==============================================================
        // Summary
        // ==============================================================
        $display("\n==============================================");
        $display("  Results: %0d passed, %0d failed", pass_count, fail_count);
        $display("==============================================");

        if (fail_count == 0)
            $display("  ALL TESTS PASSED");
        else
            $display("  SOME TESTS FAILED — review above");

        $finish;
    end

    // -----------------------------------------------------------------------
    // Timeout watchdog
    // -----------------------------------------------------------------------
    initial begin
        #10000;
        $display("TIMEOUT: simulation exceeded limit");
        $finish;
    end

endmodule
