/* Convolução 3x3 por im2col + GEMM com RVV (RCB-14). */
#include "../common/rcb_rvv.h"
#include "im2col.h"
#include "kernel.h"

/* GEMM: produto escalar vetorial sobre K = 9*Cin, redução e requantização escalar. */
static void gemm(long pixels, long k_len, long cout, const int8_t *col, const int8_t *w,
                 const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    for (long p = 0; p < pixels; ++p) {
        const int8_t *a = &col[p * k_len];
        for (long co = 0; co < cout; ++co) {
            vint32m4_t acc = rcb_rvv_mac(rcb_rvv_zero(), a, &w[co * k_len], k_len);
            y[p * cout + co] = (int8_t)rcb_requantize(rcb_rvv_reduce(acc, bias[co]), q, 1);
        }
    }
}

void conv3x3_im2col(const struct rcb_conv_shape *s, const int8_t *x, const int8_t *w,
                    const int32_t *bias, struct rcb_qparams q, int8_t *col, int8_t *y)
{
    im2col(s, x, col);
    gemm(s->h * s->w, 9 * s->cin, s->cout, col, w, bias, q, y);
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
