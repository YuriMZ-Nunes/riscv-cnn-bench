/*
 * Camada totalmente conectada int8 (RCB-12).
 *
 *     fc [In] [Out] [R]
 *
 * Pesos [Out][In], bias int32, requantização com ReLU. Tamanhos de
 * docs/scope.md: S = 512 32 (padrão), L = 1024 512 (os pesos excedem a L2).
 */
#include <stddef.h>
#include <stdint.h>

#include "../common/rcb_bench.h"
#include "../common/rcb_ops.h"
#include "kernel.h"

#define SEED 0xc0de3306u
#define SCALE (1.0 / 3000.0)

int main(int argc, char **argv)
{
    struct rcb_param params[] = {
        {"In", 512, 8, 1 << 16, 8},
        {"Out", 32, 8, 1 << 14, 8},
        {"R", 1, 1, 1 << 16, 1},
    };
    rcb_parse_params(argc, argv, params, 3);
    long in = params[0].value;
    long out = params[1].value;
    long repeat = params[2].value;
    size_t nw = (size_t)(out * in);

    int8_t *x = rcb_alloc((size_t)in, "x");
    int8_t *w = rcb_alloc(nw, "w");
    int32_t *bias = rcb_alloc((size_t)out * sizeof(*bias), "bias");
    int8_t *y = rcb_alloc((size_t)out, "y");
    int8_t *y_ref = rcb_alloc((size_t)out, "y_ref");

    struct rcb_rng rng = rcb_rng_init(SEED);
    rcb_fill_i8(x, (size_t)in, &rng, -128, 127);
    rcb_fill_i8(w, nw, &rng, -128, 127);
    rcb_fill_i32(bias, (size_t)out, &rng, -8192, 8192);
    struct rcb_qparams q = rcb_qparams_from_scale(SCALE);

    rcb_roi_begin();
    for (long r = 0; r < repeat; ++r) {
        fc(in, out, x, w, bias, q, y);
    }
    rcb_roi_end();

    rcb_oracle_fc(in, out, x, w, bias, q, y_ref);
    size_t mismatches = rcb_compare_i8(y, y_ref, (size_t)out, "y");
    return rcb_finish("fc", params, 3, rcb_checksum(y, (size_t)out), mismatches);
}
