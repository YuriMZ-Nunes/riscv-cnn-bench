# Kernels das operações

Benchmarks das sete operações de [scope.md](scope.md), construídos sobre a base comum de [kernel_base.md](kernel_base.md) (RCB-12).

| Parte | Situação |
| --- | --- |
| Kernels de referência escalar (`kernel_ref.c`) das sete operações | Existente; passam no QEMU (S e L) e no gem5 (S e L, atomic) |
| Oráculos em `benchmarks/common/rcb_ops.h` | Existente |
| YAMLs `experiments/<operação>_{s,l}.yaml` | Existente; CPU atomic |
| Variantes personalizada e RVV | Planejado (RCB-14) |
| Equivalência entre variantes | Planejado (RCB-15) |

## Operações

| Benchmark | Argumentos | S (padrão) | L | Pesos | Escala | `SEED` |
| --- | --- | --- | --- | --- | --- | --- |
| `conv3x3_direct` | `H W Cin Cout R` | `16 16 8 16` | `32 32 16 32` | `[Cout][3][3][Cin]` | 1/1000 | `0xc0de3301` |
| `conv3x3_im2col` | `H W Cin Cout R` | `16 16 8 16` | `32 32 16 32` | `[Cout][3][3][Cin]` | 1/1000 | `0xc0de3301` |
| `depthwise3x3` | `H W C R` | `16 16 32` | `32 32 64` | `[3][3][C]` | 1/300 | `0xc0de3302` |
| `pointwise1x1` | `H W Cin Cout R` | `16 16 32 32` | `32 32 64 64` | `[Cout][Cin]` | 1/750 | `0xc0de3303` |
| `maxpool2x2` | `H W C R` | `32 32 16` | `64 64 32` | — | — | `0xc0de3304` |
| `requant_relu` | `N R` | `4096` | `32768` | — | 1/200 | `0xc0de3305` |
| `fc` | `In Out R` | `512 32` | `1024 512` | `[Out][In]` | 1/3000 | `0xc0de3306` |

Regras comuns:

- **Layout:** ativações em NHWC, sem a dimensão N. Os pesos deixam o canal contíguo: `Cin` na conv e na pointwise, `In` na FC e `C` por tap na depthwise.
- **Convoluções:** stride 1, padding 1 com zero e saída do mesmo tamanho da entrada.
- **Pooling:** stride 2. `H` e `W` devem ser pares.
- **Quantização:** entradas e pesos int8 e bias int32. A saída das convoluções, da pointwise e da FC é requantizada com ReLU por `rcb_requantize`, com a escala da tabela convertida por `rcb_qparams_from_scale`. O max pooling não requantiza, porque usa a mesma escala na entrada e na saída.
- **Dimensões contíguas múltiplas de 8:** valem para `Cin`, `Cout`, `C`, `N`, `In` e `Out`. Os parâmetros também têm limites para que o acumulador int32 não transborde.
- **Mesma camada:** `conv3x3_direct` e `conv3x3_im2col` usam a mesma `SEED` e a mesma escala, então devem dar o mesmo checksum. Um teste e2e confere isso.

Dados sorteados pela base:

| Tensor | Faixa |
| --- | --- |
| Ativações e pesos | `[-128, 127]` |
| Bias | `[-8192, 8192]` |
| Entrada int32 da `requant_relu` | `[-32768, 32767]` |

As escalas foram escolhidas para espalhar as saídas na faixa int8:

| Operação | Saídas zero (S / L) | Saídas saturadas em 127 (S / L) |
| --- | --- | --- |
| `conv3x3_direct`, `conv3x3_im2col` | 51% / 50% | 0,3% / 2,7% |
| `depthwise3x3` | 54% / 50% | 0,7% / 1,2% |
| `pointwise1x1` | 54% / 50% | 0,1% / 1,5% |
| `requant_relu` | 50% / 50% | 10,6% / 11,2% |
| `fc` | 47% / 52% | 0% / 0,8% |

