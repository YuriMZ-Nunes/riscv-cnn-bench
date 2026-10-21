/*
 * Dados determinísticos e alocação alinhada (RCB-11).
 *
 * O gerador é o splitmix64: só aritmética inteira de 64 bits, então a mesma
 * semente produz os mesmos tensores no QEMU, no gem5 e em qualquer variante
 * (referência, personalizada, RVV).
 */
#ifndef RCB_DATA_H
#define RCB_DATA_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Alinhamento dos tensores: 64 bytes cobre o `ld` de 8 bytes das instruções
 * personalizadas e uma linha de cache de 64 bytes. */
#define RCB_ALIGN 64u

struct rcb_rng {
    uint64_t state;
};

static inline struct rcb_rng rcb_rng_init(uint64_t seed)
{
    struct rcb_rng rng = {seed};
    return rng;
}

/* splitmix64 (Steele, Lea e Flood, 2014). */
static inline uint64_t rcb_rng_next(struct rcb_rng *rng)
{
    uint64_t z = (rng->state += 0x9e3779b97f4a7c15u);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9u;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebu;
    return z ^ (z >> 31);
}

/* Inteiro em [lo, hi]. O viés do módulo é desprezível e determinístico. */
static inline int64_t rcb_rng_range(struct rcb_rng *rng, int64_t lo, int64_t hi)
{
    uint64_t span = (uint64_t)(hi - lo) + 1u;
    return lo + (int64_t)(rcb_rng_next(rng) % span);
}

static inline void rcb_fill_i8(int8_t *dst, size_t n, struct rcb_rng *rng, int lo, int hi)
{
    for (size_t i = 0; i < n; ++i) {
        dst[i] = (int8_t)rcb_rng_range(rng, lo, hi);
    }
}

static inline void rcb_fill_i32(int32_t *dst, size_t n, struct rcb_rng *rng, int32_t lo,
                                int32_t hi)
{
    for (size_t i = 0; i < n; ++i) {
        dst[i] = (int32_t)rcb_rng_range(rng, lo, hi);
    }
}

/* Buffer zerado e alinhado a RCB_ALIGN. Sem memória, encerra com código 2. */
static inline void *rcb_alloc(size_t bytes, const char *what)
{
    size_t size = (bytes + RCB_ALIGN - 1) / RCB_ALIGN * RCB_ALIGN;
    void *ptr = aligned_alloc(RCB_ALIGN, size == 0 ? RCB_ALIGN : size);
    if (ptr == NULL) {
        fprintf(stderr, "ERRO: memória insuficiente para %s (%zu bytes)\n", what, bytes);
        exit(2);
    }
    memset(ptr, 0, size == 0 ? RCB_ALIGN : size);
    return ptr;
}

#endif /* RCB_DATA_H */
