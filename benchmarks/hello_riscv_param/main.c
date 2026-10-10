/*
 * Variante parametrizável do hello_riscv.
 *
 * Soma os elementos de um vetor de N inteiros, repetindo R vezes:
 *
 *     hello_riscv_param [N] [R]
 *
 * N controla quanta memória é percorrida (N * 4 bytes) e R quantas vezes ela
 * é reutilizada, o que permite observar o efeito de caches e memória nas
 * estatísticas do gem5. Padrão: N=1024, R=1.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static long parse_arg(const char *text, const char *name)
{
    char *end = NULL;
    long value = strtol(text, &end, 10);

    if (*text == '\0' || *end != '\0' || value <= 0) {
        fprintf(stderr, "ERRO: %s deve ser um inteiro positivo: %s\n", name, text);
        exit(2);
    }
    return value;
}

int main(int argc, char **argv)
{
    long n = argc > 1 ? parse_arg(argv[1], "N") : 1024;
    long repeat = argc > 2 ? parse_arg(argv[2], "R") : 1;

    int32_t *values = malloc((size_t)n * sizeof(*values));
    if (values == NULL) {
        fprintf(stderr, "ERRO: memória insuficiente para N=%ld\n", n);
        return 2;
    }

    for (long i = 0; i < n; ++i) {
        values[i] = (int32_t)i;
    }

    volatile int64_t sum = 0;
    for (long r = 0; r < repeat; ++r) {
        for (long i = 0; i < n; ++i) {
            sum += values[i];
        }
    }

    int64_t expected = (int64_t)repeat * n * (n - 1) / 2;
    printf("RESULT n=%ld repeat=%ld sum=%lld\n", n, repeat, (long long)sum);

    free(values);
    return sum == expected ? 0 : 1;
}
