/* Convolução 3x3 por im2col + GEMM com instruções personalizadas (RCB-14). */
#include "../common/cnn_insn.h"
#include "im2col.h"
#include "kernel.h"

/* GEMM: cnn.dot8 sobre K = 9*Cin (múltiplo de 8) e cnn.rqnt.relu por saída. */
static void gemm(long pixels, long k_len, long cout, const int8_t *col, const int8_t *w,
                 const int32_t *bias, struct rcb_qparams q, int8_t *y)
{
    const uint64_t prm = cnn_rqnt_params(q.m0, q.s);

    for (long p = 0; p < pixels; ++p) {
        const int8_t *a = &col[p * k_len];
        for (long co = 0; co < cout; ++co) {
            const int8_t *b = &w[co * k_len];
            int64_t acc = bias[co];
            for (long k = 0; k < k_len; k += 8) {
                acc = cnn_dot8(acc, cnn_ld8(&a[k]), cnn_ld8(&b[k]));
            }
            y[p * cout + co] = (int8_t)cnn_rqnt_relu(acc, prm);
        }
    }
}

void conv3x3_im2col(const struct rcb_conv_shape *s, const int8_t *x, const int8_t *w,
                    const int32_t *bias, struct rcb_qparams q, int8_t *col, int8_t *y)
{
    im2col(s, x, col);
    gemm(s->h * s->w, 9 * s->cin, s->cout, col, w, bias, q, y);
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
