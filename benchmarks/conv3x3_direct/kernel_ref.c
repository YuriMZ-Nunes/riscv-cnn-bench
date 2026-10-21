/* Kernel de referência escalar da convolução 3x3 direta (RCB-12). */
#include "kernel.h"

void conv3x3_direct(const struct rcb_conv_shape *s, const int8_t *x, const int8_t *w,
                    const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    const long taps_cin = 9 * s->cin;

    for (long oh = 0; oh < s->h; ++oh) {
        /* Faixa de taps válidos: fora dela o padding vale zero e não soma. */
        long kh0 = oh == 0 ? 1 : 0;
        long kh1 = oh == s->h - 1 ? 2 : 3;
        for (long ow = 0; ow < s->w; ++ow) {
            long kw0 = ow == 0 ? 1 : 0;
            long kw1 = ow == s->w - 1 ? 2 : 3;
            int8_t *out = &y[(oh * s->w + ow) * s->cout];

            for (long co = 0; co < s->cout; ++co) {
                const int8_t *wc = &w[co * taps_cin];
                int32_t acc = bias[co];
                for (long kh = kh0; kh < kh1; ++kh) {
                    for (long kw = kw0; kw < kw1; ++kw) {
                        const int8_t *xp = &x[((oh + kh - 1) * s->w + (ow + kw - 1)) * s->cin];
                        const int8_t *wp = &wc[(kh * 3 + kw) * s->cin];
                        for (long ci = 0; ci < s->cin; ++ci) {
                            acc += (int32_t)xp[ci] * wp[ci];
                        }
                    }
                }
                out[co] = (int8_t)rcb_requantize(acc, q, 1);
            }
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
