/* Kernel de referência escalar da camada totalmente conectada (RCB-12). */
#include "kernel.h"

void fc(long in, long out, const int8_t *x, const int8_t *w, const int32_t *bias,
        struct rcb_qparams q, int8_t *y)
{
    for (long o = 0; o < out; ++o) {
        const int8_t *wo = &w[o * in];
        int32_t acc = bias[o];
        for (long i = 0; i < in; ++i) {
            acc += (int32_t)x[i] * wo[i];
        }
        y[o] = (int8_t)rcb_requantize(acc, q, 1);
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
