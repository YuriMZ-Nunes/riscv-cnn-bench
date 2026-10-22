/* Camada totalmente conectada com instruções personalizadas (RCB-14). */
#include "../common/cnn_insn.h"
#include "kernel.h"

/* cnn.dot8 sobre In (múltiplo de 8) e cnn.rqnt.relu por saída. */
void fc(long in, long out, const int8_t *x, const int8_t *w, const int32_t *bias,
        struct rcb_qparams q, int8_t *y)
{
    const uint64_t prm = cnn_rqnt_params(q.m0, q.s);

    for (long o = 0; o < out; ++o) {
        const int8_t *wo = &w[o * in];
        int64_t acc = bias[o];
        for (long i = 0; i < in; i += 8) {
            acc = cnn_dot8(acc, cnn_ld8(&x[i]), cnn_ld8(&wo[i]));
        }
        y[o] = (int8_t)cnn_rqnt_relu(acc, prm);
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
