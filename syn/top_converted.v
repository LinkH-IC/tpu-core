`default_nettype none
module accumulator (
	clk,
	rst_n,
	psum_in,
	valid_in,
	clear,
	drain_trigger,
	acc_out,
	col_idx,
	acc_valid,
	pass_done,
	drain_done
);
	reg _sv2v_0;
	parameter ROWS = 8;
	parameter COLS = 8;
	parameter ACC_W = 32;
	input wire clk;
	input wire rst_n;
	input wire [(COLS * ACC_W) - 1:0] psum_in;
	input wire [COLS - 1:0] valid_in;
	input wire clear;
	input wire drain_trigger;
	output reg [(ROWS * ACC_W) - 1:0] acc_out;
	output reg [$clog2(COLS) - 1:0] col_idx;
	output reg acc_valid;
	output wire pass_done;
	output wire drain_done;
	localparam ROW_W = $clog2(ROWS);
	localparam COL_W = $clog2(COLS);
	function automatic signed [ROW_W - 1:0] sv2v_cast_66E4F_signed;
		input reg signed [ROW_W - 1:0] inp;
		sv2v_cast_66E4F_signed = inp;
	endfunction
	localparam ROW_END = sv2v_cast_66E4F_signed(ROWS - 1);
	function automatic signed [COL_W - 1:0] sv2v_cast_D7C09_signed;
		input reg signed [COL_W - 1:0] inp;
		sv2v_cast_D7C09_signed = inp;
	endfunction
	localparam COL_END = sv2v_cast_D7C09_signed(COLS - 1);
	reg state;
	reg state_next;
	reg [COL_W - 1:0] drain_cnt;
	reg [COL_W - 1:0] drain_cnt_next;
	reg signed [ACC_W - 1:0] acc_reg [0:ROWS - 1][0:COLS - 1];
	reg [ROW_W - 1:0] col_cnt [0:COLS - 1];
	reg [COLS - 1:0] col_done;
	always @(posedge clk)
		if (!rst_n) begin
			state <= 1'b0;
			drain_cnt <= 1'sb0;
		end
		else begin
			state <= state_next;
			drain_cnt <= drain_cnt_next;
		end
	always @(*) begin
		if (_sv2v_0)
			;
		state_next = state;
		drain_cnt_next = 1'sb0;
		case (state)
			1'b0:
				if (drain_trigger)
					state_next = 1'b1;
			1'b1:
				if (drain_cnt == COL_END)
					state_next = 1'b0;
				else
					drain_cnt_next = drain_cnt + sv2v_cast_D7C09_signed(1);
			default: state_next = 1'b0;
		endcase
	end
	always @(posedge clk)
		if (!rst_n || clear) begin : sv2v_autoblock_1
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin : sv2v_autoblock_2
					reg signed [31:0] c;
					for (c = 0; c < COLS; c = c + 1)
						acc_reg[r][c] <= 1'sb0;
				end
		end
		else if (state == 1'b0) begin : sv2v_autoblock_3
			reg signed [31:0] c;
			for (c = 0; c < COLS; c = c + 1)
				if (valid_in[c])
					acc_reg[col_cnt[c]][c] <= acc_reg[col_cnt[c]][c] + $signed(psum_in[c * ACC_W+:ACC_W]);
		end
	assign pass_done = &col_done;
	always @(posedge clk)
		if (!rst_n || clear) begin : sv2v_autoblock_4
			reg signed [31:0] c;
			for (c = 0; c < COLS; c = c + 1)
				begin
					col_cnt[c] <= 1'sb0;
					col_done[c] <= 1'b0;
				end
		end
		else if (pass_done) begin : sv2v_autoblock_5
			reg signed [31:0] c;
			for (c = 0; c < COLS; c = c + 1)
				begin
					col_cnt[c] <= 1'sb0;
					col_done[c] <= 1'b0;
				end
		end
		else begin : sv2v_autoblock_6
			reg signed [31:0] c;
			for (c = 0; c < COLS; c = c + 1)
				if (valid_in[c] && (state == 1'b0)) begin
					col_cnt[c] <= col_cnt[c] + sv2v_cast_66E4F_signed(1);
					if (col_cnt[c] == ROW_END)
						col_done[c] <= 1'b1;
				end
		end
	always @(*) begin
		if (_sv2v_0)
			;
		acc_out = 1'sb0;
		acc_valid = 1'b0;
		col_idx = 1'sb0;
		if (state == 1'b1) begin
			begin : sv2v_autoblock_7
				reg signed [31:0] r;
				for (r = 0; r < ROWS; r = r + 1)
					acc_out[r * ACC_W+:ACC_W] = acc_reg[r][drain_cnt];
			end
			col_idx = drain_cnt;
			acc_valid = 1'b1;
		end
	end
	assign drain_done = (state == 1'b1) && (drain_cnt == COL_END);
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module bias_add (
	clk,
	rst_n,
	wr_addr,
	wr_data,
	wr_en,
	data_in,
	col_idx,
	data_out
);
	reg _sv2v_0;
	parameter ROWS = 8;
	parameter COLS = 8;
	parameter ACC_W = 32;
	input wire clk;
	input wire rst_n;
	input wire [$clog2(COLS) - 1:0] wr_addr;
	input wire [ACC_W - 1:0] wr_data;
	input wire wr_en;
	input wire [(ROWS * ACC_W) - 1:0] data_in;
	input wire [$clog2(COLS) - 1:0] col_idx;
	output reg [(ROWS * ACC_W) - 1:0] data_out;
	reg signed [ACC_W - 1:0] bias_reg [0:COLS - 1];
	always @(posedge clk)
		if (!rst_n) begin : sv2v_autoblock_1
			reg signed [31:0] i;
			for (i = 0; i < COLS; i = i + 1)
				bias_reg[i] <= 1'sb0;
		end
		else if (wr_en)
			bias_reg[wr_addr] <= wr_data;
	always @(*) begin
		if (_sv2v_0)
			;
		begin : sv2v_autoblock_2
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				data_out[r * ACC_W+:ACC_W] = data_in[r * ACC_W+:ACC_W] + bias_reg[col_idx];
		end
	end
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module binary_step (
	data_in,
	data_out
);
	reg _sv2v_0;
	parameter ROWS = 8;
	parameter ACC_W = 32;
	parameter DATA_W = 8;
	input wire [(ROWS * ACC_W) - 1:0] data_in;
	output reg [(ROWS * DATA_W) - 1:0] data_out;
	function automatic signed [DATA_W - 1:0] sv2v_cast_4F9DF_signed;
		input reg signed [DATA_W - 1:0] inp;
		sv2v_cast_4F9DF_signed = inp;
	endfunction
	always @(*) begin
		if (_sv2v_0)
			;
		begin : sv2v_autoblock_1
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				if ($signed(data_in[r * ACC_W+:ACC_W]) > 0)
					data_out[r * DATA_W+:DATA_W] = sv2v_cast_4F9DF_signed(1);
				else
					data_out[r * DATA_W+:DATA_W] = 1'sb0;
		end
	end
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module bypass (
	data_in,
	shift_amount,
	data_out
);
	reg _sv2v_0;
	parameter ROWS = 8;
	parameter ACC_W = 32;
	parameter DATA_W = 8;
	input wire [(ROWS * ACC_W) - 1:0] data_in;
	input wire [4:0] shift_amount;
	output reg [(ROWS * DATA_W) - 1:0] data_out;
	function automatic signed [ACC_W - 1:0] sv2v_cast_528BB_signed;
		input reg signed [ACC_W - 1:0] inp;
		sv2v_cast_528BB_signed = inp;
	endfunction
	localparam signed [ACC_W - 1:0] MAX_POS = sv2v_cast_528BB_signed(127);
	localparam signed [ACC_W - 1:0] MIN_NEG = -sv2v_cast_528BB_signed(128);
	reg signed [ACC_W - 1:0] shifted [0:ROWS - 1];
	function automatic signed [DATA_W - 1:0] sv2v_cast_4F9DF_signed;
		input reg signed [DATA_W - 1:0] inp;
		sv2v_cast_4F9DF_signed = inp;
	endfunction
	function automatic [DATA_W - 1:0] sv2v_cast_4F9DF;
		input reg [DATA_W - 1:0] inp;
		sv2v_cast_4F9DF = inp;
	endfunction
	always @(*) begin
		if (_sv2v_0)
			;
		begin : sv2v_autoblock_1
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin
					shifted[r] = $signed(data_in[r * ACC_W+:ACC_W]) >>> shift_amount;
					if (shifted[r] > MAX_POS)
						data_out[r * DATA_W+:DATA_W] = sv2v_cast_4F9DF_signed(MAX_POS);
					else if (shifted[r] < MIN_NEG)
						data_out[r * DATA_W+:DATA_W] = sv2v_cast_4F9DF_signed(MIN_NEG);
					else
						data_out[r * DATA_W+:DATA_W] = sv2v_cast_4F9DF(shifted[r]);
				end
		end
	end
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module control_fsm (
	clk,
	rst_n,
	cmd,
	start,
	done,
	mux_sel,
	wb_load_trigger,
	wb_done,
	ub_load_trigger,
	ub_load_done,
	ub_store_trigger,
	ub_store_done,
	acc_clear,
	acc_drain_trigger,
	acc_pass_done,
	acc_drain_done
);
	reg _sv2v_0;
	input wire clk;
	input wire rst_n;
	input wire [1:0] cmd;
	input wire start;
	output wire done;
	output wire mux_sel;
	output wire wb_load_trigger;
	input wire wb_done;
	output wire ub_load_trigger;
	input wire ub_load_done;
	output wire ub_store_trigger;
	input wire ub_store_done;
	output wire acc_clear;
	output wire acc_drain_trigger;
	input wire acc_pass_done;
	input wire acc_drain_done;
	localparam [1:0] CMD_COMPUTE = 2'b00;
	localparam [1:0] CMD_DRAIN = 2'b01;
	localparam [1:0] CMD_STORE = 2'b10;
	localparam [1:0] CMD_CLEAR = 2'b11;
	reg [2:0] state;
	reg [2:0] state_next;
	always @(posedge clk)
		if (!rst_n)
			state <= 3'b000;
		else
			state <= state_next;
	always @(*) begin
		if (_sv2v_0)
			;
		state_next = state;
		case (state)
			3'b000:
				if (start)
					case (cmd)
						CMD_COMPUTE: state_next = 3'b001;
						CMD_DRAIN: state_next = 3'b101;
						CMD_STORE: state_next = 3'b110;
						CMD_CLEAR: state_next = 3'b111;
						default: state_next = 3'b000;
					endcase
			3'b001: state_next = 3'b010;
			3'b010:
				if (wb_done)
					state_next = 3'b011;
			3'b011: state_next = 3'b100;
			3'b100:
				if (acc_pass_done)
					state_next = 3'b000;
			3'b101:
				if (acc_drain_done)
					state_next = 3'b000;
			3'b110:
				if (ub_store_done)
					state_next = 3'b000;
			3'b111: state_next = 3'b000;
			default: state_next = 3'b000;
		endcase
	end
	assign wb_load_trigger = state == 3'b001;
	assign ub_load_trigger = state == 3'b011;
	assign ub_store_trigger = state == 3'b110;
	assign acc_clear = state == 3'b111;
	assign acc_drain_trigger = state == 3'b101;
	assign mux_sel = state == 3'b101;
	assign done = (state != 3'b000) && (state_next == 3'b000);
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module leaky_relu (
	data_in,
	shift_amount,
	leak_shift,
	data_out
);
	reg _sv2v_0;
	parameter ROWS = 8;
	parameter ACC_W = 32;
	parameter DATA_W = 8;
	input wire [(ROWS * ACC_W) - 1:0] data_in;
	input wire [4:0] shift_amount;
	input wire [2:0] leak_shift;
	output reg [(ROWS * DATA_W) - 1:0] data_out;
	function automatic signed [ACC_W - 1:0] sv2v_cast_528BB_signed;
		input reg signed [ACC_W - 1:0] inp;
		sv2v_cast_528BB_signed = inp;
	endfunction
	localparam signed [ACC_W - 1:0] MAX_POS = sv2v_cast_528BB_signed(127);
	localparam signed [ACC_W - 1:0] MIN_NEG = -sv2v_cast_528BB_signed(128);
	reg signed [ACC_W - 1:0] shifted [0:ROWS - 1];
	reg signed [ACC_W - 1:0] leaked [0:ROWS - 1];
	function automatic signed [DATA_W - 1:0] sv2v_cast_4F9DF_signed;
		input reg signed [DATA_W - 1:0] inp;
		sv2v_cast_4F9DF_signed = inp;
	endfunction
	function automatic [DATA_W - 1:0] sv2v_cast_4F9DF;
		input reg [DATA_W - 1:0] inp;
		sv2v_cast_4F9DF = inp;
	endfunction
	always @(*) begin
		if (_sv2v_0)
			;
		begin : sv2v_autoblock_1
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin
					shifted[r] = $signed(data_in[r * ACC_W+:ACC_W]) >>> shift_amount;
					if (shifted[r] < 0)
						leaked[r] = shifted[r] >>> leak_shift;
					else
						leaked[r] = shifted[r];
					if (leaked[r] > MAX_POS)
						data_out[r * DATA_W+:DATA_W] = sv2v_cast_4F9DF_signed(MAX_POS);
					else if (leaked[r] < MIN_NEG)
						data_out[r * DATA_W+:DATA_W] = sv2v_cast_4F9DF_signed(MIN_NEG);
					else
						data_out[r * DATA_W+:DATA_W] = sv2v_cast_4F9DF(leaked[r]);
				end
		end
	end
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
module pe (
	clk,
	rst_n,
	weight_in,
	weight_load,
	act_in,
	act_out,
	psum_in,
	psum_out,
	valid_in,
	valid_out
);
	parameter signed [31:0] DATA_W = 8;
	parameter signed [31:0] ACC_W = 32;
	input wire clk;
	input wire rst_n;
	input wire signed [DATA_W - 1:0] weight_in;
	input wire weight_load;
	input wire signed [DATA_W - 1:0] act_in;
	output reg signed [DATA_W - 1:0] act_out;
	input wire signed [ACC_W - 1:0] psum_in;
	output reg signed [ACC_W - 1:0] psum_out;
	input wire valid_in;
	output reg valid_out;
	reg signed [DATA_W - 1:0] weight_reg;
	wire signed [(2 * DATA_W) - 1:0] product;
	wire signed [ACC_W - 1:0] psum_next;
	always @(posedge clk)
		if (!rst_n)
			weight_reg <= 1'sb0;
		else if (weight_load)
			weight_reg <= weight_in;
	assign product = weight_reg * act_in;
	function automatic signed [ACC_W - 1:0] sv2v_cast_528BB_signed;
		input reg signed [ACC_W - 1:0] inp;
		sv2v_cast_528BB_signed = inp;
	endfunction
	assign psum_next = psum_in + sv2v_cast_528BB_signed(product);
	always @(posedge clk)
		if (!rst_n)
			psum_out <= 1'sb0;
		else if (valid_in)
			psum_out <= psum_next;
	always @(posedge clk)
		if (!rst_n)
			act_out <= 1'sb0;
		else
			act_out <= act_in;
	always @(posedge clk)
		if (!rst_n)
			valid_out <= 1'b0;
		else
			valid_out <= valid_in;
endmodule
`default_nettype none
module relu (
	data_in,
	shift_amount,
	data_out
);
	reg _sv2v_0;
	parameter ROWS = 8;
	parameter ACC_W = 32;
	parameter DATA_W = 8;
	input wire [(ROWS * ACC_W) - 1:0] data_in;
	input wire [4:0] shift_amount;
	output reg [(ROWS * DATA_W) - 1:0] data_out;
	function automatic signed [ACC_W - 1:0] sv2v_cast_528BB_signed;
		input reg signed [ACC_W - 1:0] inp;
		sv2v_cast_528BB_signed = inp;
	endfunction
	localparam signed [ACC_W - 1:0] MAX_POS = sv2v_cast_528BB_signed((1 << (DATA_W - 1)) - 1);
	reg signed [ACC_W - 1:0] clipped [0:ROWS - 1];
	reg signed [ACC_W - 1:0] shifted [0:ROWS - 1];
	function automatic signed [DATA_W - 1:0] sv2v_cast_4F9DF_signed;
		input reg signed [DATA_W - 1:0] inp;
		sv2v_cast_4F9DF_signed = inp;
	endfunction
	function automatic [DATA_W - 1:0] sv2v_cast_4F9DF;
		input reg [DATA_W - 1:0] inp;
		sv2v_cast_4F9DF = inp;
	endfunction
	always @(*) begin
		if (_sv2v_0)
			;
		begin : sv2v_autoblock_1
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin
					if ($signed(data_in[r * ACC_W+:ACC_W]) < 0)
						clipped[r] = 1'sb0;
					else
						clipped[r] = $signed(data_in[r * ACC_W+:ACC_W]);
					shifted[r] = clipped[r] >>> shift_amount;
					if (shifted[r] > MAX_POS)
						data_out[r * DATA_W+:DATA_W] = sv2v_cast_4F9DF_signed(MAX_POS);
					else
						data_out[r * DATA_W+:DATA_W] = sv2v_cast_4F9DF(shifted[r]);
				end
		end
	end
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module systolic_array (
	clk,
	rst_n,
	weight_in,
	weight_load,
	act_in,
	valid_in,
	psum_out,
	valid_out
);
	parameter signed [31:0] ROWS = 8;
	parameter signed [31:0] COLS = 8;
	parameter signed [31:0] DATA_W = 8;
	parameter signed [31:0] ACC_W = 32;
	input wire clk;
	input wire rst_n;
	input wire [(ROWS * DATA_W) - 1:0] weight_in;
	input wire [COLS - 1:0] weight_load;
	input wire [(ROWS * DATA_W) - 1:0] act_in;
	input wire [ROWS - 1:0] valid_in;
	output wire [(COLS * ACC_W) - 1:0] psum_out;
	output wire [COLS - 1:0] valid_out;
	wire [DATA_W - 1:0] act_h [0:ROWS - 1][0:COLS + 0];
	wire valid_h [0:ROWS - 1][0:COLS + 0];
	wire [ACC_W - 1:0] psum_v [0:ROWS + 0][0:COLS - 1];
	genvar _gv_c_1;
	generate
		for (_gv_c_1 = 0; _gv_c_1 < COLS; _gv_c_1 = _gv_c_1 + 1) begin : g_psum_top
			localparam c = _gv_c_1;
			assign psum_v[0][c] = 1'sb0;
		end
	endgenerate
	reg [DATA_W - 1:0] stagger_act [0:ROWS - 1][0:ROWS - 1];
	reg stagger_vld [0:ROWS - 1][0:ROWS - 1];
	genvar _gv_i_1;
	generate
		for (_gv_i_1 = 0; _gv_i_1 < ROWS; _gv_i_1 = _gv_i_1 + 1) begin : g_stagger
			localparam i = _gv_i_1;
			if (i == 0) begin : g_row0
				assign act_h[0][0] = act_in[0+:DATA_W];
				assign valid_h[0][0] = valid_in[0];
			end
			else begin : g_rowN
				always @(posedge clk)
					if (!rst_n) begin
						stagger_act[i][0] <= 1'sb0;
						stagger_vld[i][0] <= 1'b0;
					end
					else begin
						stagger_act[i][0] <= act_in[i * DATA_W+:DATA_W];
						stagger_vld[i][0] <= valid_in[i];
					end
				genvar _gv_s_1;
				for (_gv_s_1 = 1; _gv_s_1 < i; _gv_s_1 = _gv_s_1 + 1) begin : g_stage
					localparam s = _gv_s_1;
					always @(posedge clk)
						if (!rst_n) begin
							stagger_act[i][s] <= 1'sb0;
							stagger_vld[i][s] <= 1'b0;
						end
						else begin
							stagger_act[i][s] <= stagger_act[i][s - 1];
							stagger_vld[i][s] <= stagger_vld[i][s - 1];
						end
				end
				assign act_h[i][0] = stagger_act[i][i - 1];
				assign valid_h[i][0] = stagger_vld[i][i - 1];
			end
		end
	endgenerate
	genvar _gv_r_1;
	generate
		for (_gv_r_1 = 0; _gv_r_1 < ROWS; _gv_r_1 = _gv_r_1 + 1) begin : g_row
			localparam r = _gv_r_1;
			genvar _gv_c_2;
			for (_gv_c_2 = 0; _gv_c_2 < COLS; _gv_c_2 = _gv_c_2 + 1) begin : g_col
				localparam c = _gv_c_2;
				pe #(
					.DATA_W(DATA_W),
					.ACC_W(ACC_W)
				) u_pe(
					.clk(clk),
					.rst_n(rst_n),
					.weight_in(weight_in[r * DATA_W+:DATA_W]),
					.weight_load(weight_load[c]),
					.act_in(act_h[r][c]),
					.act_out(act_h[r][c + 1]),
					.valid_in(valid_h[r][c]),
					.valid_out(valid_h[r][c + 1]),
					.psum_in(psum_v[r][c]),
					.psum_out(psum_v[r + 1][c])
				);
			end
		end
	endgenerate
	genvar _gv_c_3;
	generate
		for (_gv_c_3 = 0; _gv_c_3 < COLS; _gv_c_3 = _gv_c_3 + 1) begin : g_out
			localparam c = _gv_c_3;
			assign psum_out[c * ACC_W+:ACC_W] = psum_v[ROWS][c];
			assign valid_out[c] = valid_h[ROWS - 1][c + 1];
		end
	endgenerate
