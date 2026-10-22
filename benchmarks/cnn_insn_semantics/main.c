/*
 * Casos de teste de semântica das instruções personalizadas (RCB-10).
 *
 * Cada caso dá os valores de rd (entrada), rs1 e rs2 e o rd esperado. Os casos
 * são os mesmos da tabela em docs/custom_instructions.md; um teste em pytest
 * confere que as duas listas são iguais e recalcula cada valor esperado com um
 * modelo independente em Python.
 *
 * Compilado sem CNN_INSN_HW, confere só o modelo em C e roda no QEMU e no gem5
 * atual. Com -DCNN_INSN_HW, confere também as instruções reais e só roda no
 * gem5 do fork (RCB-13); no gem5 atual a primeira instrução gera
 * "Unknown instruction".
 *
 * Nos casos de requantização, confere também que o oráculo da base comum
 * (rcb_requantize, RCB-11) dá o mesmo resultado.
 *
 * Imprime "RESULT mode=<model|hw> cases=N failures=F" e retorna 0 se não houve
 * falha, 1 caso contrário.
 */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

#include "../common/cnn_insn.h"
#include "../common/rcb_quant.h"

enum cnn_op {
    CNN_OP_DOT8,
    CNN_OP_MAX8,
    CNN_OP_DWMAC,
    CNN_OP_RQNT,
    CNN_OP_RQNT_RELU,
};

struct cnn_case {
    const char *id;
    enum cnn_op op;
    unsigned p; /* só cnn.dwmac */
    uint64_t rd;
    uint64_t rs1;
    uint64_t rs2;
    uint64_t expected;
};

