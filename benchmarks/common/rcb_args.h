/*
 * Parâmetros posicionais com padrão, faixa e múltiplo (RCB-11).
 *
 *     struct rcb_param params[] = {
 *         {"K", 64, 8, 4096, 8},   // nome, padrão, mínimo, máximo, múltiplo
 *         {"R", 1, 1, 1000, 1},
 *     };
 *     rcb_parse_params(argc, argv, params, 2);
 *
 * Argumento inválido encerra com código 2 e uma mensagem no stderr.
 */
#ifndef RCB_ARGS_H
#define RCB_ARGS_H

#include <stdio.h>
#include <stdlib.h>

struct rcb_param {
    const char *name;
    long value; /* padrão; recebe o argumento, se houver */
    long min;
    long max;
    long multiple; /* 1 aceita qualquer valor */
};

static inline void rcb_usage_error(const struct rcb_param *params, int count)
{
    fprintf(stderr, "uso: programa");
    for (int i = 0; i < count; ++i) {
        fprintf(stderr, " [%s]", params[i].name);
    }
    fprintf(stderr, "\n");
    exit(2);
}

static inline void rcb_parse_params(int argc, char **argv, struct rcb_param *params, int count)
{
    if (argc - 1 > count) {
        fprintf(stderr, "ERRO: argumentos demais: %d (máximo %d)\n", argc - 1, count);
        rcb_usage_error(params, count);
    }
    for (int i = 0; i < argc - 1; ++i) {
        struct rcb_param *p = &params[i];
        const char *text = argv[i + 1];
        char *end = NULL;
        long value = strtol(text, &end, 10);

        if (*text == '\0' || *end != '\0') {
            fprintf(stderr, "ERRO: %s deve ser um inteiro: %s\n", p->name, text);
            exit(2);
        }
        if (value < p->min || value > p->max) {
            fprintf(stderr, "ERRO: %s deve estar entre %ld e %ld: %ld\n", p->name, p->min, p->max,
                    value);
            exit(2);
        }
        if (value % p->multiple != 0) {
            fprintf(stderr, "ERRO: %s deve ser múltiplo de %ld: %ld\n", p->name, p->multiple, value);
            exit(2);
        }
        p->value = value;
    }
}

#endif /* RCB_ARGS_H */
