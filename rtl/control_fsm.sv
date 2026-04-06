`default_nettype none

module control_fsm (
    input  logic        clk,
    input  logic        rst_n,

    // Host command interface
    input  logic [1:0]  cmd,
    input  logic        start,
    output logic        done,

    // Write port mux select
    output logic        mux_sel,        // 0 = HOST, 1 = DRAIN

    // Weight buffer handshake
    output logic        wb_load_trigger,
    input  logic        wb_done,

    // Unified buffer handshake
    output logic        ub_load_trigger,
    input  logic        ub_load_done,
    output logic        ub_store_trigger,
    input  logic        ub_store_done,

    // Accumulator handshake
    output logic        acc_clear,
    output logic        acc_drain_trigger,
    input  logic        acc_pass_done,
    input  logic        acc_drain_done
);

    // ── Command Encoding ───────────────────────────────────────
    localparam logic [1:0] CMD_COMPUTE = 2'b00,
                           CMD_DRAIN   = 2'b01,
                           CMD_STORE   = 2'b10,
                           CMD_CLEAR   = 2'b11;

    // ── FSM States ─────────────────────────────────────────────
    typedef enum logic [2:0] {
        IDLE         = 3'b000,
        LOAD_W       = 3'b001,
        WAIT_W       = 3'b010,
        LOAD_A       = 3'b011,
        COMPUTE_WAIT = 3'b100,
        DRAIN_RUN    = 3'b101,
        STORE_RUN    = 3'b110,
        CLEAR_RUN    = 3'b111
    } state_t;

    state_t state, state_next;

    // ── State Register ─────────────────────────────────────────
    always_ff @(posedge clk) begin
        if (!rst_n)
            state <= IDLE;
        else
            state <= state_next;
    end

    // ── Next-State Logic ───────────────────────────────────────
    always_comb begin
        state_next = state;

        case (state)
            IDLE: begin
                if (start) begin
                    case (cmd)
                        CMD_COMPUTE: state_next = LOAD_W;
                        CMD_DRAIN:   state_next = DRAIN_RUN;
                        CMD_STORE:   state_next = STORE_RUN;
                        CMD_CLEAR:   state_next = CLEAR_RUN;
                        default:     state_next = IDLE;
                    endcase
                end
            end

            LOAD_W: begin
                state_next = WAIT_W;
            end

            WAIT_W: begin
                if (wb_done)
                    state_next = LOAD_A;
            end

            LOAD_A: begin
                state_next = COMPUTE_WAIT;
            end

            COMPUTE_WAIT: begin
                if (acc_pass_done)
                    state_next = IDLE;
            end

            DRAIN_RUN: begin
                if (acc_drain_done)
                    state_next = IDLE;
            end

            STORE_RUN: begin
                if (ub_store_done)
                    state_next = IDLE;
            end

            CLEAR_RUN: begin
                state_next = IDLE;
            end

            default: state_next = IDLE;
        endcase
    end

    // ── Output Logic ───────────────────────────────────────────
    assign wb_load_trigger  = (state == LOAD_W);
    assign ub_load_trigger  = (state == LOAD_A);
    assign ub_store_trigger = (state == STORE_RUN);
    assign acc_clear        = (state == CLEAR_RUN);
    assign acc_drain_trigger = (state == DRAIN_RUN);

    assign mux_sel = (state == DRAIN_RUN);

    assign done = (state != IDLE) && (state_next == IDLE);

endmodule

`default_nettype wire
