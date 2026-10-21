/*
 * Região de interesse (ROI) com m5ops do gem5 (RCB-11).
 *
 *     rcb_roi_begin();   // m5_reset_stats: zera as estatísticas
 *     kernel(...);       // só isto entra no primeiro bloco do stats.txt
 *     rcb_roi_end();     // m5_dump_reset_stats: grava o bloco e zera de novo
 *
 * No gem5, o stats.txt fica com dois blocos: o primeiro só com a ROI e o
 * segundo do fim da ROI até o fim do programa. A inicialização antes da ROI
 * não aparece em nenhum bloco.
 *
 * As m5ops do RISC-V usam o opcode custom-3 (0x7B) com a função nos bits
 * 31:25 e argumentos em a0/a1. Fora do gem5 (por exemplo, no QEMU) elas são
 * instruções ilegais: um tratador de SIGILL reconhece só essas palavras, pula
 * a instrução e registra que a ROI não foi marcada. Qualquer outra instrução
 * ilegal continua encerrando o programa.
 */
#ifndef RCB_ROI_H
#define RCB_ROI_H

#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <ucontext.h>

#define RCB_M5OP_OPCODE 0x7bu
#define RCB_M5OP_RESET_STATS 0x40u /* include/gem5/asm/generic/m5ops.h */
#define RCB_M5OP_DUMP_RESET_STATS 0x42u

/* 1 quando uma m5op foi pulada por não haver gem5. */
static volatile sig_atomic_t rcb_m5ops_missing = 0;

static inline void rcb_on_sigill(int sig, siginfo_t *info, void *context)
{
    (void)sig;
    (void)info;
    ucontext_t *uc = context;
    /* No RISC-V Linux, __gregs[0] é o pc. */
    uint32_t insn;
    memcpy(&insn, (const void *)uc->uc_mcontext.__gregs[0], sizeof(insn));

    if ((insn & 0x01ffffffu) == RCB_M5OP_OPCODE) {
        rcb_m5ops_missing = 1;
        uc->uc_mcontext.__gregs[0] += 4;
        return;
    }
    /* Não é m5op: volta ao comportamento padrão; a instrução é reexecutada e
     * o processo termina com SIGILL, como sem o tratador. */
    signal(SIGILL, SIG_DFL);
}

static inline void rcb_install_sigill_handler(void)
{
    static int installed = 0;
    if (installed) {
        return;
    }
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_sigaction = rcb_on_sigill;
    action.sa_flags = SA_SIGINFO;
    sigemptyset(&action.sa_mask);
    sigaction(SIGILL, &action, NULL);
    installed = 1;
}

/* Palavra da m5op: opcode 0x7B, função nos bits 31:25, demais campos zero. */
#define RCB_M5OP_WORD(func) (RCB_M5OP_OPCODE | ((func) << 25))
#define RCB_STR2(x) #x
#define RCB_STR(x) RCB_STR2(x)

/* m5op com a0 = a1 = 0 (atraso e período zero). "memory" impede que o
 * compilador mova acessos à memória para dentro ou para fora da ROI. */
#define RCB_M5OP(word)                                                               \
    do {                                                                             \
        register uint64_t rcb_a0 __asm__("a0") = 0;                                  \
        register uint64_t rcb_a1 __asm__("a1") = 0;                                  \
        __asm__ volatile(".word " RCB_STR(word) : "+r"(rcb_a0) : "r"(rcb_a1) : "memory"); \
    } while (0)

/* As palavras abaixo vão literais no .word; estas asserções as amarram às
 * funções de m5ops.h. */
_Static_assert(RCB_M5OP_WORD(RCB_M5OP_RESET_STATS) == 0x8000007bu, "m5_reset_stats");
_Static_assert(RCB_M5OP_WORD(RCB_M5OP_DUMP_RESET_STATS) == 0x8400007bu, "m5_dump_reset_stats");

static inline void rcb_roi_begin(void)
{
    rcb_install_sigill_handler();
    RCB_M5OP(0x8000007b); /* RCB_M5OP_WORD(RCB_M5OP_RESET_STATS) */
}

static inline void rcb_roi_end(void)
{
    RCB_M5OP(0x8400007b); /* RCB_M5OP_WORD(RCB_M5OP_DUMP_RESET_STATS) */
    if (rcb_m5ops_missing) {
        fprintf(stderr,
                "AVISO: m5ops indisponíveis (fora do gem5); a região de interesse não foi marcada\n");
    }
}

#endif /* RCB_ROI_H */
