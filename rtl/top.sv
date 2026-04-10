`default_nettype none

module top #(
    parameter ROWS   = 8,
    parameter COLS   = 8,
    parameter DATA_W = 8,
    parameter ACC_W  = 32
)(
    input  logic                            clk,
    input  logic                            rst_n,

    // Host — weight buffer write port
    input  logic [2:0]                      wb_wr_addr,
    input  logic [ROWS-1:0][DATA_W-1:0]     wb_wr_data,
    input  logic                            wb_wr_en,

    // Host — unified buffer write port
    input  logic [2:0]                      ub_wr_addr,
    input  logic [ROWS-1:0][DATA_W-1:0]     ub_wr_data,
    input  logic                            ub_wr_en,

    // Host — unified buffer read port (result bank)
    input  logic [2:0]                      ub_rd_addr,
    input  logic                            ub_rd_en,
    output logic [ROWS-1:0][DATA_W-1:0]     ub_rd_data,

    // Host — bias write port
    input  logic [2:0]                      bias_wr_addr,
    input  logic [ACC_W-1:0]                bias_wr_data,
    input  logic                            bias_wr_en,

    // Host — command interface
    input  logic [1:0]                      cmd,
    input  logic                            start,
    output logic                            done,

    // Host — ReLU configuration
    input  logic [1:0]                      act_sel,      // 00=ReLU, 01=LeakyReLU, 10=Bypass, 11=BinaryStep
    input  logic [4:0]                      shift_amount,
    input  logic [2:0]                      leak_shift,   // Leaky ReLU negative divisor (2^leak_shift)

    // Host — buffer status
    output logic                            wb_ready,
    output logic                            ub_ready
);

    // ── Activation Function Encoding ─────────────────────────
    localparam logic [1:0] ACT_RELU        = 2'b00,
                           ACT_LEAKY_RELU  = 2'b01,
                           ACT_BYPASS      = 2'b10,
                           ACT_BINARY_STEP = 2'b11;
    
    // ── Internal Wires — Weight Buffer to Systolic Array ──────
    logic [ROWS-1:0][DATA_W-1:0]    wb_weight_out;
    logic [COLS-1:0]                wb_weight_load;

    // ── Internal Wires — Unified Buffer to Systolic Array ────
    logic [ROWS-1:0][DATA_W-1:0]    ub_act_out;
    logic [ROWS-1:0]                ub_valid;

    // ── Internal Wires — Systolic Array to Accumulator ───────
    logic [COLS-1:0][ACC_W-1:0]     sa_psum_out;
    logic [COLS-1:0]                sa_valid_out;

    // ── Internal Wires — Accumulator to ReLU ─────────────────
    logic [ROWS-1:0][ACC_W-1:0]     acc_out;
    logic [$clog2(COLS)-1:0]        acc_col_idx;
    logic                           acc_valid;

    // ── Internal Wires — Bias Add to Activation Functions ────
    logic [ROWS-1:0][ACC_W-1:0]     biased_out;

    // ── Internal Wires — Activation Function Outputs ─────────
    logic [ROWS-1:0][DATA_W-1:0]    relu_result;
    logic [ROWS-1:0][DATA_W-1:0]    leaky_result;
    logic [ROWS-1:0][DATA_W-1:0]    bypass_result;
    logic [ROWS-1:0][DATA_W-1:0]    bstep_result;
    logic [ROWS-1:0][DATA_W-1:0]    act_out;          // Selected activation output

    // ── Internal Wires — FSM Handshake ───────────────────────
    logic        fsm_mux_sel;
    logic        fsm_wb_load_trigger;
    logic        fsm_wb_done;
    logic        fsm_ub_load_trigger;
    logic        fsm_ub_load_done;
    logic        fsm_ub_store_trigger;
    logic        fsm_ub_store_done;
    logic        fsm_acc_clear;
    logic        fsm_acc_drain_trigger;
    logic        fsm_acc_pass_done;
    logic        fsm_acc_drain_done;

    // ── Internal Wires — Write Port Mux Output ───────────────
    logic [2:0]                     ub_mux_wr_addr;
    logic [ROWS-1:0][DATA_W-1:0]    ub_mux_wr_data;
    logic                           ub_mux_wr_en;

    // ── Write Port Mux ───────────────────────────────────────
    //   mux_sel = 0: HOST drives unified buffer write port
    //   mux_sel = 1: Accumulator drain drives through ReLU
    always_comb begin
        if (fsm_mux_sel) begin
            ub_mux_wr_addr = acc_col_idx;
            ub_mux_wr_data = act_out;
            ub_mux_wr_en   = acc_valid;
        end else begin
            ub_mux_wr_addr = ub_wr_addr;
            ub_mux_wr_data = ub_wr_data;
            ub_mux_wr_en   = ub_wr_en;
        end
    end

    // ── Weight Buffer ────────────────────────────────────────
    weight_buffer #(
        .ROWS   (ROWS),
        .COLS   (COLS),
        .DATA_W (DATA_W)
    ) u_weight_buffer (
        .clk          (clk),
        .rst_n        (rst_n),
        .wr_addr      (wb_wr_addr),
        .wr_data      (wb_wr_data),
        .wr_en        (wb_wr_en),
        .load_trigger (fsm_wb_load_trigger),
        .ready        (wb_ready),
        .done         (fsm_wb_done),
        .weight_out   (wb_weight_out),
        .weight_load  (wb_weight_load)
    );

    // ── Unified Buffer ───────────────────────────────────────
    unified_buffer #(
        .ROWS   (ROWS),
        .COLS   (COLS),
        .DATA_W (DATA_W)
    ) u_unified_buffer (
        .clk           (clk),
        .rst_n         (rst_n),
        .wr_addr       (ub_mux_wr_addr),
        .wr_data       (ub_mux_wr_data),
        .wr_en         (ub_mux_wr_en),
        .load_trigger  (fsm_ub_load_trigger),
        .ready         (ub_ready),
        .load_done     (fsm_ub_load_done),
        .act_out       (ub_act_out),
        .valid         (ub_valid),
        .store_trigger (fsm_ub_store_trigger),
        .store_done    (fsm_ub_store_done),
        .rd_addr       (ub_rd_addr),
        .rd_en         (ub_rd_en),
        .rd_data       (ub_rd_data)
    );

    // ── Systolic Array ───────────────────────────────────────
    systolic_array #(
        .ROWS   (ROWS),
        .COLS   (COLS),
        .DATA_W (DATA_W),
        .ACC_W  (ACC_W)
    ) u_systolic_array (
        .clk         (clk),
        .rst_n       (rst_n),
        .weight_in   (wb_weight_out),
        .weight_load (wb_weight_load),
        .act_in      (ub_act_out),
        .valid_in    (ub_valid),
        .psum_out    (sa_psum_out),
        .valid_out   (sa_valid_out)
    );

    // ── Accumulator ──────────────────────────────────────────
    accumulator #(
        .ROWS  (ROWS),
        .COLS  (COLS),
        .ACC_W (ACC_W)
    ) u_accumulator (
        .clk           (clk),
        .rst_n         (rst_n),
        .psum_in       (sa_psum_out),
        .valid_in      (sa_valid_out),
        .clear         (fsm_acc_clear),
        .drain_trigger (fsm_acc_drain_trigger),
        .acc_out       (acc_out),
        .col_idx       (acc_col_idx),
        .acc_valid     (acc_valid),
        .pass_done     (fsm_acc_pass_done),
        .drain_done    (fsm_acc_drain_done)
    );
 
    // ── Bias Addition ──────────────────────────────────────────
    bias_add #(
        .ROWS  (ROWS),
        .COLS  (COLS),
        .ACC_W (ACC_W)
    ) u_bias_add (
        .clk      (clk),
        .rst_n    (rst_n),
        .wr_addr  (bias_wr_addr),
        .wr_data  (bias_wr_data),
        .wr_en    (bias_wr_en),
        .data_in  (acc_out),
        .col_idx  (acc_col_idx),
        .data_out (biased_out)
    );
 
    // ── Activation Functions (all combinational) ─────────────────────────────────
    relu #(
        .ROWS   (ROWS),
        .ACC_W  (ACC_W),
        .DATA_W (DATA_W)
    ) u_relu (
        .data_in      (biased_out),
        .shift_amount (shift_amount),
        .data_out     (relu_result)
    );

    leaky_relu #(
        .ROWS   (ROWS),
        .ACC_W  (ACC_W),
        .DATA_W (DATA_W)
    ) u_leaky_relu (
        .data_in      (biased_out),
        .shift_amount (shift_amount),
        .leak_shift   (leak_shift),
        .data_out     (leaky_result)
    );
 
    bypass #(
        .ROWS   (ROWS),
        .ACC_W  (ACC_W),
        .DATA_W (DATA_W)
    ) u_bypass (
        .data_in      (biased_out),
        .shift_amount (shift_amount),
        .data_out     (bypass_result)
    );
 
    binary_step #(
        .ROWS   (ROWS),
        .ACC_W  (ACC_W),
        .DATA_W (DATA_W)
    ) u_binary_step (
        .data_in      (biased_out),
        .data_out     (bstep_result)
    );

    // ── Activation Function Select Mux ───────────────────────
    always_comb begin
        case (act_sel)
            ACT_RELU:        act_out = relu_result;
            ACT_LEAKY_RELU:  act_out = leaky_result;
            ACT_BYPASS:      act_out = bypass_result;
            ACT_BINARY_STEP: act_out = bstep_result;
            default:         act_out = bypass_result;
        endcase
    end

    // ── Control FSM ──────────────────────────────────────────
    control_fsm u_control_fsm (
        .clk               (clk),
        .rst_n             (rst_n),
        .cmd               (cmd),
        .start             (start),
        .done              (done),
        .mux_sel           (fsm_mux_sel),
        .wb_load_trigger   (fsm_wb_load_trigger),
        .wb_done           (fsm_wb_done),
        .ub_load_trigger   (fsm_ub_load_trigger),
        .ub_load_done      (fsm_ub_load_done),
        .ub_store_trigger  (fsm_ub_store_trigger),
        .ub_store_done     (fsm_ub_store_done),
        .acc_clear         (fsm_acc_clear),
        .acc_drain_trigger (fsm_acc_drain_trigger),
        .acc_pass_done     (fsm_acc_pass_done),
        .acc_drain_done    (fsm_acc_drain_done)
    );

endmodule

`default_nettype wire
