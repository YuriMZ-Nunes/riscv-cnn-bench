/*
 * Max pooling 2x2 int8 (RCB-12).
 *
 *     maxpool2x2 [H] [W] [C] [R]
 *
 * Stride 2, sem requantização (mesma escala na entrada e na saída),
 * ativações NHWC, H e W pares. Tamanhos de docs/scope.md: S = 32 32 16
 * (padrão), L = 64 64 32.
 */
#include <stddef.h>
#include <stdint.h>

#include "../common/rcb_bench.h"
#include "../common/rcb_ops.h"
#include "kernel.h"

#define SEED 0xc0de3304u

int main(int argc, char **argv)
{
    struct rcb_param params[] = {
        {"H", 32, 2, 512, 2},
        {"W", 32, 2, 512, 2},
        {"C", 16, 8, 512, 8},
        {"R", 1, 1, 1 << 16, 1},
    };
    rcb_parse_params(argc, argv, params, 4);
    long h = params[0].value;
    long w = params[1].value;
    long c = params[2].value;
    long repeat = params[3].value;
    size_t nx = (size_t)(h * w * c);
    size_t ny = (size_t)((h / 2) * (w / 2) * c);

    int8_t *x = rcb_alloc(nx, "x");
    int8_t *y = rcb_alloc(ny, "y");
    int8_t *y_ref = rcb_alloc(ny, "y_ref");

    struct rcb_rng rng = rcb_rng_init(SEED);
    rcb_fill_i8(x, nx, &rng, -128, 127);

    rcb_roi_begin();
    for (long r = 0; r < repeat; ++r) {
        maxpool2x2(h, w, c, x, y);
    }
    rcb_roi_end();

    rcb_oracle_maxpool2x2(h, w, c, x, y_ref);
    size_t mismatches = rcb_compare_i8(y, y_ref, ny, "y");
    return rcb_finish("maxpool2x2", params, 4, rcb_checksum(y, ny), mismatches);
}
