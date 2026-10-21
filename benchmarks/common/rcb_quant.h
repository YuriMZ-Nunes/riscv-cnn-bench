/*
 * Quantização int8 simétrica (RCB-11), conforme docs/scope.md:
 *
 *     y = sat8(ReLU((acc * M0 + 2^(30+s)) >> (31+s)))
 *
 * rcb_requantize é o oráculo da requantização. A instrução cnn.rqnt
 * (cnn_insn.h) implementa a mesma fórmula; o benchmark cnn_insn_semantics
 * confere que as duas coincidem.
 */
#ifndef RCB_QUANT_H
#define RCB_QUANT_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

struct rcb_qparams {
    int32_t m0; /* em [2^30, 2^31) */
    unsigned s; /* de 0 a 31 */
};

static inline int32_t rcb_requantize(int32_t acc, struct rcb_qparams q, int relu)
{
    int64_t y = ((int64_t)acc * q.m0 + ((int64_t)1 << (30 + q.s))) >> (31 + q.s);
    int64_t lo = relu ? 0 : -128;
    if (y < lo) {
        y = lo;
    }
    if (y > 127) {
        y = 127;
    }
    return (int32_t)y;
}

/*
 * Converte uma escala real M = S_x * S_w / S_y, com 2^-32 <= M < 1, em
 * M0 * 2^-(31+s). Usa só multiplicações por 2, exatas em ponto flutuante,
 * para não depender da libm. Escala fora da faixa encerra com código 2.
 */
static inline struct rcb_qparams rcb_qparams_from_scale(double scale)
{
    if (!(scale >= 0x1p-32 && scale < 1.0)) {
        fprintf(stderr, "ERRO: escala de requantização fora de [2^-32, 1): %g\n", scale);
        exit(2);
    }
    unsigned s = 0;
    while (scale < 0.5) { /* normaliza para [0,5, 1) */
        scale *= 2.0;
        ++s;
    }
    int64_t m0 = (int64_t)(scale * 2147483648.0 + 0.5); /* round(scale * 2^31) */
    if (m0 == ((int64_t)1 << 31)) {
        m0 >>= 1; /* arredondou para 2^31: 2^30 com um deslocamento a menos */
        if (s == 0) {
            fprintf(stderr, "ERRO: escala de requantização arredonda para 1\n");
            exit(2);
        }
        --s;
    }
    struct rcb_qparams q = {(int32_t)m0, s};
    return q;
}

#endif /* RCB_QUANT_H */
