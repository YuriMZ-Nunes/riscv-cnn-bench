/* Convolução 3x3 direta com instruções personalizadas (RCB-14). */
#include "../common/cnn_insn.h"
#include "kernel.h"

/* Mesma ordem de laços da referência; o laço de Cin vira cnn.dot8. */
void conv3x3_direct(const struct rcb_conv_shape *s, const int8_t *x, const int8_t *w,
                    const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    const long taps_cin = 9 * s->cin;
    const uint64_t prm = cnn_rqnt_params(q.m0, q.s);

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
                int64_t acc = bias[co];
                for (long kh = kh0; kh < kh1; ++kh) {
                    for (long kw = kw0; kw < kw1; ++kw) {
                        const int8_t *xp = &x[((oh + kh - 1) * s->w + (ow + kw - 1)) * s->cin];
                        const int8_t *wp = &wc[(kh * 3 + kw) * s->cin];
                        for (long ci = 0; ci < s->cin; ci += 8) {
                            acc = cnn_dot8(acc, cnn_ld8(&xp[ci]), cnn_ld8(&wp[ci]));
                        }
                    }
                }
                out[co] = (int8_t)cnn_rqnt_relu(acc, prm);
            }
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
