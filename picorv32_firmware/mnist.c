// firmware/mnist/mnist.c

#include <stdint.h>

// ============ Hardware ============
#define UART      ((volatile uint32_t *)0x80000000)
#define TX_BUSY   (1u << 9)
#define RX_VALID  (1u << 8)

// ============ Protocol (match your TPU opcode numbering) ============
#define OP_SET_CONFIG           0x01
#define OP_WRITE_ACTIVATION     0x02
#define OP_WRITE_BIAS           0x03
#define OP_EXEC                 0x04
#define OP_READ_RESULT          0x05
#define OP_RESET                0x06
#define OP_PING                 0x07
#define OP_WRITE_WEIGHT_BULK    0x08

#define ACK_OK     0xAA
#define ACK_ERR    0xEE
#define ACK_PING   0xA5

// ============ Network shape ============
#define INPUT_SIZE     784
#define LAYER1_SIZE    64
#define LAYER2_SIZE    16   // 10 real + 6 padding (matches TPU 8x8 tile shape)
#define OUTPUT_CLASSES 10

// ============ Storage in RAM (.bss) ============
static int8_t  layer1_weights[LAYER1_SIZE * INPUT_SIZE];   // ~50 KB
static int8_t  layer2_weights[LAYER2_SIZE * LAYER1_SIZE];  // 1 KB
static int32_t layer1_bias[LAYER1_SIZE];                   // 256 B
static int32_t layer2_bias[LAYER2_SIZE];                   // 64 B
static int8_t  activations[INPUT_SIZE];                    // 784 B
static int8_t  layer1_out[LAYER1_SIZE];                    // 64 B
static int8_t  layer2_out[LAYER2_SIZE];                    // 16 B

static uint32_t last_cycle_count;   // last inference's cycle count
static uint32_t inference_count;

// ============ UART helpers ============
static void    putc(char c)        { while (*UART & TX_BUSY); *UART = (uint32_t)c; }
static uint8_t getc(void)          { uint32_t v; do { v = *UART; } while (!(v & RX_VALID)); return v & 0xFF; }
static void    send_ack(uint8_t a) { putc(a); }

// ============ Configuration (set by host via OP_SET_CONFIG before EXEC) ============
static uint8_t shift_layer1 = 0;
static uint8_t shift_layer2 = 0;

// ============ Inference state ============
static uint8_t  last_prediction;
static uint32_t last_cycle_count;
static uint32_t inference_count;

// ============ Protocol helpers ============
static void recv_payload(uint8_t *buf, int len) {
    for (int i = 0; i < len; i++) buf[i] = getc();
}

// ============ Cycle counter ============
static inline uint32_t rdcycle(void) {
    uint32_t c;
    asm volatile ("rdcycle %0" : "=r"(c));
    return c;
}

// ============ Inference ============
static void run_inference(void) {
    uint32_t start_cycles = rdcycle();

    // ----- Layer 1: 784 → 64, ReLU activation -----
    for (int i = 0; i < LAYER1_SIZE; i++) {
        int32_t acc = layer1_bias[i];
        const int8_t *w_row = &layer1_weights[i * INPUT_SIZE];

        for (int j = 0; j < INPUT_SIZE; j++) {
            acc += (int32_t)w_row[j] * (int32_t)activations[j];
        }

        // Requantize: signed right shift (matches TPU hardware shifter & Python >>)
        acc = acc >> shift_layer1;

        // ReLU: clamp negatives to 0
        if (acc < 0) acc = 0;

        // Saturate upper bound to int8 max
        if (acc > 127) acc = 127;

        layer1_out[i] = (int8_t)acc;
    }

    // ----- Layer 2: 64 → 16, BYPASS (no activation) -----
    for (int i = 0; i < LAYER2_SIZE; i++) {
        int32_t acc = layer2_bias[i];
        const int8_t *w_row = &layer2_weights[i * LAYER1_SIZE];

        for (int j = 0; j < LAYER1_SIZE; j++) {
            acc += (int32_t)w_row[j] * (int32_t)layer1_out[j];
        }

        // Requantize: signed right shift
        acc = acc >> shift_layer2;

        // Saturate to full int8 range (no ReLU on output layer)
        if (acc >  127) acc =  127;
        if (acc < -128) acc = -128;

        layer2_out[i] = (int8_t)acc;
    }

    // ----- Argmax over the 10 real outputs (last 6 are zero-padding) -----
    int8_t  best_val = layer2_out[0];
    uint8_t best_idx = 0;
    for (int i = 1; i < OUTPUT_CLASSES; i++) {
        if (layer2_out[i] > best_val) {
            best_val = layer2_out[i];
            best_idx = (uint8_t)i;
        }
    }
    last_prediction = best_idx;

    last_cycle_count = rdcycle() - start_cycles;
    inference_count++;
}