/* Gerado a partir da especificação; mantenha igual à tabela do documento. */
static const struct cnn_case CASES[] = {
    {"dot8-01", CNN_OP_DOT8, 0, 0x0000000000000000, 0x0000000000000000, 0x0000000000000000, 0x0000000000000000},
    {"dot8-02", CNN_OP_DOT8, 0, 0x0000000000000000, 0x0807060504030201, 0x0101010101010101, 0x0000000000000024},
    {"dot8-03", CNN_OP_DOT8, 0, 0x0000000000000000, 0x0101010101010101, 0xffffffffffffffff, 0xfffffffffffffff8},
    {"dot8-04", CNN_OP_DOT8, 0, 0x0000000000000000, 0x8080808080808080, 0x8080808080808080, 0x0000000000020000},
    {"dot8-05", CNN_OP_DOT8, 0, 0x0000000000000000, 0x8080808080808080, 0x7f7f7f7f7f7f7f7f, 0xfffffffffffe0400},
    {"dot8-06", CNN_OP_DOT8, 0, 0x00000000000003e8, 0x0807060504030201, 0x0102030405060708, 0x0000000000000460},
    {"dot8-07", CNN_OP_DOT8, 0, 0x000000007ffffff0, 0x7f7f7f7f7f7f7f7f, 0x7f7f7f7f7f7f7f7f, 0xffffffff8001f7f8},
    {"dot8-08", CNN_OP_DOT8, 0, 0xdeadbeef00000010, 0x0807060504030201, 0x0101010101010101, 0x0000000000000034},
    {"dot8-09", CNN_OP_DOT8, 0, 0x0000000000000000, 0xfc04fd03fe02ff01, 0xf5f50909f9f90505, 0x0000000000000000},
    {"max8-01", CNN_OP_MAX8, 0, 0x0000000000000000, 0x9c64fb05ff007f80, 0x9c64fb05ff007f80, 0x9c64fb05ff007f80},
    {"max8-02", CNN_OP_MAX8, 0, 0x0000000000000000, 0x9c64fb05ff007f80, 0x649c05fb00ff807f, 0x6464050500007f7f},
    {"max8-03", CNN_OP_MAX8, 0, 0x0000000000000000, 0x8080808080808080, 0x8080808080808080, 0x8080808080808080},
    {"max8-04", CNN_OP_MAX8, 0, 0x0000000000000000, 0x9c64fb05ff007f80, 0x0000000000000000, 0x0064000500007f00},
    {"max8-05", CNN_OP_MAX8, 0, 0x0000000000000000, 0x8080808080808080, 0x7f7f7f7f7f7f7f7f, 0x7f7f7f7f7f7f7f7f},
    {"max8-06", CNN_OP_MAX8, 0, 0x0000000000000000, 0x09f807fa05fc03fe, 0x0af908fb06fd02ff, 0x0af908fb06fd03ff},
    {"dwmac-01", CNN_OP_DWMAC, 0, 0x0000000000000000, 0x0000000000008080, 0x0000000000007f80, 0xffffc08000004000},
    {"dwmac-02", CNN_OP_DWMAC, 0, 0x0000000000000000, 0x0807060504030201, 0x0202020202020202, 0x0000000400000002},
    {"dwmac-03", CNN_OP_DWMAC, 1, 0x0000000000000000, 0x0807060504030201, 0x0202020202020202, 0x0000000800000006},
    {"dwmac-04", CNN_OP_DWMAC, 2, 0x0000000000000000, 0x0807060504030201, 0x0202020202020202, 0x0000000c0000000a},
    {"dwmac-05", CNN_OP_DWMAC, 3, 0x0000000000000000, 0x0807060504030201, 0x0202020202020202, 0x000000100000000e},
    {"dwmac-06", CNN_OP_DWMAC, 1, 0x000002bcfffffe0c, 0xf807fa05fc037f80, 0x0101010103fd0101, 0x000002b0fffffe03},
    {"dwmac-07", CNN_OP_DWMAC, 0, 0x00000005ffffffff, 0x0101010101010101, 0x0101010101010101, 0x0000000600000000},
    {"dwmac-08", CNN_OP_DWMAC, 3, 0x800000007fffffff, 0x0101000000000000, 0xff01000000000000, 0x7fffffff80000000},
    {"rqnt-01", CNN_OP_RQNT, 0, 0x0000000000000000, 0x0000000000000064, 0x0000000040000000, 0x0000000000000032},
    {"rqnt-02", CNN_OP_RQNT, 0, 0x0000000000000000, 0x0000000000000065, 0x0000000040000000, 0x0000000000000033},
    {"rqnt-03", CNN_OP_RQNT, 0, 0x0000000000000000, 0xffffffffffffff9b, 0x0000000040000000, 0xffffffffffffffce},
    {"rqnt-04", CNN_OP_RQNT, 0, 0x0000000000000000, 0x00000000000003e8, 0x0000000040000000, 0x000000000000007f},
    {"rqnt-05", CNN_OP_RQNT, 0, 0x0000000000000000, 0xfffffffffffffc18, 0x0000000040000000, 0xffffffffffffff80},
    {"rqnt-06", CNN_OP_RQNT, 0, 0x0000000000000000, 0x00000000000007d0, 0x0000000460000000, 0x000000000000005e},
    {"rqnt-07", CNN_OP_RQNT, 0, 0x0000000000000000, 0xffffffff80000000, 0x000000007fffffff, 0xffffffffffffff80},
    {"rqnt-08", CNN_OP_RQNT, 0, 0x0000000000000000, 0x000000007fffffff, 0x0000001f7fffffff, 0x0000000000000001},
    {"rqnt-09", CNN_OP_RQNT, 0, 0x0000000000000000, 0x1234567800000064, 0x0000000040000000, 0x0000000000000032},
    {"rqnt-10", CNN_OP_RQNT, 0, 0x0000000000000000, 0x0000000000000064, 0xffffffe040000000, 0x0000000000000032},
    {"rqnt-11", CNN_OP_RQNT, 0, 0x0000000000000000, 0x0000000000000000, 0x0000000540000000, 0x0000000000000000},
    {"rqnt.relu-01", CNN_OP_RQNT_RELU, 0, 0x0000000000000000, 0x0000000000000064, 0x0000000040000000, 0x0000000000000032},
    {"rqnt.relu-02", CNN_OP_RQNT_RELU, 0, 0x0000000000000000, 0xffffffffffffff9c, 0x0000000040000000, 0x0000000000000000},
    {"rqnt.relu-03", CNN_OP_RQNT_RELU, 0, 0x0000000000000000, 0x00000000000003e8, 0x0000000040000000, 0x000000000000007f},
    {"rqnt.relu-04", CNN_OP_RQNT_RELU, 0, 0x0000000000000000, 0xffffffffffffffff, 0x0000000040000000, 0x0000000000000000},
    {"rqnt.relu-05", CNN_OP_RQNT_RELU, 0, 0x0000000000000000, 0x0000000000000003, 0x0000000040000000, 0x0000000000000002},
};

