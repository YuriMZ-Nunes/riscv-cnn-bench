#ifndef KERNEL_H
#define KERNEL_H

#include <stdint.h>

#include "../common/rcb_ops.h"

/* Conv 3x3 direta, stride 1, padding 1, requantização com ReLU. */
void conv3x3_direct(const struct rcb_conv_shape *s, const int8_t *x, const int8_t *w,
                    const int32_t *bias, struct rcb_qparams q, int8_t *y);

#endif
