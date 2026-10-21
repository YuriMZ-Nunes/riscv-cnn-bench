#ifndef KERNEL_H
#define KERNEL_H

#include <stdint.h>

#include "../common/rcb_ops.h"

/* Pointwise 1x1: para cada um dos `pixels` pixels, cin -> cout. */
void pointwise1x1(long pixels, long cin, long cout, const int8_t *x, const int8_t *w,
                  const int32_t *bias, struct rcb_qparams q, int8_t *y);

#endif