Os zeros vêm da ReLU. A distribuição foi medida em 20/10/2026 com um binário de depuração fora do repositório.

## Estrutura de um benchmark

```
benchmarks/<operação>/
├── Makefile       # NAME := <operação>; include ../common/kernel.mk
├── main.c         # parâmetros, dados, ROI, oráculo, verificação, RESULT
├── kernel.h       # assinatura do kernel
└── kernel_ref.c   # kernel de referência escalar
```

- **`main.c`:** segue o roteiro da base: parâmetros, dados, kernel `R` vezes na ROI, oráculo, `rcb_compare_i8` e `rcb_finish`. É o mesmo para todas as variantes.
- **`kernel_ref.c`:** o código medido, compilado em separado do `main.c`. Assim o compilador não move o kernel para fora da ROI nem elimina repetições.
- **`benchmarks/common/kernel.mk`:** concentra as regras de build: `FLAGS ?= -O2`, as flags obrigatórias com `-march=rv64gc`, `SRCS := main.c kernel_ref.c` e a dependência dos headers comuns.
- **Variantes (RCB-14):** acrescentam `kernel_custom.c` e `kernel_rvv.c` com a mesma assinatura, e o `kernel.mk` escolhe o arquivo e o `-march` pela variante.

Com `-DRCB_INJECT_ERROR`, cada kernel erra `y[0]` de propósito, para o teste negativo.

## Kernels de referência

C portátil, compilado com `-O2 -march=rv64gc`, sem intrínsecos e sem otimização à mão além do básico:

| Kernel | Ordem dos laços | Detalhes |
| --- | --- | --- |
| `conv3x3_direct` | `oh, ow, co, kh, kw, ci` | Faixa de taps válidos calculada fora do laço interno, então o padding não custa instruções; acumulador int32 em registrador |
| `conv3x3_im2col` | montagem: `oh, ow, kh, kw, ci`; GEMM: `p, co, k` | Buffer `col[(H·W)][9·Cin]` alocado fora da ROI e montado dentro dela, com zeros no padding; a GEMM tem laço interno contíguo de `9·Cin` |
| `depthwise3x3` | `oh, ow, c, kh, kw` | Taps no laço interno, por canal; acessos com passo `C` |
| `pointwise1x1` | `p, co, ci` | Produto escalar contíguo sobre `Cin` |
| `maxpool2x2` | `oh, ow, ch` | Três comparações por saída |
| `requant_relu` | `i` | `rcb_requantize` por elemento |
| `fc` | `o, i` | Produto escalar contíguo sobre `In` |

## Oráculos

`benchmarks/common/rcb_ops.h` tem um oráculo por operação. Os oráculos seguem quatro regras:

- os laços estão na ordem da definição matemática;
- a acumulação é em int64;
- o teste de borda é feito por tap, e um tap no padding é pulado;
- a requantização usa `rcb_requantize`.

Os oráculos não mudam entre variantes, e a conv direta e a im2col compartilham o mesmo. Eles rodam fora da ROI, mas também são simulados. Uma versão anterior do oráculo da convolução, com o teste de borda dentro do laço interno, custava cerca de 3 vezes o kernel.

## Instruções medidas

`simInsts` dos dois blocos do `stats.txt`, na variante de referência, medidos no gem5 atomic em 20/10/2026. Os valores são a contagem da referência, não resultados de desempenho. O tempo de host inclui build, inicialização e saída do gem5.

