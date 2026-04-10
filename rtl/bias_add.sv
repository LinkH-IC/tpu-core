`default_nettype none

module bias_add #(
    parameter ROWS  = 8,
    parameter COLS  = 8,
    parameter ACC_W = 32
)(
    input  logic                        clk,
    input  logic                        rst_n,

    // Host write port — one bias per column
    input  logic [$clog2(COLS)-1:0]     wr_addr,
    input  logic [ACC_W-1:0]            wr_data,
    input  logic                        wr_en,

    // Datapath — combinational add
    input  logic [ROWS-1:0][ACC_W-1:0]  data_in,
    input  logic [$clog2(COLS)-1:0]     col_idx,
    output logic [ROWS-1:0][ACC_W-1:0]  data_out
);

    // ── Bias Register File (one 32-bit value per column) ─────
    logic signed [ACC_W-1:0] bias_reg [COLS];

    // ── Host Write ───────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int i = 0; i < COLS; i++)
                bias_reg[i] <= '0;
        end else if (wr_en) begin
            bias_reg[wr_addr] <= wr_data;
        end
    end

    // ── Combinational Bias Addition ──────────────────────────
    //   Every row in the current drain column gets the same bias
    always_comb begin
        for (int r = 0; r < ROWS; r++)
            data_out[r] = data_in[r] + bias_reg[col_idx];
    end

endmodule

`default_nettype wire
