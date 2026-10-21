/*
 * Convolução 3x3 por im2col + GEMM int8 (RCB-12).
 *
 *     conv3x3_im2col [H] [W] [Cin] [Cout] [R]
 *
 * Stride 1, padding 1, ativações NHWC, pesos [Cout][3][3][Cin], bias int32,
 * requantização com ReLU. Tamanhos de docs/scope.md: S = 16 16 8 16 (padrão),
 * L = 32 32 16 32. Mesmos dados e escala de conv3x3_direct (mesma camada); o buffer col
 * [(H*W)][9*Cin] é alocado fora da ROI e montado dentro dela.
 */
#include <stddef.h>
#include <stdint.h>

#include "../common/rcb_bench.h"
#include "../common/rcb_ops.h"
#include "kernel.h"

#define SEED 0xc0de3301u
#define SCALE (1.0 / 1000.0)

int main(int argc, char **argv)
{
    struct rcb_param params[] = {
        {"H", 16, 1, 256, 1},
        {"W", 16, 1, 256, 1},
        {"Cin", 8, 8, 512, 8},
        {"Cout", 16, 8, 512, 8},
        {"R", 1, 1, 1 << 16, 1},
    };
    rcb_parse_params(argc, argv, params, 5);
    struct rcb_conv_shape s = {params[0].value, params[1].value, params[2].value,
                               params[3].value};
    long repeat = params[4].value;
    size_t nx = (size_t)(s.h * s.w * s.cin);
    size_t nw = (size_t)(s.cout * 9 * s.cin);
    size_t ny = (size_t)(s.h * s.w * s.cout);

    int8_t *x = rcb_alloc(nx, "x");
    int8_t *w = rcb_alloc(nw, "w");
    int32_t *bias = rcb_alloc((size_t)s.cout * sizeof(*bias), "bias");
    int8_t *y = rcb_alloc(ny, "y");
    int8_t *y_ref = rcb_alloc(ny, "y_ref");
    int8_t *col = rcb_alloc((size_t)(s.h * s.w * 9 * s.cin), "col");

    struct rcb_rng rng = rcb_rng_init(SEED);
    rcb_fill_i8(x, nx, &rng, -128, 127);
    rcb_fill_i8(w, nw, &rng, -128, 127);
    rcb_fill_i32(bias, (size_t)s.cout, &rng, -8192, 8192);
    struct rcb_qparams q = rcb_qparams_from_scale(SCALE);

    rcb_roi_begin();
    for (long r = 0; r < repeat; ++r) {
        conv3x3_im2col(&s, x, w, bias, q, col, y);
    }
    rcb_roi_end();

    rcb_oracle_conv3x3(&s, x, w, bias, q, y_ref);
    size_t mismatches = rcb_compare_i8(y, y_ref, ny, "y");
    return rcb_finish("conv3x3_im2col", params, 5, rcb_checksum(y, ny), mismatches);
}
