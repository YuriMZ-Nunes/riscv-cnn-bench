/* Kernel de referência escalar da convolução pointwise 1x1 (RCB-12). */
#include "kernel.h"

void pointwise1x1(long pixels, long cin, long cout, const int8_t *x, const int8_t *w,
                  const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    for (long p = 0; p < pixels; ++p) {
        const int8_t *xp = &x[p * cin];
        for (long co = 0; co < cout; ++co) {
            const int8_t *wc = &w[co * cin];
            int32_t acc = bias[co];
            for (long ci = 0; ci < cin; ++ci) {
                acc += (int32_t)xp[ci] * wc[ci];
            }
            y[p * cout + co] = (int8_t)rcb_requantize(acc, q, 1);
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
