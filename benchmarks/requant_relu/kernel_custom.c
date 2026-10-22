/* Requantização int32 -> int8 com ReLU por instrução personalizada (RCB-14). */
#include "../common/cnn_insn.h"
#include "kernel.h"

/* lw + cnn.rqnt.relu + sb por elemento. */
void requant_relu(long n, const int32_t *acc, struct rcb_qparams q, int8_t *y)
{
    const uint64_t prm = cnn_rqnt_params(q.m0, q.s);

    for (long i = 0; i < n; ++i) {
        y[i] = (int8_t)cnn_rqnt_relu(acc[i], prm);
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
