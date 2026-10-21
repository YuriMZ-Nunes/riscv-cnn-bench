/*
 * Formas e oráculos das operações de CNN (RCB-12). Especificação em
 * docs/scope.md; documentação em docs/kernels.md.
 *
 * Layouts:
 *   ativações          NHWC (sem N): [H][W][C]
 *   pesos de conv 3x3  [Cout][3][3][Cin]
 *   pesos depthwise    [3][3][C]
 *   pesos pointwise    [Cout][Cin]
 *   pesos FC           [Out][In]
 *
 * Os oráculos são a versão mais simples possível de cada operação: laços
 * diretos na ordem da definição, acumulação em int64 e teste de borda em cada
 * tap (o padding vale zero, então um tap fora da imagem é pulado). Eles nunca
 * mudam entre variantes; todas as variantes são comparadas com eles. Rodam
 * fora da ROI, mas também são simulados: um oráculo lento aumenta o tempo de
 * cada execução no gem5.
 */
#ifndef RCB_OPS_H
#define RCB_OPS_H

#include <stddef.h>
#include <stdint.h>

#include "rcb_quant.h"

/* Convolução 3x3 (direta e im2col) e depthwise 3x3: stride 1, padding 1. */
struct rcb_conv_shape {
    long h;    /* altura da entrada e da saída */
    long w;    /* largura da entrada e da saída */
    long cin;  /* canais de entrada (depthwise: canais) */
    long cout; /* canais de saída (depthwise: igual a cin) */
};

/* Pixel (ih, iw) da entrada, ou NULL se estiver no padding. */
static inline const int8_t *rcb_pixel(const int8_t *x, const struct rcb_conv_shape *s, long ih,
                                      long iw)
{
    if (ih < 0 || ih >= s->h || iw < 0 || iw >= s->w) {
        return NULL;
    }
    return &x[(ih * s->w + iw) * s->cin];
}

static inline void rcb_oracle_conv3x3(const struct rcb_conv_shape *s, const int8_t *x,
                                      const int8_t *w, const int32_t *bias,
                                      struct rcb_qparams q, int8_t *y)
{
    for (long oh = 0; oh < s->h; ++oh) {
        for (long ow = 0; ow < s->w; ++ow) {
            for (long co = 0; co < s->cout; ++co) {
                int64_t acc = bias[co];
                for (long kh = 0; kh < 3; ++kh) {
                    for (long kw = 0; kw < 3; ++kw) {
                        const int8_t *px = rcb_pixel(x, s, oh + kh - 1, ow + kw - 1);
                        if (px == NULL) {
                            continue; /* padding: vale zero e não soma */
                        }
                        const int8_t *wp = &w[((co * 3 + kh) * 3 + kw) * s->cin];
                        for (long ci = 0; ci < s->cin; ++ci) {
                            acc += (int64_t)px[ci] * wp[ci];
                        }
                    }
                }
                y[(oh * s->w + ow) * s->cout + co] = (int8_t)rcb_requantize((int32_t)acc, q, 1);
            }
        }
    }
}

static inline void rcb_oracle_depthwise3x3(const struct rcb_conv_shape *s, const int8_t *x,
                                           const int8_t *w, const int32_t *bias,
                                           struct rcb_qparams q, int8_t *y)
{
    for (long oh = 0; oh < s->h; ++oh) {
        for (long ow = 0; ow < s->w; ++ow) {
            for (long c = 0; c < s->cin; ++c) {
                int64_t acc = bias[c];
                for (long kh = 0; kh < 3; ++kh) {
                    for (long kw = 0; kw < 3; ++kw) {
                        const int8_t *px = rcb_pixel(x, s, oh + kh - 1, ow + kw - 1);
                        if (px != NULL) { /* padding: vale zero e não soma */
                            acc += (int64_t)px[c] * w[(kh * 3 + kw) * s->cin + c];
                        }
                    }
                }
                y[(oh * s->w + ow) * s->cin + c] = (int8_t)rcb_requantize((int32_t)acc, q, 1);
            }
        }
    }
}

/* Pointwise 1x1: pixels = h * w, pesos [cout][cin]. */
static inline void rcb_oracle_pointwise(long pixels, long cin, long cout, const int8_t *x,
                                        const int8_t *w, const int32_t *bias,
                                        struct rcb_qparams q, int8_t *y)
{
    for (long p = 0; p < pixels; ++p) {
        for (long co = 0; co < cout; ++co) {
            int64_t acc = bias[co];
            for (long ci = 0; ci < cin; ++ci) {
                acc += (int64_t)x[p * cin + ci] * w[co * cin + ci];
            }
            y[p * cout + co] = (int8_t)rcb_requantize((int32_t)acc, q, 1);
        }
    }
}

/* Max pooling 2x2, stride 2: entrada h x w x c, saída (h/2) x (w/2) x c. */
static inline void rcb_oracle_maxpool2x2(long h, long w, long c, const int8_t *x, int8_t *y)
{
    for (long oh = 0; oh < h / 2; ++oh) {
        for (long ow = 0; ow < w / 2; ++ow) {
            for (long ch = 0; ch < c; ++ch) {
                int best = -128;
                for (long dh = 0; dh < 2; ++dh) {
                    for (long dw = 0; dw < 2; ++dw) {
                        int v = x[((2 * oh + dh) * w + (2 * ow + dw)) * c + ch];
                        if (v > best) {
                            best = v;
                        }
                    }
                }
                y[(oh * (w / 2) + ow) * c + ch] = (int8_t)best;
            }
        }
    }
}

static inline void rcb_oracle_requant_relu(long n, const int32_t *acc, struct rcb_qparams q,
                                           int8_t *y)
{
    for (long i = 0; i < n; ++i) {
        y[i] = (int8_t)rcb_requantize(acc[i], q, 1);
    }
}

/* FC: y[o] = requant(bias[o] + sum_i x[i] * w[o][i]). */
static inline void rcb_oracle_fc(long in, long out, const int8_t *x, const int8_t *w,
                                 const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    for (long o = 0; o < out; ++o) {
        int64_t acc = bias[o];
        for (long i = 0; i < in; ++i) {
            acc += (int64_t)x[i] * w[o * in + i];
        }
        y[o] = (int8_t)rcb_requantize((int32_t)acc, q, 1);
    }
}

#endif /* RCB_OPS_H */
