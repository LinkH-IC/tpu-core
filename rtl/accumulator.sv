`default_nettype none

module accumulator #(
    parameter ROWS   = 8,
    parameter COLS   = 8,
    parameter ACC_W  = 32
)(
    input  logic                           clk,
    input  logic                           rst_n,

    // Systolic array interface
    input  logic  [COLS-1:0][ACC_W-1:0]    psum_in,        // From array bottom edge
    input  logic  [COLS-1:0]               valid_in,       // Per-column valid from array

    // FSM control
    input  logic                           clear,          // Zero all registers and counters
    input  logic                           drain_trigger,  // Start draining results to ReLU

    // Output interface (to ReLU)
    output logic [ROWS-1:0][ACC_W-1:0]     acc_out,         // One row of results during drain
    output logic [$clog2(COLS)-1:0]        col_idx,         // Which row is currently being output
    output logic                           acc_valid,       // High for one cycle per row during drain

    // Handshake
    output logic                           pass_done,       // Pulse: all columns received this pass
    output logic                           drain_done       // Pulse: drain finished
);

    // ── Internal Parameters ──────────────────────────────────────
    localparam ROW_W    = $clog2(ROWS);
    localparam COL_W    = $clog2(COLS);
    localparam ROW_END  = ROW_W'(ROWS - 1);
    localparam COL_END  = COL_W'(COLS - 1);

    // ── FSM States ───────────────────────────────────────────────
    typedef enum logic {
        IDLE  = 1'b0,
        DRAIN = 1'b1
    } state_t;

    state_t              state, state_next;
    logic [COL_W-1:0]    drain_cnt, drain_cnt_next;

    // ── Storage — 8×8 register file of 32-bit accumulators ──────
    logic signed [ACC_W-1:0]  acc_reg [ROWS][COLS];

    // ── Per-Column Row Counters and Pass Tracking ────────────────
    logic [ROW_W-1:0]    col_cnt [COLS];
    logic [COLS-1:0]     col_done ;

    // ── State Register ───────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state     <= IDLE;
            drain_cnt <= '0;
        end else begin
            state     <= state_next;
            drain_cnt <= drain_cnt_next;
        end
    end

    // ── Next-State Logic ─────────────────────────────────────────
    always_comb begin
        state_next     = state;
        drain_cnt_next = '0;

        case (state)
            IDLE: begin
                if (drain_trigger)
                    state_next = DRAIN;
            end

            DRAIN: begin
                if (drain_cnt == COL_END)
                    state_next = IDLE;
                else
                    drain_cnt_next = drain_cnt + COL_W'(1);
            end

            default: state_next = IDLE;
        endcase
    end

    // ── Accumulator Registers ────────────────────────────────────
    //   On clear: zero all 64 registers
    //   On valid_in[c]: acc_reg[row][c] += psum_in[c]
    //   where row = col_cnt[c] (per-column row counter)
    //   Accumulation only happens in IDLE state
    always_ff @(posedge clk) begin
        if (!rst_n || clear) begin
            for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                    acc_reg[r][c] <= '0;
        end else if (state == IDLE) begin
            for (int c = 0; c < COLS; c++) begin
                if (valid_in[c])
                    acc_reg[col_cnt[c]][c] <= acc_reg[col_cnt[c]][c] + $signed(psum_in[c]);
            end
        end
    end

    // ── Per-Column Counters and Pass Tracking ────────────────────
    //   col_cnt[c]:  tracks which result row this column is on
    //   col_done[c]: set when column c has received all ROWS valids
    //   pass_done:   pulses when all columns complete one pass
    //   On pass_done: counters and flags reset (acc_reg kept)
    assign pass_done = &col_done;

    always_ff @(posedge clk) begin
        if (!rst_n || clear) begin
            for (int c = 0; c < COLS; c++) begin
                col_cnt[c]  <= '0;
                col_done[c] <= 1'b0;
            end
        end else if (pass_done) begin
            // Reset counters for next tiling pass; acc_reg values preserved
            for (int c = 0; c < COLS; c++) begin
                col_cnt[c]  <= '0;
                col_done[c] <= 1'b0;
            end
        end else begin
            for (int c = 0; c < COLS; c++) begin
                if (valid_in[c] && state == IDLE) begin
                    col_cnt[c] <= col_cnt[c] + ROW_W'(1);
                    if (col_cnt[c] == ROW_END)
                        col_done[c] <= 1'b1;
                end
            end
        end
    end

    // ── Drain Sequencer — Output one row per cycle ───────────────
    always_comb begin
        acc_out   = '0;
        acc_valid = 1'b0;
        col_idx   = '0;

        if (state == DRAIN) begin
            for (int r = 0; r < ROWS; r++)
                acc_out[r] = acc_reg[r][drain_cnt];
            col_idx   = drain_cnt;
            acc_valid = 1'b1;
        end
    end

    // ── Done Signal — Drain Complete ─────────────────────────────
    assign drain_done = (state == DRAIN) && (drain_cnt == COL_END);

endmodule

`default_nettype wire
