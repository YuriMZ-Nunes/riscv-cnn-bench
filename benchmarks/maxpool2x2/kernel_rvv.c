/* Max pooling 2x2 com RVV (RCB-14). */
#include <riscv_vector.h>

#include "kernel.h"

/* Vetoriza sobre os canais: 4 vle8, 3 vmax e 1 vse8 por bloco. */
void maxpool2x2(long h, long w, long c, const int8_t *x, int8_t *y)
{
    const long row = w * c; /* bytes de uma linha da entrada */

    for (long oh = 0; oh < h / 2; ++oh) {
        for (long ow = 0; ow < w / 2; ++ow) {
            const int8_t *p0 = &x[(2 * oh) * row + (2 * ow) * c];
            const int8_t *p1 = p0 + row;
            int8_t *out = &y[(oh * (w / 2) + ow) * c];
            for (long ch = 0; ch < c;) {
                size_t vl = __riscv_vsetvl_e8m1((size_t)(c - ch));
                vint8m1_t a = __riscv_vmax_vv_i8m1(__riscv_vle8_v_i8m1(&p0[ch], vl),
                                                   __riscv_vle8_v_i8m1(&p0[c + ch], vl), vl);
                vint8m1_t b = __riscv_vmax_vv_i8m1(__riscv_vle8_v_i8m1(&p1[ch], vl),
                                                   __riscv_vle8_v_i8m1(&p1[c + ch], vl), vl);
                __riscv_vse8_v_i8m1(&out[ch], __riscv_vmax_vv_i8m1(a, b, vl), vl);
                ch += (long)vl;
            }
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