| Operação | Tamanho | MACs (ou elementos) | ROI | Instruções por MAC | Depois da ROI | Host |
| --- | --- | --- | --- | --- | --- | --- |
| `conv3x3_direct` | S | 294.912 | 2.499.690 | 8,48 | 3.074.319 | 9,5 s |
| | L | 4.718.592 | 36.586.544 | 7,75 | 41.190.187 | 66,8 s |
| `conv3x3_im2col` | S | 294.912 | 2.324.694 | 7,88 | 3.074.318 | 9,1 s |
| | L | 4.718.592 | 34.938.815 | 7,40 | 41.190.123 | 60,0 s |
| `depthwise3x3` | S | 73.728 | 975.113 | 13,23 | 1.745.172 | 4,8 s |
| | L | 589.824 | 7.992.565 | 13,55 | 14.054.880 | 20,3 s |
| `pointwise1x1` | S | 262.144 | 1.976.613 | 7,54 | 2.111.782 | 6,2 s |
| | L | 4.194.304 | 30.480.778 | 7,27 | 31.476.107 | 54,7 s |
| `maxpool2x2` | S | 16.384 elementos de entrada | 113.898 | 6,95 por elemento | 142.733 | 3,4 s |
| | L | 131.072 elementos de entrada | 898.931 | 6,86 por elemento | 1.046.502 | 5,6 s |
| `requant_relu` | S | 4.096 elementos | 49.182 | 12,01 por elemento | 106.425 | 2,9 s |
| | L | 32.768 elementos | 393.246 | 12,00 por elemento | 788.350 | 4,2 s |
| `fc` | S | 16.384 | 115.270 | 7,04 | 125.197 | 3,0 s |
| | L | 524.288 | 3.678.746 | 7,02 | 3.694.922 | 14,8 s |

Os MACs da tabela são os **nominais** de `scope.md`, que contam os 9 taps de cada saída. Nas bordas, os kernels de convolução e depthwise não executam os taps no padding. Os MACs efetivos são `(3H-2)(3W-2)·Cin·Cout` na conv, ou `·C` na depthwise:

| Tamanho | MACs efetivos ÷ nominais | Conv: instruções por MAC efetivo | Depthwise: instruções por MAC efetivo |
| --- | --- | --- | --- |
| S | 91,8% | 9,23 | 14,40 |
| L | 95,9% | 8,09 | 14,13 |

As métricas por MAC da RCB-17 precisam declarar qual das duas definições usam.

A estimativa de tempo da campanha em [scope.md](scope.md#estimativa-de-tempo-de-simulação) foi refeita com esses valores.

Para reproduzir uma linha, dentro do container:

```bash
uv run riscvcnnbench run experiments/conv3x3_direct_s.yaml
grep -E '^simInsts ' results/conv3x3_direct_s/<run_id>/gem5/stats.txt   # 1ª linha = ROI
```

## Testes

`tests/test_kernels_e2e.py`, executado com `pytest -m e2e`:

| Teste | Confere |
| --- | --- |
| `test_op_passes_on_qemu` | As sete operações em S e L passam no QEMU (`mismatches=0`) |
| `test_op_s_on_gem5_matches_qemu` | As sete em S rodam pelo `riscvcnnbench run` no gem5, com 2 blocos no `stats.txt` e o mesmo checksum do QEMU |
| `test_direct_and_im2col_compute_the_same_layer` | A conv direta e a im2col dão o mesmo checksum em S e L |
| `test_wrong_kernel_is_detected` | Com `-DRCB_INJECT_ERROR`, as sete saem com 1 e mostram a diferença |
| `test_invalid_arguments_exit_with_2` | Mensagens de argumento inválido e código 2 |

Os tamanhos L no gem5 não entram no e2e, pelo tempo de simulação. Eles foram executados uma vez para a tabela acima.

## Limites

- **Qualidade da referência.** O ganho das variantes é medido contra esta referência. Outra versão do GCC ou outro nível de otimização mudam as contagens; a proveniência de cada execução registra a toolchain.
- **Oráculo simulado.** A verificação custa cerca de tanto quanto o kernel no gem5. A forma de reduzir isso está em [scope.md](scope.md#estimativa-de-tempo-de-simulação).
- **Caches no início da ROI.** A ROI começa com as caches aquecidas pela inicialização ([kernel_base.md](kernel_base.md#cuidados)), e a decisão fica para a RCB-18.
- **Erro comum.** Kernel e oráculo compartilham `rcb_requantize`. A fórmula é conferida pelos 39 casos de [custom_instructions.md](custom_instructions.md).
