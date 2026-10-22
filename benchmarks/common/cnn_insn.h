/*
 * Instruções personalizadas para operações de CNN int8 (RCB-10).
 *
 * Especificação: docs/custom_instructions.md. Este header oferece, para cada
 * instrução:
 *
 *   - cnn_<op>_model(): modelo de referência em C portátil, que define a
 *     semântica e serve de oráculo nos testes e na equivalência (RCB-15);
 *   - cnn_<op>(): a forma usada pelos kernels. Com CNN_INSN_HW definido, emite
 *     a instrução com `.insn` (só roda no gem5 do fork, RCB-13); sem ele,
 *     chama o modelo, o que permite executar no QEMU e no gem5 atual.
 *
 * Todas as instruções usam o formato R. Operandos empacotados ocupam um
 * registrador de 64 bits, com o byte 0 nos bits 7:0 (little-endian), que é o
 * que um `ld` de 8 bytes contíguos produz.
 *
 * O modelo assume deslocamento aritmético à direita de inteiros negativos,
 * como o GCC faz em RISC-V.
 */
#ifndef CNN_INSN_H
#define CNN_INSN_H

#include <stdint.h>
#include <string.h>

/* Campos de codificação (ver tabela de codificação na especificação). */
#define CNN_FUNCT7_DOT8 0x00 /* custom-0, funct3 = 0 */
#define CNN_FUNCT7_MAX8 0x00 /* custom-0, funct3 = 1 */
#define CNN_FUNCT7_DWMAC 0x01 /* custom-0, funct3 = p (0..3) */
#define CNN_FUNCT7_RQNT 0x00 /* custom-1, funct3 = 0 */
#define CNN_FUNCT7_RQNT_RELU 0x01 /* custom-1, funct3 = 0 */

/* Byte i de um registrador empacotado, com sinal. */
static inline int32_t cnn_lane8(uint64_t reg, unsigned i)
{
    return (int8_t)(uint8_t)(reg >> (8u * i));
}

/* Empacota os parâmetros de requantização em rs2: M0 nos bits 31:0, s nos 36:32. */
static inline uint64_t cnn_rqnt_params(int32_t m0, unsigned s)
{
    return (uint64_t)(uint32_t)m0 | ((uint64_t)(s & 31u) << 32);
}

/*
 * Carga e armazenamento de 8 bytes contíguos (um registrador empacotado). O
 * endereço precisa estar alinhado a 8 (requisito dos kernels); com isso o
 * GCC emite um único ld/sd, e o memcpy evita violar as regras de aliasing.
 */
static inline uint64_t cnn_ld8(const void *p)
{
    uint64_t v;
    memcpy(&v, __builtin_assume_aligned(p, 8), sizeof v);
    return v;
}

static inline void cnn_sd8(void *p, uint64_t v)
{
    memcpy(__builtin_assume_aligned(p, 8), &v, sizeof v);
}

/* ---------------------------------------------------------------------------
 * Modelos de referência
 * ------------------------------------------------------------------------- */

/* cnn.dot8: rd = sext32(rd[31:0] + soma de 8 produtos int8 x int8). */
static inline int32_t cnn_dot8_model(int32_t acc, uint64_t x, uint64_t w)
{
    uint32_t sum = (uint32_t)acc; /* aritmética módulo 2^32, sem UB */
    for (unsigned i = 0; i < 8; ++i) {
        sum += (uint32_t)(cnn_lane8(x, i) * cnn_lane8(w, i));
    }
    return (int32_t)sum;
}

/* cnn.max8: máximo com sinal, byte a byte. */
static inline uint64_t cnn_max8_model(uint64_t a, uint64_t b)
{
    uint64_t out = 0;
    for (unsigned i = 0; i < 8; ++i) {
        int32_t x = cnn_lane8(a, i);
        int32_t y = cnn_lane8(b, i);
        out |= (uint64_t)(uint8_t)(x > y ? x : y) << (8u * i);
    }
    return out;
}

