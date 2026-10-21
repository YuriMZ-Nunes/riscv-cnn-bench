/* Kernel de referência escalar da requantização com ReLU (RCB-12). */
#include "kernel.h"

void requant_relu(long n, const int32_t *acc, struct rcb_qparams q, int8_t *y)
{
    for (long i = 0; i < n; ++i) {
        y[i] = (int8_t)rcb_requantize(acc[i], q, 1);
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
