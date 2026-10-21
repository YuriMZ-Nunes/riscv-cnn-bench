#ifndef KERNEL_H
#define KERNEL_H

#include <stdint.h>

#include "../common/rcb_quant.h"

/* Requantização int32 -> int8 com ReLU, elemento a elemento. */
void requant_relu(long n, const int32_t *acc, struct rcb_qparams q, int8_t *y);

#endif