/* cnn.dwmac p: duas faixas int32 de rd acumulam x.b[2p+j] * w.b[2p+j]. */
static inline uint64_t cnn_dwmac_model(uint64_t acc, uint64_t x, uint64_t w, unsigned p)
{
    uint64_t out = 0;
    for (unsigned j = 0; j < 2; ++j) {
        unsigned k = 2u * (p & 3u) + j;
        uint32_t lane = (uint32_t)(acc >> (32u * j));
        lane += (uint32_t)(cnn_lane8(x, k) * cnn_lane8(w, k));
        out |= (uint64_t)lane << (32u * j);
    }
    return out;
}

/* cnn.rqnt / cnn.rqnt.relu: sat8(ReLU?((acc * M0 + 2^(30+s)) >> (31+s))). */
static inline int32_t cnn_rqnt_model(int32_t acc, uint64_t params, int relu)
{
    int32_t m0 = (int32_t)(uint32_t)params;
    unsigned s = (unsigned)(params >> 32) & 31u;
    /* |acc * M0| <= 2^62 e o arredondamento <= 2^61: cabe em int64. */
    int64_t y = ((int64_t)acc * m0 + ((int64_t)1 << (30 + s))) >> (31 + s);
    int64_t lo = relu ? 0 : -128;
    if (y < lo) {
        y = lo;
    }
    if (y > 127) {
        y = 127;
    }
    return (int32_t)y;
}

/* ---------------------------------------------------------------------------
 * Forma usada pelos kernels
 *
 * Os acumuladores de cnn_dot8 e cnn_rqnt* são int64_t, a largura do
 * registrador: as instruções leem só os bits 31:0 e devolvem o resultado
 * estendido com sinal. Com int32_t, o GCC estenderia o sinal de novo (sext.w)
 * a cada chamada, uma instrução a mais por cnn.dot8 que não é da variante.
 * ------------------------------------------------------------------------- */

#ifdef CNN_INSN_HW

/* Instruções reais. Só executam no gem5 do fork (RCB-13). */
static inline int64_t cnn_dot8(int64_t acc, uint64_t x, uint64_t w)
{
    __asm__(".insn r CUSTOM_0, 0, 0x00, %0, %1, %2" : "+r"(acc) : "r"(x), "r"(w));
    return acc;
}

static inline uint64_t cnn_max8(uint64_t a, uint64_t b)
{
    uint64_t out;
    __asm__(".insn r CUSTOM_0, 1, 0x00, %0, %1, %2" : "=r"(out) : "r"(a), "r"(b));
    return out;
}

/* p vai no funct3 e precisa ser constante: CNN_DWMAC(acc, x, w, 0..3). */
#define CNN_DWMAC(acc, x, w, p)                                                       \
    __asm__(".insn r CUSTOM_0, " #p ", 0x01, %0, %1, %2"                             \
            : "+r"(acc)                                                               \
            : "r"((uint64_t)(x)), "r"((uint64_t)(w)))

static inline int64_t cnn_rqnt(int64_t acc, uint64_t params)
{
    int64_t out;
    __asm__(".insn r CUSTOM_1, 0, 0x00, %0, %1, %2" : "=r"(out) : "r"(acc), "r"(params));
    return out;
}

static inline int64_t cnn_rqnt_relu(int64_t acc, uint64_t params)
{
    int64_t out;
    __asm__(".insn r CUSTOM_1, 0, 0x01, %0, %1, %2" : "=r"(out) : "r"(acc), "r"(params));
    return out;
}

#else

/* Sem CNN_INSN_HW: mesmo código C dos kernels, executado pelo modelo. */
static inline int64_t cnn_dot8(int64_t acc, uint64_t x, uint64_t w)
{
    return cnn_dot8_model((int32_t)acc, x, w);
}

static inline uint64_t cnn_max8(uint64_t a, uint64_t b)
{
    return cnn_max8_model(a, b);
}

#define CNN_DWMAC(acc, x, w, p) ((acc) = cnn_dwmac_model((acc), (x), (w), (p)))

static inline int64_t cnn_rqnt(int64_t acc, uint64_t params)
{
    return cnn_rqnt_model((int32_t)acc, params, 0);
}

static inline int64_t cnn_rqnt_relu(int64_t acc, uint64_t params)
{
    return cnn_rqnt_model((int32_t)acc, params, 1);
}

#endif /* CNN_INSN_HW */

#endif /* CNN_INSN_H */