static uint64_t run_model(const struct cnn_case *c)
{
    switch (c->op) {
    case CNN_OP_DOT8:
        return (uint64_t)(int64_t)cnn_dot8_model((int32_t)c->rd, c->rs1, c->rs2);
    case CNN_OP_MAX8:
        return cnn_max8_model(c->rs1, c->rs2);
    case CNN_OP_DWMAC:
        return cnn_dwmac_model(c->rd, c->rs1, c->rs2, c->p);
    case CNN_OP_RQNT:
        return (uint64_t)(int64_t)cnn_rqnt_model((int32_t)c->rs1, c->rs2, 0);
    case CNN_OP_RQNT_RELU:
        return (uint64_t)(int64_t)cnn_rqnt_model((int32_t)c->rs1, c->rs2, 1);
    }
    return 0;
}

#ifdef CNN_INSN_HW
/*
 * Executa a instrução real. dot8 e rqnt recebem int32_t: a ABI do RV64 mantém
 * valores de 32 bits estendidos com sinal no registrador, então os bits 63:32
 * dos casos que testam "bits ignorados" são passados com asm direto.
 */
static uint64_t run_hw(const struct cnn_case *c)
{
    uint64_t rd = c->rd;
    uint64_t out;

    switch (c->op) {
    case CNN_OP_DOT8:
#ifdef CNN_INSN_INJECT_ERROR
        /* Teste negativo (RCB-15): simula um decodificador que executa outra
         * instrução real, cnn.dwmac p=0, no lugar do cnn.dot8. Os casos
         * dot8-* devem falhar. */
        __asm__ volatile(".insn r CUSTOM_0, 0, 0x01, %0, %1, %2"
                         : "+r"(rd)
                         : "r"(c->rs1), "r"(c->rs2));
#else
        __asm__ volatile(".insn r CUSTOM_0, 0, 0x00, %0, %1, %2"
                         : "+r"(rd)
                         : "r"(c->rs1), "r"(c->rs2));
#endif
        return rd;
    case CNN_OP_MAX8:
        return cnn_max8(c->rs1, c->rs2);
    case CNN_OP_DWMAC:
        switch (c->p) {
        case 0:
            CNN_DWMAC(rd, c->rs1, c->rs2, 0);
            break;
        case 1:
            CNN_DWMAC(rd, c->rs1, c->rs2, 1);
            break;
        case 2:
            CNN_DWMAC(rd, c->rs1, c->rs2, 2);
            break;
        default:
            CNN_DWMAC(rd, c->rs1, c->rs2, 3);
            break;
        }
        return rd;
    case CNN_OP_RQNT:
        __asm__ volatile(".insn r CUSTOM_1, 0, 0x00, %0, %1, %2"
                         : "=r"(out)
                         : "r"(c->rs1), "r"(c->rs2));
        return out;
    case CNN_OP_RQNT_RELU:
        __asm__ volatile(".insn r CUSTOM_1, 0, 0x01, %0, %1, %2"
                         : "=r"(out)
                         : "r"(c->rs1), "r"(c->rs2));
        return out;
    }
    return 0;
}
#endif

/* Oráculo da base comum, só para os casos de requantização. */
static int check_oracle(const struct cnn_case *c)
{
    if (c->op != CNN_OP_RQNT && c->op != CNN_OP_RQNT_RELU) {
        return 0;
    }
    struct rcb_qparams q = {(int32_t)(uint32_t)c->rs2, (unsigned)(c->rs2 >> 32) & 31u};
    int32_t y = rcb_requantize((int32_t)c->rs1, q, c->op == CNN_OP_RQNT_RELU);
    return (uint64_t)(int64_t)y != c->expected;
}

static int check(const char *what, const struct cnn_case *c, uint64_t got)
{
    if (got == c->expected) {
        return 0;
    }
    fprintf(stderr, "FALHA %s %s: esperado 0x%016" PRIx64 ", obtido 0x%016" PRIx64 "\n",
            c->id, what, c->expected, got);
    return 1;
}

int main(void)
{
    unsigned n = sizeof(CASES) / sizeof(CASES[0]);
    unsigned failures = 0;

    for (unsigned i = 0; i < n; ++i) {
        failures += check("modelo", &CASES[i], run_model(&CASES[i]));
        if (check_oracle(&CASES[i])) {
            fprintf(stderr, "FALHA %s: rcb_requantize difere do esperado\n", CASES[i].id);
            ++failures;
        }
#ifdef CNN_INSN_HW
        failures += check("instrução", &CASES[i], run_hw(&CASES[i]));
#endif
    }

#ifdef CNN_INSN_HW
    const char *mode = "hw";
#else
    const char *mode = "model";
#endif
    printf("RESULT mode=%s cases=%u failures=%u\n", mode, n, failures);
    return failures == 0 ? 0 : 1;
}
