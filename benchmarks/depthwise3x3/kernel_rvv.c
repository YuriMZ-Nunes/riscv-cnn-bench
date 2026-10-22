/* Convolução depthwise 3x3 com RVV (RCB-14). */
#include "../common/rcb_rvv.h"
#include "kernel.h"

/*
 * Vetoriza sobre os canais (contíguos em NHWC): o acumulador int32 começa no
 * bias, cada tap soma vwmul (int16) com vwadd.wv, e a requantização com ReLU
 * é vetorial.
 */
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

            for (long c = 0; c < c_len;) {
                size_t vl = __riscv_vsetvl_e8m1((size_t)(c_len - c));
                vint32m4_t acc = __riscv_vle32_v_i32m4(&bias[c], vl);
                for (long kh = kh0; kh < kh1; ++kh) {
                    for (long kw = kw0; kw < kw1; ++kw) {
                        vint8m1_t xv = __riscv_vle8_v_i8m1(
                            &x[((oh + kh - 1) * s->w + (ow + kw - 1)) * c_len + c], vl);
                        vint8m1_t wv = __riscv_vle8_v_i8m1(&w[(kh * 3 + kw) * c_len + c], vl);
                        acc = __riscv_vwadd_wv_i32m4(acc, __riscv_vwmul_vv_i16m2(xv, wv, vl), vl);
                    }
                }
                __riscv_vse8_v_i8m1(&out[c], rcb_rvv_requant_relu(acc, q, vl), vl);
                c += (long)vl;
            }
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
