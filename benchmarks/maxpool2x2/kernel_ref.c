/* Kernel de referência escalar do max pooling 2x2 (RCB-12). */
#include "kernel.h"

void maxpool2x2(long h, long w, long c, const int8_t *x, int8_t *y)
{
    const long row = w * c; /* bytes de uma linha da entrada */

    for (long oh = 0; oh < h / 2; ++oh) {
        for (long ow = 0; ow < w / 2; ++ow) {
            const int8_t *p0 = &x[(2 * oh) * row + (2 * ow) * c];
            const int8_t *p1 = p0 + row;
            int8_t *out = &y[(oh * (w / 2) + ow) * c];
            for (long ch = 0; ch < c; ++ch) {
                int8_t a = p0[ch] > p0[c + ch] ? p0[ch] : p0[c + ch];
                int8_t b = p1[ch] > p1[c + ch] ? p1[ch] : p1[c + ch];
                out[ch] = a > b ? a : b;
            }
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
