`default_nettype none

module unified_buffer #(
    parameter ROWS   = 8,
    parameter COLS   = 8,
    parameter DATA_W = 8
)(
    input  logic                            clk,
    input  logic                            rst_n,

    // Write interface
    input  logic [2:0]                      wr_addr,        // Column index 0–7
    input  logic [ROWS-1:0][DATA_W-1:0]     wr_data,        // All 8 row values for one column
    input  logic                            wr_en,

    // Computation control interface
    input  logic                            load_trigger,   // Strobe: copy write → active, then stream
    output logic                            ready,          // Write bank accepts writes
    output logic                            load_done,      // Pulse: streaming finished

    // Systolic array interface
    output logic [ROWS-1:0][DATA_W-1:0]     act_out,        // Activation bus to array
    output logic [ROWS-1:0]                 valid,          // Asserted during STREAM phase

    // Result bank control
    input  logic                            store_trigger,  // Strobe: copy write → result bank
    output logic                            store_done,     // Pulse: result bank copy complete

    // Host read interface
    input  logic [2:0]                      rd_addr,        // Column index 0–7
    input  logic                            rd_en,          // Host read enable
    output logic [ROWS-1:0][DATA_W-1:0]     rd_data         // One column from result bank (registered)
);

    // ── Internal Parameters ──────────────────────────────────────
    localparam CNT_W    = $clog2(COLS);
    localparam CNT_END  = CNT_W'(COLS - 1);

    // ── FSM States ───────────────────────────────────────────────
    typedef enum logic [1:0] {
        IDLE   = 2'b00,
        COPY   = 2'b01,
        STREAM = 2'b10,
        STORE  = 2'b11
    } state_t;

    state_t              state, state_next;
    logic [CNT_W-1:0]    seq_cnt, seq_cnt_next;

    // ── Storage ──────────────────────────────────────────────────
    logic [DATA_W-1:0]   write  [ROWS][COLS];
    logic [DATA_W-1:0]   active [ROWS][COLS];
    logic [DATA_W-1:0]   result [ROWS][COLS];

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
                // load_trigger takes priority over store_trigger
                if (load_trigger)
                    state_next = COPY;
                else if (store_trigger)
                    state_next = STORE;
            end

            COPY: begin
                state_next = STREAM;
            end

            STREAM: begin
                if (seq_cnt == CNT_END)
                    state_next = IDLE;
                else
                    seq_cnt_next = seq_cnt + CNT_W'(1);
            end

            STORE: begin
                state_next = IDLE;
            end

            default: state_next = IDLE;
        endcase
    end

    // ── Write Bank — Host / Feedback Write ───────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                    write[r][c] <= '0;
        end else if (wr_en && ready) begin
            for (int r = 0; r < ROWS; r++)
                write[r][wr_addr] <= wr_data[r];
        end
    end

    // ── Active Bank — Copy from Write Bank ───────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                    active[r][c] <= '0;
        end else if (state == COPY) begin
            for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                    active[r][c] <= write[c][r];
        end
    end

    // ── Result Bank — Copy from Write Bank ───────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                    result[r][c] <= '0;
        end else if (state == STORE) begin
            for (int r = 0; r < ROWS; r++)
                for (int c = 0; c < COLS; c++)
                    result[r][c] <= write[r][c];
        end
    end

    // ── Sequencer — Drive Array Activations ──────────────────────
    always_comb begin
        act_out = '0;
        valid   = '0;

        if (state == STREAM) begin
            for (int r = 0; r < ROWS; r++)
                act_out[r] = active[r][seq_cnt];
            valid = '1;
        end
    end

    // ── Host Read — Result Bank (Registered) ─────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            rd_data <= '0;
        end else if (rd_en) begin
            for (int r = 0; r < ROWS; r++)
                rd_data[r] <= result[r][rd_addr];
        end else begin
            rd_data <= '0;
        end
    end

    // ── Handshake Outputs ────────────────────────────────────────
    assign ready      = (state == IDLE) || (state == STREAM);
    assign load_done  = (state == STREAM) && (seq_cnt == CNT_END);
    assign store_done = (state == STORE);

endmodule

`default_nettype wire
