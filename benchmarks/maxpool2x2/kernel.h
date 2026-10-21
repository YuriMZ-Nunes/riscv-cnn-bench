#ifndef KERNEL_H
#define KERNEL_H

#include <stdint.h>

/* Max pooling 2x2, stride 2: h x w x c -> (h/2) x (w/2) x c, sem requantização. */
void maxpool2x2(long h, long w, long c, const int8_t *x, int8_t *y);

#endif
