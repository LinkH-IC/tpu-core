`default_nettype none

module relu #(
    parameter ROWS   = 8,
    parameter ACC_W  = 32,
    parameter DATA_W = 8
)(
    input  logic  [ROWS-1:0][ACC_W-1:0]      data_in,        // From accumulator
    input  logic  [4:0]                      shift_amount,   // Right-shift for requantization
    output logic  [ROWS-1:0][DATA_W-1:0]     data_out        // To unified buffer
);

    // Maximum positive value for signed INT8: 127
    localparam signed [ACC_W-1:0] MAX_POS = ACC_W'((1 << (DATA_W - 1)) - 1);

    // ── Per-Column ReLU + Scale + Clamp ──────────────────────────
    //   Step 1: ReLU   — if value < 0, replace with 0
    //   Step 2: Scale  — arithmetic right-shift by shift_amount
    //   Step 3: Clamp  — saturate to signed INT8 [0, +127]
    //           (minimum is 0 after ReLU, only upper clamp needed)

    logic signed [ACC_W-1:0] clipped [ROWS];
    logic signed [ACC_W-1:0] shifted [ROWS];

    always_comb begin
        for (int r = 0; r < ROWS; r++) begin
            // Step 1: ReLU
            if ($signed(data_in[r]) < 0)
                clipped[r] = '0;
            else
                clipped[r] = $signed(data_in[r]);

            // Step 2: Scale (right-shift; value is non-negative after ReLU)
            shifted[r] = clipped[r] >>> shift_amount;

            // Step 3: Clamp to [0, 127]
            if (shifted[r] > MAX_POS)
                data_out[r] = DATA_W'(MAX_POS);
            else
                data_out[r] = DATA_W'(shifted[r]);
        end
    end

endmodule

`default_nettype wire