endmodule
`default_nettype wire
`default_nettype none
module top (
	clk,
	rst_n,
	wb_wr_addr,
	wb_wr_data,
	wb_wr_en,
	ub_wr_addr,
	ub_wr_data,
	ub_wr_en,
	ub_rd_addr,
	ub_rd_en,
	ub_rd_data,
	bias_wr_addr,
	bias_wr_data,
	bias_wr_en,
	cmd,
	start,
	done,
	act_sel,
	shift_amount,
	leak_shift,
	wb_ready,
	ub_ready
);
	reg _sv2v_0;
	parameter ROWS = 8;
	parameter COLS = 8;
	parameter DATA_W = 8;
	parameter ACC_W = 32;
	input wire clk;
	input wire rst_n;
	input wire [2:0] wb_wr_addr;
	input wire [(ROWS * DATA_W) - 1:0] wb_wr_data;
	input wire wb_wr_en;
	input wire [2:0] ub_wr_addr;
	input wire [(ROWS * DATA_W) - 1:0] ub_wr_data;
	input wire ub_wr_en;
	input wire [2:0] ub_rd_addr;
	input wire ub_rd_en;
	output wire [(ROWS * DATA_W) - 1:0] ub_rd_data;
	input wire [2:0] bias_wr_addr;
	input wire [ACC_W - 1:0] bias_wr_data;
	input wire bias_wr_en;
	input wire [1:0] cmd;
	input wire start;
	output wire done;
	input wire [1:0] act_sel;
	input wire [4:0] shift_amount;
	input wire [2:0] leak_shift;
	output wire wb_ready;
	output wire ub_ready;
	localparam [1:0] ACT_RELU = 2'b00;
	localparam [1:0] ACT_LEAKY_RELU = 2'b01;
	localparam [1:0] ACT_BYPASS = 2'b10;
	localparam [1:0] ACT_BINARY_STEP = 2'b11;
	wire [(ROWS * DATA_W) - 1:0] wb_weight_out;
	wire [COLS - 1:0] wb_weight_load;
	wire [(ROWS * DATA_W) - 1:0] ub_act_out;
	wire [ROWS - 1:0] ub_valid;
	wire [(COLS * ACC_W) - 1:0] sa_psum_out;
	wire [COLS - 1:0] sa_valid_out;
	wire [(ROWS * ACC_W) - 1:0] acc_out;
	wire [$clog2(COLS) - 1:0] acc_col_idx;
	wire acc_valid;
	wire [(ROWS * ACC_W) - 1:0] biased_out;
	wire [(ROWS * DATA_W) - 1:0] relu_result;
	wire [(ROWS * DATA_W) - 1:0] leaky_result;
	wire [(ROWS * DATA_W) - 1:0] bypass_result;
	wire [(ROWS * DATA_W) - 1:0] bstep_result;
	reg [(ROWS * DATA_W) - 1:0] act_out;
	wire fsm_mux_sel;
	wire fsm_wb_load_trigger;
	wire fsm_wb_done;
	wire fsm_ub_load_trigger;
	wire fsm_ub_load_done;
	wire fsm_ub_store_trigger;
	wire fsm_ub_store_done;
	wire fsm_acc_clear;
	wire fsm_acc_drain_trigger;
	wire fsm_acc_pass_done;
	wire fsm_acc_drain_done;
	reg [2:0] ub_mux_wr_addr;
	reg [(ROWS * DATA_W) - 1:0] ub_mux_wr_data;
	reg ub_mux_wr_en;
	always @(*) begin
		if (_sv2v_0)
			;
		if (fsm_mux_sel) begin
			ub_mux_wr_addr = acc_col_idx;
			ub_mux_wr_data = act_out;
			ub_mux_wr_en = acc_valid;
		end
		else begin
			ub_mux_wr_addr = ub_wr_addr;
			ub_mux_wr_data = ub_wr_data;
			ub_mux_wr_en = ub_wr_en;
		end
	end
	weight_buffer #(
		.ROWS(ROWS),
		.COLS(COLS),
		.DATA_W(DATA_W)
	) u_weight_buffer(
		.clk(clk),
		.rst_n(rst_n),
		.wr_addr(wb_wr_addr),
		.wr_data(wb_wr_data),
		.wr_en(wb_wr_en),
		.load_trigger(fsm_wb_load_trigger),
		.ready(wb_ready),
		.done(fsm_wb_done),
		.weight_out(wb_weight_out),
		.weight_load(wb_weight_load)
	);
	unified_buffer #(
		.ROWS(ROWS),
		.COLS(COLS),
		.DATA_W(DATA_W)
	) u_unified_buffer(
		.clk(clk),
		.rst_n(rst_n),
		.wr_addr(ub_mux_wr_addr),
		.wr_data(ub_mux_wr_data),
		.wr_en(ub_mux_wr_en),
		.load_trigger(fsm_ub_load_trigger),
		.ready(ub_ready),
		.load_done(fsm_ub_load_done),
		.act_out(ub_act_out),
		.valid(ub_valid),
		.store_trigger(fsm_ub_store_trigger),
		.store_done(fsm_ub_store_done),
		.rd_addr(ub_rd_addr),
		.rd_en(ub_rd_en),
		.rd_data(ub_rd_data)
	);
	systolic_array #(
		.ROWS(ROWS),
		.COLS(COLS),
		.DATA_W(DATA_W),
		.ACC_W(ACC_W)
	) u_systolic_array(
		.clk(clk),
		.rst_n(rst_n),
		.weight_in(wb_weight_out),
		.weight_load(wb_weight_load),
		.act_in(ub_act_out),
		.valid_in(ub_valid),
		.psum_out(sa_psum_out),
		.valid_out(sa_valid_out)
	);
	accumulator #(
		.ROWS(ROWS),
		.COLS(COLS),
		.ACC_W(ACC_W)
	) u_accumulator(
		.clk(clk),
		.rst_n(rst_n),
		.psum_in(sa_psum_out),
		.valid_in(sa_valid_out),
		.clear(fsm_acc_clear),
		.drain_trigger(fsm_acc_drain_trigger),
		.acc_out(acc_out),
		.col_idx(acc_col_idx),
		.acc_valid(acc_valid),
		.pass_done(fsm_acc_pass_done),
		.drain_done(fsm_acc_drain_done)
	);
	bias_add #(
		.ROWS(ROWS),
		.COLS(COLS),
		.ACC_W(ACC_W)
	) u_bias_add(
		.clk(clk),
		.rst_n(rst_n),
		.wr_addr(bias_wr_addr),
		.wr_data(bias_wr_data),
		.wr_en(bias_wr_en),
		.data_in(acc_out),
		.col_idx(acc_col_idx),
		.data_out(biased_out)
	);
	relu #(
		.ROWS(ROWS),
		.ACC_W(ACC_W),
		.DATA_W(DATA_W)
	) u_relu(
		.data_in(biased_out),
		.shift_amount(shift_amount),
		.data_out(relu_result)
	);
	leaky_relu #(
		.ROWS(ROWS),
		.ACC_W(ACC_W),
		.DATA_W(DATA_W)
	) u_leaky_relu(
		.data_in(biased_out),
		.shift_amount(shift_amount),
		.leak_shift(leak_shift),
		.data_out(leaky_result)
	);
	bypass #(
		.ROWS(ROWS),
		.ACC_W(ACC_W),
		.DATA_W(DATA_W)
	) u_bypass(
		.data_in(biased_out),
		.shift_amount(shift_amount),
		.data_out(bypass_result)
	);
	binary_step #(
		.ROWS(ROWS),
		.ACC_W(ACC_W),
		.DATA_W(DATA_W)
	) u_binary_step(
		.data_in(biased_out),
		.data_out(bstep_result)
	);
	always @(*) begin
		if (_sv2v_0)
			;
		case (act_sel)
			ACT_RELU: act_out = relu_result;
			ACT_LEAKY_RELU: act_out = leaky_result;
			ACT_BYPASS: act_out = bypass_result;
			ACT_BINARY_STEP: act_out = bstep_result;
			default: act_out = bypass_result;
		endcase
	end
	control_fsm u_control_fsm(
		.clk(clk),
		.rst_n(rst_n),
		.cmd(cmd),
		.start(start),
		.done(done),
		.mux_sel(fsm_mux_sel),
		.wb_load_trigger(fsm_wb_load_trigger),
		.wb_done(fsm_wb_done),
		.ub_load_trigger(fsm_ub_load_trigger),
		.ub_load_done(fsm_ub_load_done),
		.ub_store_trigger(fsm_ub_store_trigger),
		.ub_store_done(fsm_ub_store_done),
		.acc_clear(fsm_acc_clear),
		.acc_drain_trigger(fsm_acc_drain_trigger),
		.acc_pass_done(fsm_acc_pass_done),
		.acc_drain_done(fsm_acc_drain_done)
	);
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module unified_buffer (
	clk,
	rst_n,
	wr_addr,
	wr_data,
	wr_en,
	load_trigger,
	ready,
	load_done,
	act_out,
	valid,
	store_trigger,
	store_done,
	rd_addr,
	rd_en,
	rd_data
);
	reg _sv2v_0;
	parameter ROWS = 8;
	parameter COLS = 8;
	parameter DATA_W = 8;
	input wire clk;
	input wire rst_n;
	input wire [2:0] wr_addr;
	input wire [(ROWS * DATA_W) - 1:0] wr_data;
	input wire wr_en;
	input wire load_trigger;
	output wire ready;
	output wire load_done;
	output reg [(ROWS * DATA_W) - 1:0] act_out;
	output reg [ROWS - 1:0] valid;
	input wire store_trigger;
	output wire store_done;
	input wire [2:0] rd_addr;
	input wire rd_en;
	output reg [(ROWS * DATA_W) - 1:0] rd_data;
	localparam CNT_W = $clog2(COLS);
	function automatic signed [CNT_W - 1:0] sv2v_cast_66408_signed;
		input reg signed [CNT_W - 1:0] inp;
		sv2v_cast_66408_signed = inp;
	endfunction
	localparam CNT_END = sv2v_cast_66408_signed(COLS - 1);
	reg [1:0] state;
	reg [1:0] state_next;
	reg [CNT_W - 1:0] seq_cnt;
	reg [CNT_W - 1:0] seq_cnt_next;
	reg [DATA_W - 1:0] write [0:ROWS - 1][0:COLS - 1];
	reg [DATA_W - 1:0] active [0:ROWS - 1][0:COLS - 1];
	reg [DATA_W - 1:0] result [0:ROWS - 1][0:COLS - 1];
	always @(posedge clk)
		if (!rst_n) begin
			state <= 2'b00;
			seq_cnt <= 1'sb0;
		end
		else begin
			state <= state_next;
			seq_cnt <= seq_cnt_next;
		end
	always @(*) begin
		if (_sv2v_0)
			;
		state_next = state;
		seq_cnt_next = 1'sb0;
		case (state)
			2'b00:
				if (load_trigger)
					state_next = 2'b01;
				else if (store_trigger)
					state_next = 2'b11;
			2'b01: state_next = 2'b10;
			2'b10:
				if (seq_cnt == CNT_END)
					state_next = 2'b00;
				else
					seq_cnt_next = seq_cnt + sv2v_cast_66408_signed(1);
			2'b11: state_next = 2'b00;
			default: state_next = 2'b00;
		endcase
	end
	always @(posedge clk)
		if (!rst_n) begin : sv2v_autoblock_1
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin : sv2v_autoblock_2
					reg signed [31:0] c;
					for (c = 0; c < COLS; c = c + 1)
						write[r][c] <= 1'sb0;
				end
		end
		else if (wr_en && ready) begin : sv2v_autoblock_3
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				write[r][wr_addr] <= wr_data[r * DATA_W+:DATA_W];
		end
	always @(posedge clk)
		if (!rst_n) begin : sv2v_autoblock_4
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin : sv2v_autoblock_5
					reg signed [31:0] c;
					for (c = 0; c < COLS; c = c + 1)
						active[r][c] <= 1'sb0;
				end
		end
		else if (state == 2'b01) begin : sv2v_autoblock_6
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin : sv2v_autoblock_7
					reg signed [31:0] c;
					for (c = 0; c < COLS; c = c + 1)
						active[r][c] <= write[c][r];
				end
		end
	always @(posedge clk)
		if (!rst_n) begin : sv2v_autoblock_8
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin : sv2v_autoblock_9
					reg signed [31:0] c;
					for (c = 0; c < COLS; c = c + 1)
						result[r][c] <= 1'sb0;
				end
		end
		else if (state == 2'b11) begin : sv2v_autoblock_10
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin : sv2v_autoblock_11
					reg signed [31:0] c;
					for (c = 0; c < COLS; c = c + 1)
						result[r][c] <= write[r][c];
				end
		end
	always @(*) begin
		if (_sv2v_0)
			;
		act_out = 1'sb0;
		valid = 1'sb0;
		if (state == 2'b10) begin
			begin : sv2v_autoblock_12
				reg signed [31:0] r;
				for (r = 0; r < ROWS; r = r + 1)
					act_out[r * DATA_W+:DATA_W] = active[r][seq_cnt];
			end
			valid = 1'sb1;
		end
	end
	always @(posedge clk)
		if (!rst_n)
			rd_data <= 1'sb0;
		else if (rd_en) begin : sv2v_autoblock_13
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				rd_data[r * DATA_W+:DATA_W] <= result[r][rd_addr];
		end
		else
			rd_data <= 1'sb0;
	assign ready = (state == 2'b00) || (state == 2'b10);
	assign load_done = (state == 2'b10) && (seq_cnt == CNT_END);
	assign store_done = state == 2'b11;
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
`default_nettype none
module weight_buffer (
	clk,
	rst_n,
	wr_addr,
	wr_data,
	wr_en,
	load_trigger,
	ready,
	done,
	weight_out,
	weight_load
);
	reg _sv2v_0;
	parameter ROWS = 8;
	parameter COLS = 8;
	parameter DATA_W = 8;
	input wire clk;
	input wire rst_n;
	input wire [2:0] wr_addr;
	input wire [(ROWS * DATA_W) - 1:0] wr_data;
	input wire wr_en;
	input wire load_trigger;
	output wire ready;
	output wire done;
	output reg [(ROWS * DATA_W) - 1:0] weight_out;
	output reg [COLS - 1:0] weight_load;
	localparam CNT_W = $clog2(COLS);
	function automatic signed [CNT_W - 1:0] sv2v_cast_66408_signed;
		input reg signed [CNT_W - 1:0] inp;
		sv2v_cast_66408_signed = inp;
	endfunction
	localparam CNT_END = sv2v_cast_66408_signed(COLS - 1);
	reg [1:0] state;
	reg [1:0] state_next;
	reg [CNT_W - 1:0] seq_cnt;
	reg [CNT_W - 1:0] seq_cnt_next;
	reg [DATA_W - 1:0] shadow [0:ROWS - 1][0:COLS - 1];
	reg [DATA_W - 1:0] active [0:ROWS - 1][0:COLS - 1];
	always @(posedge clk)
		if (!rst_n) begin
			state <= 2'b00;
			seq_cnt <= 1'sb0;
		end
		else begin
			state <= state_next;
			seq_cnt <= seq_cnt_next;
		end
	always @(*) begin
		if (_sv2v_0)
			;
		state_next = state;
		seq_cnt_next = 1'sb0;
		case (state)
			2'b00:
				if (load_trigger)
					state_next = 2'b01;
			2'b01: state_next = 2'b10;
			2'b10:
				if (seq_cnt == CNT_END)
					state_next = 2'b00;
				else
					seq_cnt_next = seq_cnt + sv2v_cast_66408_signed(1);
			default: state_next = 2'b00;
		endcase
	end
	always @(posedge clk)
		if (!rst_n) begin : sv2v_autoblock_1
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin : sv2v_autoblock_2
					reg signed [31:0] c;
					for (c = 0; c < COLS; c = c + 1)
						shadow[r][c] <= 1'sb0;
				end
		end
		else if (wr_en && ready) begin : sv2v_autoblock_3
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				shadow[r][wr_addr] <= wr_data[r * DATA_W+:DATA_W];
		end
	always @(posedge clk)
		if (!rst_n) begin : sv2v_autoblock_4
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin : sv2v_autoblock_5
					reg signed [31:0] c;
					for (c = 0; c < COLS; c = c + 1)
						active[r][c] <= 1'sb0;
				end
		end
		else if (state == 2'b01) begin : sv2v_autoblock_6
			reg signed [31:0] r;
			for (r = 0; r < ROWS; r = r + 1)
				begin : sv2v_autoblock_7
					reg signed [31:0] c;
					for (c = 0; c < COLS; c = c + 1)
						active[r][c] <= shadow[r][c];
				end
		end
	always @(*) begin
		if (_sv2v_0)
			;
		weight_out = 1'sb0;
		weight_load = 1'sb0;
		if (state == 2'b10) begin
			begin : sv2v_autoblock_8
				reg signed [31:0] r;
				for (r = 0; r < ROWS; r = r + 1)
					weight_out[r * DATA_W+:DATA_W] = active[r][seq_cnt];
			end
			weight_load[seq_cnt] = 1'b1;
		end
	end
	assign ready = state != 2'b01;
	assign done = (state == 2'b10) && (seq_cnt == CNT_END);
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
