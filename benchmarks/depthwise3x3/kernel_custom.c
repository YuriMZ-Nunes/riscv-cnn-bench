/* Convolução depthwise 3x3 com instruções personalizadas (RCB-14). */
#include "../common/cnn_insn.h"
#include "kernel.h"

/*
 * 8 canais por vez (C múltiplo de 8). Os acumuladores ficam em 4 registradores
 * com 2 faixas int32 cada (canais c+2p e c+2p+1), carregados do bias com um ld
 * por par. Por tap: 2 ld e 4 cnn.dwmac. No fim, a faixa baixa vai direto ao
 * cnn.rqnt.relu (que lê só os bits 31:0) e a alta precisa de um srai.
 */
void depthwise3x3(const struct rcb_conv_shape *s, const int8_t *x, const int8_t *w,
                  const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    const long c_len = s->cin;
    const uint64_t prm = cnn_rqnt_params(q.m0, q.s);

    for (long oh = 0; oh < s->h; ++oh) {
        long kh0 = oh == 0 ? 1 : 0;
        long kh1 = oh == s->h - 1 ? 2 : 3;
        for (long ow = 0; ow < s->w; ++ow) {
            long kw0 = ow == 0 ? 1 : 0;
            long kw1 = ow == s->w - 1 ? 2 : 3;
            int8_t *out = &y[(oh * s->w + ow) * c_len];

            for (long c = 0; c < c_len; c += 8) {
                uint64_t a01 = cnn_ld8(&bias[c]);
                uint64_t a23 = cnn_ld8(&bias[c + 2]);
                uint64_t a45 = cnn_ld8(&bias[c + 4]);
                uint64_t a67 = cnn_ld8(&bias[c + 6]);
                for (long kh = kh0; kh < kh1; ++kh) {
                    for (long kw = kw0; kw < kw1; ++kw) {
                        uint64_t xv =
                            cnn_ld8(&x[((oh + kh - 1) * s->w + (ow + kw - 1)) * c_len + c]);
                        uint64_t wv = cnn_ld8(&w[(kh * 3 + kw) * c_len + c]);
                        CNN_DWMAC(a01, xv, wv, 0);
                        CNN_DWMAC(a23, xv, wv, 1);
                        CNN_DWMAC(a45, xv, wv, 2);
                        CNN_DWMAC(a67, xv, wv, 3);
                    }
                }
                out[c + 0] = (int8_t)cnn_rqnt_relu((int64_t)a01, prm);
                out[c + 1] = (int8_t)cnn_rqnt_relu((int64_t)a01 >> 32, prm);
                out[c + 2] = (int8_t)cnn_rqnt_relu((int64_t)a23, prm);
                out[c + 3] = (int8_t)cnn_rqnt_relu((int64_t)a23 >> 32, prm);
                out[c + 4] = (int8_t)cnn_rqnt_relu((int64_t)a45, prm);
                out[c + 5] = (int8_t)cnn_rqnt_relu((int64_t)a45 >> 32, prm);
                out[c + 6] = (int8_t)cnn_rqnt_relu((int64_t)a67, prm);
                out[c + 7] = (int8_t)cnn_rqnt_relu((int64_t)a67 >> 32, prm);
            }
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