// ============ Main dispatch loop ============
int main(void) {
    while (1) {
        uint8_t opcode = getc();
        uint8_t len    = getc();
        uint8_t buf[256];
        recv_payload(buf, len);

        switch (opcode) {
            case OP_PING:
                send_ack(ACK_PING);
                break;

            case OP_SET_CONFIG:
                // Payload: [shift_layer1:1] [shift_layer2:1]
                shift_layer1 = buf[0];
                shift_layer2 = buf[1];
                send_ack(ACK_OK);
                break;

            case OP_WRITE_WEIGHT_BULK: {
                // Payload: [target:1] [offset_lo:1] [offset_hi:1] [weight_bytes...]
                //   target: 0 = layer1_weights, 1 = layer2_weights
                //   offset: byte index into the target array
                uint8_t  target = buf[0];
                uint16_t offset = (uint16_t)buf[1] | ((uint16_t)buf[2] << 8);
                int8_t  *dst    = (target == 0) ? layer1_weights : layer2_weights;
                int      n      = len - 3;
                for (int i = 0; i < n; i++) dst[offset + i] = (int8_t)buf[3 + i];
                send_ack(ACK_OK);
                break;
            }

            case OP_WRITE_ACTIVATION: {
                // Payload: [offset_lo:1] [offset_hi:1] [activation_bytes...]
                uint16_t offset = (uint16_t)buf[0] | ((uint16_t)buf[1] << 8);
                int      n      = len - 2;
                for (int i = 0; i < n; i++) activations[offset + i] = (int8_t)buf[2 + i];
                send_ack(ACK_OK);
                break;
            }

            case OP_WRITE_BIAS: {
                // Payload: [target:1] [offset_lo:1] [offset_hi:1] [bias_bytes:int32 LE...]
                //   target: 0 = layer1_bias, 1 = layer2_bias
                //   offset: byte index into the target array (so offset = element * 4)
                uint8_t  target = buf[0];
                uint16_t offset = (uint16_t)buf[1] | ((uint16_t)buf[2] << 8);
                uint8_t *dst    = (target == 0) ? (uint8_t *)layer1_bias : (uint8_t *)layer2_bias;
                int      nbytes = len - 3;
                for (int i = 0; i < nbytes; i++) dst[offset + i] = buf[3 + i];
                send_ack(ACK_OK);
                break;
            }

            case OP_EXEC:
                run_inference();
                send_ack(ACK_OK);
                break;

            case OP_READ_RESULT:
                // Response: [prediction:1] [cycles:4 LE] [layer2_out: LAYER2_SIZE bytes] [ACK_OK]
                putc(last_prediction);
                putc((last_cycle_count >>  0) & 0xFF);
                putc((last_cycle_count >>  8) & 0xFF);
                putc((last_cycle_count >> 16) & 0xFF);
                putc((last_cycle_count >> 24) & 0xFF);
                for (int i = 0; i < LAYER2_SIZE; i++) putc((uint8_t)layer2_out[i]);
                send_ack(ACK_OK);
                break;

            case OP_RESET:
                // Zero dynamic state; weights/biases survive (matches TPU "BRAM survives soft reset")
                for (int i = 0; i < INPUT_SIZE;  i++) activations[i] = 0;
                for (int i = 0; i < LAYER1_SIZE; i++) layer1_out[i]  = 0;
                for (int i = 0; i < LAYER2_SIZE; i++) layer2_out[i]  = 0;
                last_prediction  = 0;
                last_cycle_count = 0;
                inference_count  = 0;
                send_ack(ACK_OK);
                break;

            default:
                send_ack(ACK_ERR);
                break;
        }
    }
}
