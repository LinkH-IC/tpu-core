`default_nettype none

module bypass #(
    parameter ROWS   = 8,
    parameter ACC_W  = 32,
    parameter DATA_W = 8
)(
    input  logic [ROWS-1:0][ACC_W-1:0]      data_in,        // From accumulator
    input  logic [4:0]                      shift_amount,   // Right-shift for requantization
    output logic [ROWS-1:0][DATA_W-1:0]     data_out        // To unified buffer
);

    // Signed INT8 range: [-128, +127]
    localparam signed [ACC_W-1:0] MAX_POS =  ACC_W'(127);
    localparam signed [ACC_W-1:0] MIN_NEG = -ACC_W'(128);

    logic signed [ACC_W-1:0] shifted [ROWS];

    always_comb begin
        for (int r = 0; r < ROWS; r++) begin
            // Step 1: Requantization shift
            shifted[r] = $signed(data_in[r]) >>> shift_amount;

            // Step 2: Clamp to signed INT8 [-128, +127] (no ReLU — negatives preserved)
            if (shifted[r] > MAX_POS)
                data_out[r] = DATA_W'(MAX_POS);
            else if (shifted[r] < MIN_NEG)
                data_out[r] = DATA_W'(MIN_NEG);
            else
                data_out[r] = DATA_W'(shifted[r]);
        end
    end

endmodule

`default_nettype wire
