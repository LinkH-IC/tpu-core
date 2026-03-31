// =============================================================================
// systolic_array.sv
// 8×8 weight-stationary systolic array
// - Per-row weight broadcast
// - Internal activation staggering (row i delayed by i cycles)
// - Top-row psum_in tied to zero internally
// =============================================================================

`default_nettype none
`timescale 1ns/1ps

module systolic_array #(
    parameter int ROWS   = 8,
    parameter int COLS   = 8,
    parameter int DATA_W = 8,   // Activation / weight bit-width
    parameter int ACC_W  = 32   // Accumulator / partial-sum bit-width
)(
    input  logic                         clk,
    input  logic                         rst_n,

    // Weight loading — per row, broadcast to all columns in that row
    input  logic [ROWS-1:0][DATA_W-1:0]  weight_in,
    input  logic [COLS-1:0]              weight_load,

    // Activation inputs — un-staggered; staggering done internally
    input  logic [ROWS-1:0][DATA_W-1:0]  act_in,
    input  logic [ROWS-1:0]              valid_in,

    // Outputs — bottom edge of each column
    output logic [COLS-1:0][ACC_W-1:0]   psum_out,
    output logic [COLS-1:0]              valid_out
);

    // -------------------------------------------------------------------------
    // Internal wire arrays
    // -------------------------------------------------------------------------

    // Horizontal: act and valid flowing left → right
    // act_h[row][0]    = stagger output (feeds PE[row][0])
    // act_h[row][col+1] = PE[row][col].act_out
    logic [DATA_W-1:0] act_h   [ROWS][COLS+1];
    logic              valid_h [ROWS][COLS+1];

    // Vertical: psum flowing top → bottom
    // psum_v[0][col]     = 0  (top boundary)
    // psum_v[row+1][col] = PE[row][col].psum_out
    logic [ACC_W-1:0]  psum_v  [ROWS+1][COLS];

    // -------------------------------------------------------------------------
    // Top-row psum boundary: tie to zero
    // -------------------------------------------------------------------------
    for (genvar c = 0; c < COLS; c++) begin : g_psum_top
        assign psum_v[0][c] = '0;
    end

    // -------------------------------------------------------------------------
    // Activation stagger — row i delayed by i cycles
    // Row 0: wire through (no delay)
    // Row i: i-stage shift register on both act and valid
    // -------------------------------------------------------------------------

    // stagger_act[row][stage]: stage 0 = first register output
    logic [DATA_W-1:0] stagger_act [ROWS][ROWS];
    logic              stagger_vld [ROWS][ROWS];

    for (genvar i = 0; i < ROWS; i++) begin : g_stagger

        if (i == 0) begin : g_row0
            // No delay — wire directly
            assign act_h[0][0]   = act_in[0];
            assign valid_h[0][0] = valid_in[0];

        end else begin : g_rowN
            // Stage 0: register the raw input
            always_ff @(posedge clk) begin
                if (!rst_n) begin
                    stagger_act[i][0] <= '0;
                    stagger_vld[i][0] <= 1'b0;
                end else begin
                    stagger_act[i][0] <= act_in[i];
                    stagger_vld[i][0] <= valid_in[i];
                end
            end

            // Stages 1..i-1: chain the shift register
            for (genvar s = 1; s < i; s++) begin : g_stage
                always_ff @(posedge clk) begin
                    if (!rst_n) begin
                        stagger_act[i][s] <= '0;
                        stagger_vld[i][s] <= 1'b0;
                    end else begin
                        stagger_act[i][s] <= stagger_act[i][s-1];
                        stagger_vld[i][s] <= stagger_vld[i][s-1];
                    end
                end
            end

            // Final tap feeds the left edge of this row
            assign act_h[i][0]   = stagger_act[i][i-1];
            assign valid_h[i][0] = stagger_vld[i][i-1];
        end

    end

    // -------------------------------------------------------------------------
    // PE grid — 8×8 instantiation
    // -------------------------------------------------------------------------
    for (genvar r = 0; r < ROWS; r++) begin : g_row
        for (genvar c = 0; c < COLS; c++) begin : g_col
            pe #(
                .DATA_W (DATA_W),
                .ACC_W  (ACC_W)
            ) u_pe (
                .clk         (clk),
                .rst_n       (rst_n),
                // Weight — broadcast from row bus
                .weight_in   (weight_in[r]),
                .weight_load (weight_load[c]),
                // Horizontal activation chain
                .act_in      (act_h[r][c]),
                .act_out     (act_h[r][c+1]),
                .valid_in    (valid_h[r][c]),
                .valid_out   (valid_h[r][c+1]),
                // Vertical psum chain
                .psum_in     (psum_v[r][c]),
                .psum_out    (psum_v[r+1][c])
            );
        end
    end

    // -------------------------------------------------------------------------
    // Output assignments — bottom edge
    // -------------------------------------------------------------------------
    for (genvar c = 0; c < COLS; c++) begin : g_out
        assign psum_out[c]  = psum_v[ROWS][c];
        // valid_out for column c: take valid from bottom-right of each row
        // Specifically: valid_h[ROWS-1][c+1] tells us row 7's valid
        // has reached column c — meaning column c has received all inputs
        assign valid_out[c] = valid_h[ROWS-1][c+1];
    end

endmodule

`default_nettype wire
