# Base comum dos kernels int8

Infraestrutura compartilhada pelos benchmarks das operações de CNN (RCB-11). Ela cobre:

- parâmetros por argumento;
- dados determinísticos;
- requantização de referência;
- comparação com um oráculo e checksum;
- linha `RESULT`;
- região de interesse (ROI) marcada com m5ops.

As operações, a quantização e as dimensões estão em [scope.md](scope.md). As instruções personalizadas estão em [custom_instructions.md](custom_instructions.md).

| Parte | Situação |
| --- | --- |
| Headers em [benchmarks/common/](../benchmarks/common/) | Existente |
| Benchmark de exemplo [int8_base_example](../benchmarks/int8_base_example/main.c) | Existente; roda no QEMU e no gem5, nas quatro CPUs |
| ROI separada no `stats.txt` | Existente; verificado nas CPUs atomic, timing, minor e o3 |
| Kernels das sete operações | Existente (RCB-12, [kernels.md](kernels.md)) |
| Leitura automática do bloco da ROI | Existente (RCB-16): `riscvcnnbench stats`, ver [results.md](results.md#métricas) |

## Roteiro de um benchmark

Todo benchmark de operação segue os mesmos cinco passos, como no `int8_base_example`:

```c
#include "../common/rcb_bench.h"

int main(int argc, char **argv)
{
    /* 1. Parâmetros: nome, padrão, mínimo, máximo, múltiplo. */
    struct rcb_param params[] = {{"K", 64, 8, 1 << 16, 8}, {"R", 1, 1, 1 << 16, 1}};
    rcb_parse_params(argc, argv, params, 2);

    /* 2. Dados determinísticos, gerados fora da ROI. */
    int8_t *x = rcb_alloc(n, "x");
    struct rcb_rng rng = rcb_rng_init(SEED);
    rcb_fill_i8(x, n, &rng, -128, 127);
    rcb_dataset_i8(x, n, RCB_INPUT); /* conjunto extremo, se RCB_DATA != 0 */

    /* 3. Kernel dentro da ROI, R vezes. */
    rcb_roi_begin();
    for (long r = 0; r < repeat; ++r)
        kernel(...);
    rcb_roi_end();

    /* 4. Oráculo e comparação fora da ROI. */
    oracle(...);
    size_t mismatches = rcb_compare_i8(y, y_ref, n, "y");

    /* 5. RESULT e código de saída. */
    return rcb_finish("nome", params, 2, rcb_checksum(y, n), mismatches);
}
```

Cada parte tem um papel fixo:

- **Kernel:** a implementação medida. Nas operações há um arquivo por variante (`kernel_ref.c`, `kernel_custom.c`, `kernel_rvv.c`, RCB-12 e RCB-14), escolhido pelo Makefile; o resto do programa é o mesmo.
- **Oráculo:** a versão mais simples possível da operação, que nunca muda entre variantes.
- **Comparação:** como todas as variantes são comparadas com o mesmo oráculo e geram os mesmos dados, a equivalência byte a byte da RCB-15 se reduz a todas passarem e terem o mesmo checksum.

O `Makefile` segue o padrão do projeto, com `FLAGS ?= -O2` e as flags obrigatórias. Ele também depende dos headers comuns:

```make
$(OUT): main.c $(wildcard ../common/*.h) FORCE
```

## Headers

Todos são só headers, com funções `static inline`. Basta incluir `rcb_bench.h`.

| Header | Oferece |
| --- | --- |
| `rcb_args.h` | `struct rcb_param` e `rcb_parse_params` |
| `rcb_data.h` | `struct rcb_rng`, `rcb_rng_init`, `rcb_rng_next`, `rcb_rng_range`, `rcb_fill_i8`, `rcb_fill_i32`, `rcb_alloc`, `RCB_ALIGN`; conjuntos de dados `RCB_DATA`, `RCB_DATA_NAME`, `rcb_dataset_i8`, `rcb_dataset_i32` |
| `rcb_quant.h` | `struct rcb_qparams`, `rcb_requantize`, `rcb_qparams_from_scale` |
| `rcb_check.h` | `rcb_compare_i8`, `rcb_checksum`, `rcb_finish`, `RCB_VARIANT` |
| `rcb_roi.h` | `rcb_roi_begin`, `rcb_roi_end` |
| `cnn_insn.h` | Instruções personalizadas, da RCB-10, e `cnn_ld8`/`cnn_sd8` (8 bytes alinhados com um `ld`/`sd`). Não faz parte de `rcb_bench.h` |
| `rcb_rvv.h` | Blocos da variante RVV (RCB-14): `rcb_rvv_zero`, `rcb_rvv_mac`, `rcb_rvv_reduce`, `rcb_rvv_requant_relu`. Só compila com `-march=rv64gcv`; não faz parte de `rcb_bench.h` |
| `rcb_ops.h` | Oráculos das operações (RCB-12). Não faz parte de `rcb_bench.h` |

### Parâmetros

Os parâmetros são posicionais e opcionais, na ordem da tabela `params`. Os ausentes ficam com o padrão. Cada um tem faixa e múltiplo; por exemplo, `K` precisa ser múltiplo de 8 para as instruções personalizadas. Qualquer erro encerra com código 2 e uma linha no stderr:

```
ERRO: K deve ser múltiplo de 8: 10
ERRO: M deve estar entre 1 e 4096: 0
ERRO: M deve ser um inteiro: x
ERRO: argumentos demais: 4 (máximo 3)
```

Dimensões e repetições vêm sempre daqui, nunca de constantes espalhadas pelo código. A semente é uma constante `SEED` por benchmark, para que os dados de uma operação nunca mudem.

### Dados determinísticos

- **Gerador:** `splitmix64`, com só aritmética inteira de 64 bits. A mesma semente dá os mesmos tensores no QEMU, no gem5 e em qualquer variante.
- **Preenchimento:** `rcb_fill_i8` e `rcb_fill_i32` sorteiam uniformemente numa faixa fechada `[lo, hi]`. O padrão para ativações e pesos é `[-128, 127]`, para incluir os extremos.
- **Ordem:** os tensores são sorteados sempre na mesma ordem, a do código.
- **Conjuntos extremos (RCB-15):** depois do sorteio, `rcb_dataset_i8(buf, n, papel)` e `rcb_dataset_i32(buf, n, lo, hi)` sobrescrevem cada tensor conforme o conjunto escolhido na compilação com `-DRCB_DATA=<n>`. Com o padrão, `RCB_DATA=0`, essas chamadas não fazem nada. O papel é `RCB_INPUT`, `RCB_WEIGHT` ou `RCB_BIAS`, este último também para a entrada int32 da requantização.

  | `RCB_DATA` | Nome (`data=`) | Entradas | Pesos | Bias / int32 | Efeito |
  | --- | --- | --- | --- | --- | --- |
  | 0 | `random` | sorteadas | sorteados | sorteados | Padrão; usado nas medições |
  | 1 | `satpos` | −128 | −128 | `hi` da faixa | Cada produto vale +16384; toda saída requantizada satura em 127 |
  | 2 | `satneg` | −128 | 127 | `lo` da faixa | Cada produto vale −16256; o ReLU zera toda saída |

  Os extremos ficam dentro das faixas do sorteio, então os limites de acumulação de [custom_instructions.md](custom_instructions.md) continuam valendo. No max pooling, os dois conjuntos põem −128 em toda a entrada, e a saída também é −128: isso confere a comparação com sinal. Pelo YAML, o conjunto entra em `compiler.flags`, por exemplo `[-O2, -DRCB_DATA=1]`.
- **Alocação:** `rcb_alloc` devolve memória zerada e alinhada a 64 bytes, o que atende o requisito de 8 bytes das instruções personalizadas e coincide com a linha de cache. Sem memória, o programa encerra com código 2.

### Quantização

- **`rcb_requantize(acc, q, relu)`:** é a fórmula de [scope.md](scope.md#quantização) e o oráculo da requantização. O benchmark `cnn_insn_semantics` confere que ela coincide com o modelo do `cnn.rqnt` nos casos de teste.
- **`rcb_qparams_from_scale(M)`:** converte uma escala real `M = S_x·S_w/S_y` em `{M0, s}`, com `M0` em `[2^30, 2^31)`. Aceita `2^-32 ≤ M < 1` e encerra com código 2 fora disso. Usa só multiplicações por 2, que são exatas, e não depende da libm. Deve ser chamada fora da ROI.

### Verificação e resultado

- **Comparação:** `rcb_compare_i8` compara a saída com a do oráculo elemento a elemento, devolve o número de diferenças e mostra a primeira no stderr:

  ```
  ERRO: y[8] = 13, oráculo = 12
  ```

- **Checksum:** `rcb_checksum` é o FNV-1a de 64 bits sobre os bytes da saída.
- **Resultado:** `rcb_finish` imprime a linha abaixo e devolve o código de saída.

  ```
  RESULT bench=<nome> variant=<ref|custom|rvv> data=<random|satpos|satneg> <P>=<valor>... checksum=0x<16 hex> mismatches=<n>
  ```

`variant` vem de `RCB_VARIANT_NAME`, que o Makefile das operações define a partir de `VARIANT` (o `benchmark.variant` do YAML). Assim a variante `custom` compilada com o modelo em C (`CNN_INSN=model`) também imprime `custom`. Sem essa macro, como nos benchmarks com Makefile próprio, `variant` é deduzida das flags:

| Flag | `variant` |
| --- | --- |
| `-DRCB_VARIANT_NAME='"<v>"'` | `<v>` |
| `-DCNN_INSN_HW` | `custom` |
| `-march=rv64gcv`, que define `__riscv_vector` | `rvv` |
| nenhuma das anteriores | `ref` |

| Código de saída | Significado |
| --- | --- |
| 0 | Saída igual à do oráculo |
| 1 | Alguma diferença |
| 2 | Argumento inválido ou memória insuficiente |

## Região de interesse

```c
rcb_roi_begin();   /* m5_work_begin(0, 0) e m5_reset_stats(0, 0): zera as estatísticas */
kernel(...);
rcb_roi_end();     /* m5_dump_reset_stats(0, 0): grava um bloco e zera de novo */
```

No gem5, o `stats.txt` fica com dois blocos, cada um iniciado por `---------- Begin Simulation Statistics ----------`:

| Bloco | Cobre |
| --- | --- |
| 1 | Só a ROI: o kernel com as suas `R` repetições |
| 2 | Do fim da ROI ao fim do programa: oráculo, comparação, impressão e saída |

A inicialização, que inclui a carga do programa, a alocação e o sorteio dos dados, fica antes do `m5_reset_stats` e não aparece em nenhum bloco. O parser (RCB-16) lê o bloco 1 e recusa um `stats.txt` com outro número de blocos.

O `m5_work_begin`, logo antes do `m5_reset_stats` e portanto fora da ROI, avisa a configuração do gem5 que a ROI vai começar. Com `benchmark.cache_state: cold`, o gem5 para nele, esvazia as caches e continua; com `warm`, o padrão, ele não faz nada ([scenarios.md](scenarios.md#estado-das-caches-no-início-da-roi)). O mesmo binário serve aos dois estados.

### Como funciona

- **Codificação:** as m5ops do RISC-V são instruções no opcode custom-3 (`0x7B`), com a função nos bits 31:25 e os argumentos em `a0` e `a1`. Foi conferido em `util/m5/src/abi/riscv/m5op.S` e `include/gem5/asm/generic/m5ops.h`. O header emite as palavras direto com `.word`, sem precisar da `libm5`:

  | m5op | Função | Palavra |
  | --- | --- | --- |
  | `m5_reset_stats` | `0x40` | `0x8000007b` |
  | `m5_dump_reset_stats` | `0x42` | `0x8400007b` |
  | `m5_work_begin` | `0x5a` | `0xb400007b` |

- **Barreira do compilador:** o `asm volatile` com o clobber `"memory"` impede que o compilador mova acessos à memória para dentro ou para fora da ROI. O kernel precisa escrever o resultado na memória. Um cálculo que só fique em registradores poderia ser movido.
- **Custo fixo:** com `K=64` e `M=16`, a ROI tem 7.458 instruções com `R=1` e 14.903 com `R=2`. O custo fixo fica em torno de 13 instruções, desprezível frente aos kernels do escopo.

### Fora do gem5

No QEMU, ou em hardware sem gem5, as m5ops são instruções ilegais. Na primeira chamada, `rcb_roi_begin` instala um tratador de SIGILL que funciona assim:

- **Se a palavra é uma m5op** (opcode `0x7B` e demais campos zero), o tratador avança o `pc` em 4 e registra que a ROI não foi marcada. No fim, `rcb_roi_end` imprime no stderr:

  ```
  AVISO: m5ops indisponíveis (fora do gem5); a região de interesse não foi marcada
  ```

- **Qualquer outra instrução ilegal** faz o tratador restaurar o comportamento padrão. O programa termina com SIGILL como antes, e uma instrução personalizada no QEMU continua sendo detectada.

Assim, o mesmo binário roda no QEMU e no gem5, com os mesmos dados e o mesmo checksum.

### Cuidados

- **Caches aquecidas, por padrão.** A ROI começa com as caches no estado deixado pela inicialização, que acabou de escrever os tensores. Nos tamanhos S, com L1 de 32KiB, os dados já estão na L1. O código do kernel, que só roda na ROI, não está. A alternativa é `benchmark.cache_state: cold`, e a escolha está justificada em [scenarios.md](scenarios.md#estado-das-caches-no-início-da-roi) (RCB-18).
- **Repetições.** Com `R > 1`, as repetições depois da primeira encontram as caches aquecidas pela anterior. Métricas por execução do kernel exigem dividir o bloco por `R`, o que fica para a RCB-17.
- **Um bloco de ROI por execução.** Mais regiões por programa exigiriam outro par `rcb_roi_begin`/`rcb_roi_end`, e o parser teria que saber quantas são. Hoje ele espera 2 blocos em todo benchmark cujo fonte chama `rcb_roi_begin`.

## Benchmark de exemplo

`int8_base_example [K] [M] [R]` calcula `M` saídas `y[m] = sat8(ReLU(requant(bias[m] + Σ_k x[k]·w[m][k])))`.

- **Parâmetros:** `K` é múltiplo de 8, com padrão `64 16 1`.
- **Escala:** `1/(16K)`.
- **Não é uma das sete operações do escopo:** existe para exercitar a base.
- **Erro proposital:** com `-DRCB_INJECT_ERROR`, o kernel erra uma saída de propósito, para testar a verificação.

```bash
# Dentro do container
uv run riscvcnnbench run experiments/int8_base_example.yaml
make -C benchmarks/int8_base_example && qemu-riscv64 build/benchmarks/int8_base_example 128 32 2
```

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_kernel_base_e2e.py::test_example_runs_on_qemu_without_m5ops` | O exemplo roda no QEMU, passa e mostra o aviso da ROI | `pytest -m e2e` |
| `tests/test_kernel_base_e2e.py::test_roi_isolates_the_kernel_and_data_is_deterministic` | O `stats.txt` tem 2 blocos; dobrar `R` dobra só o bloco da ROI; o checksum é igual no QEMU e no gem5 | `pytest -m e2e` |
| `tests/test_kernel_base_e2e.py::test_wrong_kernel_is_detected` | Com o erro proposital, sai com 1 e mostra a diferença | `pytest -m e2e` |
| `tests/test_kernel_base_e2e.py::test_invalid_arguments_exit_with_2` | As mensagens de argumento inválido e o código 2 | `pytest -m e2e` |
| `tests/test_kernel_base_e2e.py::test_other_illegal_instructions_still_crash` | O tratador de SIGILL não esconde instruções ilegais que não são m5ops | `pytest -m e2e` |
| `cnn_insn_semantics` | `rcb_requantize` coincide com o modelo do `cnn.rqnt` | `pytest -m e2e`, pelos testes da RCB-10 |

## Como acrescentar uma operação

As sete operações da RCB-12 seguem estes passos ([kernels.md](kernels.md)).

1. Crie `benchmarks/<operação>/` com `main.c`, `kernel.h`, `kernel_ref.c` e um `Makefile` de duas linhas (`NAME := <operação>` e `include ../common/kernel.mk`). Oráculos novos vão em `benchmarks/common/rcb_ops.h`.
2. Siga o roteiro: parâmetros, dados com uma `SEED` própria (e `rcb_dataset_*` para cada tensor), kernel na ROI, oráculo e `rcb_finish`.
3. Use dimensões múltiplas de 8 na dimensão contígua e aloque tudo com `rcb_alloc`.
4. Acrescente `kernel_custom.c` e `kernel_rvv.c` (RCB-14), um YAML em `experiments/` e a operação em `OPS` de `tests/test_kernels_e2e.py` (e o tamanho da saída em `tests/test_validation.py`), para que ela entre no e2e e na validação.
