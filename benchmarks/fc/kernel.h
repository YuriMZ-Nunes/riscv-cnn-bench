#ifndef KERNEL_H
#define KERNEL_H

#include <stdint.h>

#include "../common/rcb_quant.h"

/* Totalmente conectada: y[o] = requant(bias[o] + sum_i x[i] * w[o][i]). */
void fc(long in, long out, const int8_t *x, const int8_t *w, const int32_t *bias,
        struct rcb_qparams q, int8_t *y);

#endif
