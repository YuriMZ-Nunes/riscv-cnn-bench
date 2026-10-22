/*
 * Convolução pointwise 1x1 int8 (RCB-12).
 *
 *     pointwise1x1 [H] [W] [Cin] [Cout] [R]
 *
 * Ativações NHWC, pesos [Cout][Cin], bias int32, requantização com ReLU.
 * Tamanhos de docs/scope.md: S = 16 16 32 32 (padrão), L = 32 32 64 64.
 */
#include <stddef.h>
#include <stdint.h>

#include "../common/rcb_bench.h"
#include "../common/rcb_ops.h"
#include "kernel.h"

#define SEED 0xc0de3303u
#define SCALE (1.0 / 750.0)

int main(int argc, char **argv)
{
    struct rcb_param params[] = {
        {"H", 16, 1, 256, 1},
        {"W", 16, 1, 256, 1},
        {"Cin", 32, 8, 512, 8},
        {"Cout", 32, 8, 512, 8},
        {"R", 1, 1, 1 << 16, 1},
    };
    rcb_parse_params(argc, argv, params, 5);
    long pixels = params[0].value * params[1].value;
    long cin = params[2].value;
    long cout = params[3].value;
    long repeat = params[4].value;
    size_t nx = (size_t)(pixels * cin);
    size_t nw = (size_t)(cout * cin);
    size_t ny = (size_t)(pixels * cout);

    int8_t *x = rcb_alloc(nx, "x");
    int8_t *w = rcb_alloc(nw, "w");
    int32_t *bias = rcb_alloc((size_t)cout * sizeof(*bias), "bias");
    int8_t *y = rcb_alloc(ny, "y");
    int8_t *y_ref = rcb_alloc(ny, "y_ref");

    struct rcb_rng rng = rcb_rng_init(SEED);
    rcb_fill_i8(x, nx, &rng, -128, 127);
    rcb_fill_i8(w, nw, &rng, -128, 127);
    rcb_fill_i32(bias, (size_t)cout, &rng, -8192, 8192);
    rcb_dataset_i8(x, nx, RCB_INPUT);
    rcb_dataset_i8(w, nw, RCB_WEIGHT);
    rcb_dataset_i32(bias, (size_t)cout, -8192, 8192);
    struct rcb_qparams q = rcb_qparams_from_scale(SCALE);

    rcb_roi_begin();
    for (long r = 0; r < repeat; ++r) {
        pointwise1x1(pixels, cin, cout, x, w, bias, q, y);
    }
    rcb_roi_end();

    rcb_oracle_pointwise(pixels, cin, cout, x, w, bias, q, y_ref);
    size_t mismatches = rcb_compare_i8(y, y_ref, ny, "y");
    return rcb_finish("pointwise1x1", params, 5, rcb_checksum(y, ny), mismatches);
}
