/*
 * Requantização int32 -> int8 com ReLU, isolada (RCB-12).
 *
 *     requant_relu [N] [R]
 *
 * Entradas int32 em [-32768, 32767], escala 1/200: parte das saídas vira 0
 * (ReLU), parte satura em 127. Tamanhos de docs/scope.md: S = 4096 (padrão),
 * L = 32768.
 */
#include <stddef.h>
#include <stdint.h>

#include "../common/rcb_bench.h"
#include "../common/rcb_ops.h"
#include "kernel.h"

#define SEED 0xc0de3305u
#define SCALE (1.0 / 200.0)

int main(int argc, char **argv)
{
    struct rcb_param params[] = {
        {"N", 4096, 8, 1 << 22, 8},
        {"R", 1, 1, 1 << 16, 1},
    };
    rcb_parse_params(argc, argv, params, 2);
    long n = params[0].value;
    long repeat = params[1].value;

    int32_t *acc = rcb_alloc((size_t)n * sizeof(*acc), "acc");
    int8_t *y = rcb_alloc((size_t)n, "y");
    int8_t *y_ref = rcb_alloc((size_t)n, "y_ref");

    struct rcb_rng rng = rcb_rng_init(SEED);
    rcb_fill_i32(acc, (size_t)n, &rng, -32768, 32767);
    struct rcb_qparams q = rcb_qparams_from_scale(SCALE);

    rcb_roi_begin();
    for (long r = 0; r < repeat; ++r) {
        requant_relu(n, acc, q, y);
    }
    rcb_roi_end();

    rcb_oracle_requant_relu(n, acc, q, y_ref);
    size_t mismatches = rcb_compare_i8(y, y_ref, (size_t)n, "y");
    return rcb_finish("requant_relu", params, 2, rcb_checksum(y, (size_t)n), mismatches);
}
