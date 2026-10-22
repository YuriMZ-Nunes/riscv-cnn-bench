/*
 * Exemplo da base comum dos kernels int8 (RCB-11).
 *
 *     int8_base_example [K] [M] [R]
 *
 * Calcula M saídas y[m] = sat8(ReLU(requant(bias[m] + Σ_k x[k] * w[m][k]))),
 * com K múltiplo de 8, e repete o cálculo R vezes dentro da região de
 * interesse. Mostra o roteiro que os kernels das operações (RCB-12) seguem:
 *
 *   1. parâmetros por argumento;
 *   2. dados determinísticos, gerados fora da ROI;
 *   3. kernel dentro da ROI (rcb_roi_begin/rcb_roi_end);
 *   4. oráculo e comparação fora da ROI;
 *   5. linha RESULT com checksum e código de saída 0/1 (2 para argumento
 *      inválido).
 *
 * Não é uma das operações do escopo. Com -DRCB_INJECT_ERROR, o kernel erra
 * uma saída de propósito, para testar a verificação.
 */
#include <stddef.h>
#include <stdint.h>

#include "../common/rcb_bench.h"

#define SEED 0x5eed0001u

/* Kernel medido: o que entra no primeiro bloco do stats.txt. */
static void kernel(const int8_t *x, const int8_t *w, const int32_t *bias, int8_t *y, long k_len,
                   long m_len, struct rcb_qparams q)
{
    for (long m = 0; m < m_len; ++m) {
        const int8_t *row = &w[m * k_len];
        int32_t acc = bias[m];
        for (long k = 0; k < k_len; ++k) {
            acc += (int32_t)x[k] * row[k];
        }
        y[m] = (int8_t)rcb_requantize(acc, q, 1);
    }
#ifdef RCB_INJECT_ERROR
    y[m_len / 2] ^= 1;
#endif
}

/* Oráculo: a versão mais simples possível, com acumulação em int64. */
static void oracle(const int8_t *x, const int8_t *w, const int32_t *bias, int8_t *y, long k_len,
                   long m_len, struct rcb_qparams q)
{
    for (long m = 0; m < m_len; ++m) {
        int64_t acc = bias[m];
        for (long k = 0; k < k_len; ++k) {
            acc += (int64_t)x[k] * (int64_t)w[m * k_len + k];
        }
        y[m] = (int8_t)rcb_requantize((int32_t)acc, q, 1);
    }
}

int main(int argc, char **argv)
{
    struct rcb_param params[] = {
        {"K", 64, 8, 1 << 16, 8},
        {"M", 16, 1, 1 << 12, 1},
        {"R", 1, 1, 1 << 16, 1},
    };
    rcb_parse_params(argc, argv, params, 3);
    long k_len = params[0].value;
    long m_len = params[1].value;
    long repeat = params[2].value;

    int8_t *x = rcb_alloc((size_t)k_len, "x");
    int8_t *w = rcb_alloc((size_t)(m_len * k_len), "w");
    int32_t *bias = rcb_alloc((size_t)m_len * sizeof(*bias), "bias");
    int8_t *y = rcb_alloc((size_t)m_len, "y");
    int8_t *y_ref = rcb_alloc((size_t)m_len, "y_ref");

    struct rcb_rng rng = rcb_rng_init(SEED);
    rcb_fill_i8(x, (size_t)k_len, &rng, -128, 127);
    rcb_fill_i8(w, (size_t)(m_len * k_len), &rng, -128, 127);
    rcb_fill_i32(bias, (size_t)m_len, &rng, -4096, 4096);
    rcb_dataset_i8(x, (size_t)k_len, RCB_INPUT);
    rcb_dataset_i8(w, (size_t)(m_len * k_len), RCB_WEIGHT);
    rcb_dataset_i32(bias, (size_t)m_len, -4096, 4096);
    /* Escala que espalha as saídas na faixa int8 para entradas uniformes. */
    struct rcb_qparams q = rcb_qparams_from_scale(1.0 / (16.0 * (double)k_len));

    rcb_roi_begin();
    for (long r = 0; r < repeat; ++r) {
        kernel(x, w, bias, y, k_len, m_len, q);
    }
    rcb_roi_end();

    oracle(x, w, bias, y_ref, k_len, m_len, q);
    size_t mismatches = rcb_compare_i8(y, y_ref, (size_t)m_len, "y");
    return rcb_finish("int8_base_example", params, 3, rcb_checksum(y, (size_t)m_len), mismatches);
}
