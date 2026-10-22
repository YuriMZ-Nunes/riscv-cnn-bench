/* Convolução pointwise 1x1 com instruções personalizadas (RCB-14). */
#include "../common/cnn_insn.h"
#include "kernel.h"

/* cnn.dot8 sobre Cin (múltiplo de 8) e cnn.rqnt.relu por saída. */
void pointwise1x1(long pixels, long cin, long cout, const int8_t *x, const int8_t *w,
                  const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    const uint64_t prm = cnn_rqnt_params(q.m0, q.s);

    for (long p = 0; p < pixels; ++p) {
        const int8_t *xp = &x[p * cin];
        for (long co = 0; co < cout; ++co) {
            const int8_t *wc = &w[co * cin];
            int64_t acc = bias[co];
            for (long ci = 0; ci < cin; ci += 8) {
                acc = cnn_dot8(acc, cnn_ld8(&xp[ci]), cnn_ld8(&wc[ci]));
            }
            y[p * cout + co] = (int8_t)cnn_rqnt_relu(acc, prm);
        }
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
