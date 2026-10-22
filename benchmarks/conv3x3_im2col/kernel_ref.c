/* Kernel de referência escalar da convolução 3x3 por im2col + GEMM (RCB-12). */
#include "im2col.h"
#include "kernel.h"

static void gemm(long pixels, long k_len, long cout, const int8_t *col, const int8_t *w,
                 const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    for (long p = 0; p < pixels; ++p) {
        const int8_t *a = &col[p * k_len];
        for (long co = 0; co < cout; ++co) {
            const int8_t *b = &w[co * k_len];
            int32_t acc = bias[co];
            for (long k = 0; k < k_len; ++k) {
                acc += (int32_t)a[k] * b[k];
            }
            y[p * cout + co] = (int8_t)rcb_requantize(acc, q, 1);
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
