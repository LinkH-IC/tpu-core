`default_nettype none

module weight_buffer #(
    parameter ROWS   = 8,
    parameter COLS   = 8,
    parameter DATA_W = 8
)(
    input  logic                            clk,
    input  logic                            rst_n,

    // Host write interface (shadow bank)
    input  logic  [2:0]                     wr_addr,    // Column index 0–7
    input  logic  [ROWS-1:0][DATA_W-1:0]    wr_data,    // All 8 row weights for one column
    input  logic                            wr_en,

    // Control interface
    input  logic                            load_trigger,   // Strobe: copy + sequence
    output logic                            ready,          // Shadow bank writable
    output logic                            done,           // Pulse: array loaded

    // Systolic array interface
    output logic [ROWS-1:0][DATA_W-1:0]     weight_out,     // Weight bus to array
    output logic [COLS-1:0]                 weight_load     // Per-column load strobe
);

    // ── Internal Parameters ──────────────────────────────────────
    localparam CNT_W    = $clog2(COLS);
    localparam CNT_END  = CNT_W'(COLS - 1);

    // ── FSM States ───────────────────────────────────────────────
    typedef enum logic [1:0] {
        IDLE     = 2'b00,
        COPY     = 2'b01,
        SEQUENCE = 2'b10
    } state_t;

    state_t              state, state_next;
    logic [CNT_W-1:0]    seq_cnt, seq_cnt_next;

    // ── Storage ──────────────────────────────────────────────────
    logic [DATA_W-1:0]   shadow [ROWS][COLS];
    logic [DATA_W-1:0]   active [ROWS][COLS];

    // ── State Register ───────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state   <= IDLE;
            seq_cnt <= '0;
        end else begin
            state   <= state_next;
            seq_cnt <= seq_cnt_next;
        end
    end

    // ── Next-State Logic ─────────────────────────────────────────
    always_comb begin
        state_next   = state;
        seq_cnt_next = '0;

        case (state)
            IDLE: begin
                if (load_trigger)
                    state_next = COPY;
            end

            COPY: begin
                state_next = SEQUENCE;
            end

            SEQUENCE: begin
                if (seq_cnt == CNT_END)
                    state_next = IDLE;
                else
                    seq_cnt_next = seq_cnt + CNT_W'(1);
            end

            default: state_next = IDLE;
        endcase
    end

    // ── Shadow Bank — Host Write ─────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                    shadow[r][c] <= '0;
        end else if (wr_en && ready) begin
            for (int r = 0; r < ROWS; r++)
                shadow[r][wr_addr] <= wr_data[r];
        end
    end

    // ── Active Bank — Copy from Shadow ───────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                    active[r][c] <= '0;
        end else if (state == COPY) begin
            for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                    active[r][c] <= shadow[r][c];
        end
    end

    // ── Sequencer — Drive Array Weights ──────────────────────────
    always_comb begin
        weight_out  = '0;
        weight_load = '0;

        if (state == SEQUENCE) begin
            for (int r = 0; r < ROWS; r++)
                weight_out[r] = active[r][seq_cnt];
            weight_load[seq_cnt] = 1'b1;
        end
    end

    // ── Handshake Outputs ────────────────────────────────────────
    assign ready = (state != COPY);
    assign done  = (state == SEQUENCE) && (seq_cnt == CNT_END);

endmodule

`default_nettype wire
