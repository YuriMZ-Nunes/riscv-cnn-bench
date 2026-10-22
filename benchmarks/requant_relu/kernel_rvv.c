/* Requantização int32 -> int8 com ReLU em RVV (RCB-14). */
#include "../common/rcb_rvv.h"
#include "kernel.h"

/* Blocos de vl elementos: vle32, requantização vetorial e vse8. */
void requant_relu(long n, const int32_t *acc, struct rcb_qparams q, int8_t *y)
{
    for (long i = 0; i < n;) {
        size_t vl = __riscv_vsetvl_e32m4((size_t)(n - i));
        vint32m4_t a = __riscv_vle32_v_i32m4(&acc[i], vl);
        __riscv_vse8_v_i8m1(&y[i], rcb_rvv_requant_relu(a, q, vl), vl);
        i += (long)vl;
    }
#ifdef RCB_INJECT_ERROR
    y[0] ^= 1;
#endif
}
