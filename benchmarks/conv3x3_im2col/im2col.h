/*
 * Montagem do buffer do im2col (RCB-12), comum às três variantes do kernel:
 * col[(oh*w + ow)][(kh*3 + kw)*cin + ci], com zeros no padding. É só cópia de
 * dados, mantida escalar e igual em todas as variantes para que elas difiram
 * apenas na GEMM.
 */
#ifndef IM2COL_H
#define IM2COL_H

#include "kernel.h"

static inline void im2col(const struct rcb_conv_shape *s, const int8_t *x, int8_t *col)
{
    const long k_len = 9 * s->cin;

    for (long oh = 0; oh < s->h; ++oh) {
        for (long ow = 0; ow < s->w; ++ow) {
            int8_t *row = &col[(oh * s->w + ow) * k_len];
            for (long kh = 0; kh < 3; ++kh) {
                for (long kw = 0; kw < 3; ++kw) {
                    long ih = oh + kh - 1;
                    long iw = ow + kw - 1;
                    int8_t *dst = &row[(kh * 3 + kw) * s->cin];
                    if (ih < 0 || ih >= s->h || iw < 0 || iw >= s->w) {
                        for (long ci = 0; ci < s->cin; ++ci) {
                            dst[ci] = 0;
                        }
                    } else {
                        const int8_t *src = &x[(ih * s->w + iw) * s->cin];
                        for (long ci = 0; ci < s->cin; ++ci) {
                            dst[ci] = src[ci];
                        }
                    }
                }
            }
        }
    }
}

#endif
