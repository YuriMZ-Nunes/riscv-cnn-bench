/* Max pooling 2x2 com instruções personalizadas (RCB-14). */
#include "../common/cnn_insn.h"
#include "kernel.h"

/* 8 canais por vez: 4 ld, 3 cnn.max8 e 1 sd. */
void maxpool2x2(long h, long w, long c, const int8_t *x, int8_t *y)
{
    const long row = w * c; /* bytes de uma linha da entrada */

    for (long oh = 0; oh < h / 2; ++oh) {
        for (long ow = 0; ow < w / 2; ++ow) {
            const int8_t *p0 = &x[(2 * oh) * row + (2 * ow) * c];
            const int8_t *p1 = p0 + row;
            int8_t *out = &y[(oh * (w / 2) + ow) * c];
            for (long ch = 0; ch < c; ch += 8) {
                uint64_t a = cnn_max8(cnn_ld8(&p0[ch]), cnn_ld8(&p0[c + ch]));
                uint64_t b = cnn_max8(cnn_ld8(&p1[ch]), cnn_ld8(&p1[c + ch]));
                cnn_sd8(&out[ch], cnn_max8(a, b));
            }
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
