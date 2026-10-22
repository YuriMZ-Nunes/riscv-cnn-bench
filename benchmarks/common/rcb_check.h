/*
 * Verificação, checksum e linha de resultado (RCB-11).
 */
#ifndef RCB_CHECK_H
#define RCB_CHECK_H

#include <inttypes.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "rcb_args.h"

/* Variante: a do Makefile (kernel.mk) ou, sem ela, deduzida das flags. */
#if defined(RCB_VARIANT_NAME)
#define RCB_VARIANT RCB_VARIANT_NAME
#elif defined(CNN_INSN_HW)
#define RCB_VARIANT "custom"
#elif defined(__riscv_vector)
#define RCB_VARIANT "rvv"
#else
#define RCB_VARIANT "ref"
#endif

/* FNV-1a de 64 bits sobre os bytes de um buffer. */
static inline uint64_t rcb_checksum(const void *data, size_t bytes)
{
    const uint8_t *p = data;
    uint64_t hash = 0xcbf29ce484222325u;
    for (size_t i = 0; i < bytes; ++i) {
        hash ^= p[i];
        hash *= 0x100000001b3u;
    }
    return hash;
}

/* Compara com o oráculo; mostra a primeira diferença no stderr. */
static inline size_t rcb_compare_i8(const int8_t *got, const int8_t *want, size_t n,
                                    const char *what)
{
    size_t mismatches = 0;
    for (size_t i = 0; i < n; ++i) {
        if (got[i] != want[i]) {
            if (mismatches == 0) {
                fprintf(stderr, "ERRO: %s[%zu] = %d, oráculo = %d\n", what, i, got[i], want[i]);
            }
            ++mismatches;
        }
    }
    return mismatches;
}

/*
 * Imprime "RESULT bench=<nome> variant=<v> <P>=<valor>... checksum=0x...
 * mismatches=<n>" e devolve o código de saída: 0 sem diferenças, 1 com.
 */
static inline int rcb_finish(const char *bench, const struct rcb_param *params, int count,
                             uint64_t checksum, size_t mismatches)
{
    printf("RESULT bench=%s variant=%s", bench, RCB_VARIANT);
    for (int i = 0; i < count; ++i) {
        printf(" %s=%ld", params[i].name, params[i].value);
    }
    printf(" checksum=0x%016" PRIx64 " mismatches=%zu\n", checksum, mismatches);
    return mismatches == 0 ? 0 : 1;
}

#endif /* RCB_CHECK_H */
