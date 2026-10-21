#ifndef KERNEL_H
#define KERNEL_H

#include <stdint.h>

#include "../common/rcb_ops.h"

/* Depthwise 3x3, stride 1, padding 1, um filtro [3][3] por canal. */
void depthwise3x3(const struct rcb_conv_shape *s, const int8_t *x, const int8_t *w,
                  const int32_t *bias, struct rcb_qparams q, int8_t *y);

#endif
