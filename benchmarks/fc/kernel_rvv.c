/* Camada totalmente conectada com RVV (RCB-14). */
#include "../common/rcb_rvv.h"
#include "kernel.h"

/* Produto escalar vetorial sobre In, redução e requantização escalar por saída. */
void fc(long in, long out, const int8_t *x, const int8_t *w, const int32_t *bias,
        struct rcb_qparams q, int8_t *y)
{
    for (long o = 0; o < out; ++o) {
        vint32m4_t acc = rcb_rvv_mac(rcb_rvv_zero(), x, &w[o * in], in);
        y[o] = (int8_t)rcb_requantize(rcb_rvv_reduce(acc, bias[o]), q, 1);
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
