/*
 * Latência das instruções nas CPUs com pipeline (RCB-18).
 *
 *     insn_latency [OP] [N]
 *
 * Dentro da ROI, N iterações de 8 instruções OP em cadeia: cada uma lê o
 * resultado da anterior, então uma só começa quando a outra termina. Nas CPUs
 * minor, o3 e o3-edge, os ciclos da ROI crescem cerca de 8 · N por ciclo de
 * latência de OP; nas atomic e timing, que não modelam as unidades funcionais,
 * não. OP (número, como os demais parâmetros da base comum):
 *
 *     0 mul (IntMult)   1 cnn.dot8   2 cnn.dwmac   3 cnn.rqnt   4 cnn.max8
 *
 * A cadeia é refeita fora da ROI com o modelo em C de cnn_insn.h e os dois
 * resultados são comparados. As instruções são sempre as reais
 * (-DCNN_INSN_HW no Makefile): só executa no gem5 do fork.
 */
#include <stddef.h>
#include <stdint.h>

#include "../common/cnn_insn.h"
#include "../common/rcb_bench.h"

#define SEED 0x1a7e5c1du

enum { OP_MUL, OP_DOT8, OP_DWMAC, OP_RQNT, OP_MAX8 };

/* N iterações de 8 passos; o switch fica fora do laço. */
#define CHAIN(step)                                                                    \
    for (long i = 0; i < n; ++i) {                                                     \
        step; step; step; step; step; step; step; step;                                \
    }

/* Fontes voláteis: o compilador não consegue calcular a cadeia antes. */
static volatile uint64_t source_x, source_w, source_params;

static inline uint64_t mul_hw(uint64_t v, uint64_t m)
{
    __asm__ volatile("mul %0, %0, %1" : "+r"(v) : "r"(m));
    return v;
}

static uint64_t run_hw(long op, long n, uint64_t start, uint64_t x, uint64_t w, uint64_t params)
{
    int64_t acc = (int64_t)start;
    uint64_t v = start;
    uint64_t m = w | 1;
    switch (op) {
    case OP_MUL:
        CHAIN(v = mul_hw(v, m));
        return v;
    case OP_DOT8:
        CHAIN(acc = cnn_dot8(acc, x, w));
        return (uint64_t)acc;
    case OP_DWMAC:
        CHAIN(CNN_DWMAC(v, x, w, 0));
        return v;
    case OP_RQNT:
        CHAIN(acc = cnn_rqnt(acc, params));
        return (uint64_t)acc;
    default:
        CHAIN(v = cnn_max8(v, w));
        return v;
    }
}

static uint64_t run_model(long op, long n, uint64_t start, uint64_t x, uint64_t w,
                          uint64_t params)
{
    int64_t acc = (int64_t)start;
    uint64_t v = start;
    for (long i = 0; i < 8 * n; ++i) {
        switch (op) {
        case OP_MUL:
            v *= w | 1;
            break;
        case OP_DOT8:
            acc = cnn_dot8_model((int32_t)acc, x, w);
            break;
        case OP_DWMAC:
            v = cnn_dwmac_model(v, x, w, 0);
            break;
        case OP_RQNT:
            acc = cnn_rqnt_model((int32_t)acc, params, 0);
            break;
        default:
            v = cnn_max8_model(v, w);
            break;
        }
    }
    return (op == OP_DOT8 || op == OP_RQNT) ? (uint64_t)acc : v;
}

int main(int argc, char **argv)
{
    struct rcb_param params[] = {
        {"OP", OP_DOT8, OP_MUL, OP_MAX8, 1},
        {"N", 2000, 1, 1 << 24, 1},
    };
    rcb_parse_params(argc, argv, params, 2);
    long op = params[0].value;
    long n = params[1].value;

    struct rcb_rng rng = rcb_rng_init(SEED);
    source_x = rcb_rng_next(&rng);
    source_w = rcb_rng_next(&rng);
    /* M0 perto de 2^31 e s = 0: o rqnt devolve quase a própria entrada. */
    source_params = cnn_rqnt_params(0x7f000000, 0);
    uint64_t x = source_x, w = source_w, qp = source_params;
    uint64_t start = x ^ w;

    rcb_roi_begin();
    uint64_t got = run_hw(op, n, start, x, w, qp);
    rcb_roi_end();

    uint64_t want = run_model(op, n, start, x, w, qp);
    size_t mismatches = got != want;
    if (mismatches) {
        fprintf(stderr, "ERRO: cadeia OP=%ld = 0x%016" PRIx64 ", modelo = 0x%016" PRIx64 "\n", op,
                got, want);
    }
    return rcb_finish("insn_latency", params, 2, rcb_checksum(&got, sizeof got), mismatches);
}
