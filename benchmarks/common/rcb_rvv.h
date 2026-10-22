/*
 * Blocos comuns das variantes RVV dos kernels (RCB-14).
 *
 * Usados só pelos kernel_rvv.c, compilados com -march=rv64gcv. O código é
 * independente da VLEN (vsetvl a cada bloco); os tipos seguem a razão
 * SEW/LMUL = 8: int8 em LMUL 1, produtos int16 em LMUL 2, acumuladores int32
 * em LMUL 4 e o produto da requantização em int64, LMUL 8.
 */
#ifndef RCB_RVV_H
#define RCB_RVV_H

#ifndef __riscv_vector
#error "rcb_rvv.h exige a extensão V (-march=rv64gcv)"
#endif

#include <riscv_vector.h>
#include <stdint.h>

#include "rcb_quant.h"

/* Acumulador int32 zerado, com o tamanho máximo do grupo. */
static inline vint32m4_t rcb_rvv_zero(void)
{
    return __riscv_vmv_v_x_i32m4(0, __riscv_vsetvlmax_e32m4());
}

/*
 * acc[j] += a[i] * b[i] para os n pares, faixa a faixa: vle8 + vle8 + vwmul
 * (int16, exato para int8 x int8) + vwadd.wv (int32). O acumulador é
 * tail-undisturbed (_tu), então um último bloco menor não apaga as faixas de
 * cima, somadas por rcb_rvv_reduce.
 */
static inline vint32m4_t rcb_rvv_mac(vint32m4_t acc, const int8_t *a, const int8_t *b, long n)
{
    for (long i = 0; i < n;) {
        size_t vl = __riscv_vsetvl_e8m1((size_t)(n - i));
        vint8m1_t va = __riscv_vle8_v_i8m1(a + i, vl);
        vint8m1_t vb = __riscv_vle8_v_i8m1(b + i, vl);
        vint16m2_t prod = __riscv_vwmul_vv_i16m2(va, vb, vl);
        acc = __riscv_vwadd_wv_i32m4_tu(acc, acc, prod, vl);
        i += (long)vl;
    }
    return acc;
}

/*
 * init + soma de todas as faixas do acumulador. Os 4 registradores do grupo
 * são somados com vadd.vv em LMUL 1 antes do vredsum, também em LMUL 1.
 *
 * Contorno de uma limitação do gem5 (O3CPU): um vredsum com LMUL > 1 vira
 * vários micro-ops que encadeiam o parcial pelo registrador de destino sem
 * dependência entre eles, e a O3 pode executar um micro-op antes do anterior
 * (resultado errado, observado na fc e na pointwise). Com LMUL 1 o vredsum é
 * um único micro-op. Ver docs/kernels.md.
 */
static inline int32_t rcb_rvv_reduce(vint32m4_t acc, int32_t init)
{
    size_t vl = __riscv_vsetvlmax_e32m1();
    vint32m1_t part = __riscv_vadd_vv_i32m1(__riscv_vget_v_i32m4_i32m1(acc, 0),
                                            __riscv_vget_v_i32m4_i32m1(acc, 1), vl);
    part = __riscv_vadd_vv_i32m1(part, __riscv_vget_v_i32m4_i32m1(acc, 2), vl);
    part = __riscv_vadd_vv_i32m1(part, __riscv_vget_v_i32m4_i32m1(acc, 3), vl);
    vint32m1_t sum = __riscv_vmv_s_x_i32m1(init, 1);
    sum = __riscv_vredsum_vs_i32m1_i32m1(part, sum, vl);
    return __riscv_vmv_x_s_i32m1_i32(sum);
}

/*
 * Requantização com ReLU de vl acumuladores, a mesma fórmula de
 * rcb_requantize: y = sat8(ReLU((acc * M0 + 2^(30+s)) >> (31+s))). O produto
 * vai a int64 (vwmul.vx); o deslocamento com estreitamento (vnsra) volta a
 * int32 sem perda, pois |y| <= 2^31; ReLU e saturação com vmax/vmin; dois
 * vncvt levam a int8.
 */
static inline vint8m1_t rcb_rvv_requant_relu(vint32m4_t acc, struct rcb_qparams q, size_t vl)
{
    vint64m8_t prod = __riscv_vwmul_vx_i64m8(acc, q.m0, vl);
    prod = __riscv_vadd_vx_i64m8(prod, (int64_t)1 << (30 + q.s), vl);
    vint32m4_t y = __riscv_vnsra_wx_i32m4(prod, 31 + q.s, vl);
    y = __riscv_vmax_vx_i32m4(y, 0, vl);
    y = __riscv_vmin_vx_i32m4(y, 127, vl);
    vint16m2_t y16 = __riscv_vncvt_x_x_w_i16m2(y, vl);
    return __riscv_vncvt_x_x_w_i8m1(y16, vl);
}

#endif /* RCB_RVV_H */
