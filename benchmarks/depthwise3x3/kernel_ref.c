/* Kernel de referência escalar da convolução depthwise 3x3 (RCB-12). */
#include "kernel.h"

void depthwise3x3(const struct rcb_conv_shape *s, const int8_t *x, const int8_t *w,
                  const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    const long c_len = s->cin;

    for (long oh = 0; oh < s->h; ++oh) {
        long kh0 = oh == 0 ? 1 : 0;
        long kh1 = oh == s->h - 1 ? 2 : 3;
        for (long ow = 0; ow < s->w; ++ow) {
            long kw0 = ow == 0 ? 1 : 0;
            long kw1 = ow == s->w - 1 ? 2 : 3;
            int8_t *out = &y[(oh * s->w + ow) * c_len];

            for (long c = 0; c < c_len; ++c) {
                int32_t acc = bias[c];
                for (long kh = kh0; kh < kh1; ++kh) {
                    for (long kw = kw0; kw < kw1; ++kw) {
                        int32_t xv = x[((oh + kh - 1) * s->w + (ow + kw - 1)) * c_len + c];
                        acc += xv * w[(kh * 3 + kw) * c_len + c];
                    }
                }
                out[c] = (int8_t)rcb_requantize(acc, q, 1);
            }
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
