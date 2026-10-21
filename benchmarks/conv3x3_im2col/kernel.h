#ifndef KERNEL_H
#define KERNEL_H

#include <stdint.h>

#include "../common/rcb_ops.h"

/*
 * Conv 3x3 por im2col + GEMM: monta col[(h*w)][9*cin] (padding = 0) e
 * multiplica pelos pesos [cout][9*cin]. A montagem faz parte do kernel.
 */
void conv3x3_im2col(const struct rcb_conv_shape *s, const int8_t *x, const int8_t *w,
                    const int32_t *bias, struct rcb_qparams q, int8_t *col, int8_t *y);

#endif
