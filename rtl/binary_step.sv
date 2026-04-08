`default_nettype none

module binary_step #(
    parameter ROWS   = 8,
    parameter ACC_W  = 32,
    parameter DATA_W = 8
)(
    input  logic [ROWS-1:0][ACC_W-1:0]      data_in,        // From accumulator
    output logic [ROWS-1:0][DATA_W-1:0]     data_out        // To unified buffer
);

    // Output: 1 if input > 0, else 0.  No shift needed.
    always_comb begin
        for (int r = 0; r < ROWS; r++) begin
            if ($signed(data_in[r]) > 0)
                data_out[r] = DATA_W'(1);
            else
                data_out[r] = '0;
        end
    end

endmodule

`default_nettype wire
