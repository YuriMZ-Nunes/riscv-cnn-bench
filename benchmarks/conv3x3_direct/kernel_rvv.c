/* Convolução 3x3 direta com RVV (RCB-14). */
#include "../common/rcb_rvv.h"
#include "kernel.h"

/*
 * Mesma ordem de laços da referência. Os taps válidos de uma saída acumulam
 * no mesmo vetor (produto faixa a faixa sobre Cin); uma redução e uma
 * requantização escalar por saída.
 */
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
                vint32m4_t acc = rcb_rvv_zero();
                for (long kh = kh0; kh < kh1; ++kh) {
                    for (long kw = kw0; kw < kw1; ++kw) {
                        const int8_t *xp = &x[((oh + kh - 1) * s->w + (ow + kw - 1)) * s->cin];
                        acc = rcb_rvv_mac(acc, xp, &wc[(kh * 3 + kw) * s->cin], s->cin);
                    }
                }
                out[co] = (int8_t)rcb_requantize(rcb_rvv_reduce(acc, bias[co]), q, 1);
            }
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
