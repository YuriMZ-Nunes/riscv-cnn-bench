/* Convolução pointwise 1x1 com RVV (RCB-14). */
#include "../common/rcb_rvv.h"
#include "kernel.h"

/*
 * Produto escalar vetorial sobre Cin, redução e requantização escalar por
 * saída. Com os pesos em [Cout][Cin], comuns às variantes, Cin é a dimensão
 * contígua; vetorizar sobre Cout exigiria transpor os pesos.
 */
void pointwise1x1(long pixels, long cin, long cout, const int8_t *x, const int8_t *w,
                  const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    for (long p = 0; p < pixels; ++p) {
        const int8_t *xp = &x[p * cin];
        for (long co = 0; co < cout; ++co) {
            vint32m4_t acc = rcb_rvv_mac(rcb_rvv_zero(), xp, &w[co * cin], cin);
            y[p * cout + co] = (int8_t)rcb_requantize(rcb_rvv_reduce(acc, bias[co]), q, 1);
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
