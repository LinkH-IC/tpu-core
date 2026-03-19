// =============================================================================
// Module  : pe (Processing Element)
// Project : TPU Systolic Array Core
// Author  : LinkH-IC
//
// Description:
//   Single MAC unit for a weight-stationary 8×8 systolic array.
//
//   Dataflow (weight-stationary):
//     - Weight is preloaded once via weight_in / weight_load and held in
//       weight_reg for the duration of a tile computation.
//     - Activations stream horizontally: act_in → (registered) → act_out
//     - Partial sums accumulate vertically:
//         psum_out = psum_in + (weight_reg × act_in)
//     - valid_in gates the MAC; when de-asserted the outputs hold their
//       last value so no garbage accumulates downstream.
//
//   Bit-width rationale:
//     - INT8 signed × INT8 signed → 16-bit product (no overflow)
//     - 32-bit accumulator supports up to 2^15 accumulations without
//       overflow, far exceeding the 8×8 tile depth (8 steps).
//
//   Pipeline latency: 1 clock cycle (act and valid are registered).
// =============================================================================

`timescale 1ns / 1ps

module pe #(
    parameter int DATA_W = 8,   // Activation / weight bit-width
    parameter int ACC_W  = 32   // Accumulator / partial-sum bit-width
)(
    input  logic                clk,
    input  logic                rst_n,       // Active-low synchronous reset

    // -------------------------------------------------------------------------
    // Weight preload interface
    // -------------------------------------------------------------------------
    input  logic signed [DATA_W-1:0] weight_in,   // Weight value to preload
    input  logic                     weight_load,  // 1-cycle strobe: latch weight

    // -------------------------------------------------------------------------
    // Activation datapath  (flows left → right across the array)
    // -------------------------------------------------------------------------
    input  logic signed [DATA_W-1:0] act_in,    // From left neighbour / input
    output logic signed [DATA_W-1:0] act_out,   // To right neighbour (registered)

    // -------------------------------------------------------------------------
    // Partial-sum datapath  (flows top → bottom down the array)
    // -------------------------------------------------------------------------
    input  logic signed [ACC_W-1:0]  psum_in,   // From top neighbour / zero
    output logic signed [ACC_W-1:0]  psum_out,  // To bottom neighbour

    // -------------------------------------------------------------------------
    // Flow control
    // -------------------------------------------------------------------------
    input  logic valid_in,    // Qualifies act_in / psum_in
    output logic valid_out    // Propagated valid (registered, matches act_out)
);

    // =========================================================================
    // Internal signals
    // =========================================================================

    logic signed [DATA_W-1:0]       weight_reg;  // Stationary weight storage
    logic signed [2*DATA_W-1:0]     product;     // 16-bit multiply result
    logic signed [ACC_W-1:0]        psum_next;   // Combinational accumulation

    // =========================================================================
    // Weight register — loaded once per tile via weight_load strobe
    // =========================================================================
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            weight_reg <= '0;
        end else if (weight_load) begin
            weight_reg <= weight_in;
        end
    end

    // =========================================================================
    // MAC logic
    //   product  = weight_reg × act_in   (signed 16-bit)
    //   psum_out = psum_in + product      (sign-extended to 32-bit)
    //
    //   The multiply is purely combinational; the result is registered only
    //   as part of psum_out to keep the critical path to one FF stage.
    // =========================================================================
    assign product   = weight_reg * act_in;   // SV signed mult (both operands signed)
    assign psum_next = psum_in + ACC_W'(product); // sign-extend product to 32-bit

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            psum_out <= '0;
        end else if (valid_in) begin
            psum_out <= psum_next;
        end
        // When valid_in is low, psum_out holds its last value.
        // Downstream PEs will also see valid_in=0 and will not accumulate.
    end

    // =========================================================================
    // Activation pipeline register
    //   Registering act_in → act_out creates the one-cycle skew between
    //   columns that produces the correct systolic wave pattern.
    // =========================================================================
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            act_out <= '0;
        end else begin
            act_out <= act_in;   // Always register, regardless of valid
        end
    end

    // =========================================================================
    // Valid pipeline register
    //   Tracks the activation wave; must be registered to stay in phase
    //   with act_out.
    // =========================================================================
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            valid_out <= 1'b0;
        end else begin
            valid_out <= valid_in;
        end
    end

endmodule