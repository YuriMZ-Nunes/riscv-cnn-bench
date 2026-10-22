# Kernels das operações

Benchmarks das sete operações de [scope.md](scope.md), construídos sobre a base comum de [kernel_base.md](kernel_base.md), em três variantes do kernel: referência escalar (RCB-12), instruções personalizadas e RVV (RCB-14).

| Parte | Situação |
| --- | --- |
| Kernels de referência escalar (`kernel_ref.c`) das sete operações | Existente; passam no QEMU (S e L) e no gem5 (S e L, atomic) |
| Variante personalizada (`kernel_custom.c`) das sete operações | Existente; passa no QEMU em modo modelo (S e L) e no gem5 do fork com as instruções reais (S e L, atomic) |
| Variante RVV (`kernel_rvv.c`) das sete operações | Existente; passa no QEMU (S e L) e no gem5 (S e L na atomic; formas reduzidas na timing, minor e o3) |
| Oráculos em `benchmarks/common/rcb_ops.h` | Existente |
| YAMLs `experiments/<operação>_{s,l}.yaml` | Existente; CPU atomic, variante `ref` (as outras pelo campo `benchmark.variant`) |
| Equivalência entre variantes | Existente (RCB-15): `make validate`, ver [Validação de equivalência](#validação-de-equivalência) |

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
├── Makefile          # NAME := <operação>; include ../common/kernel.mk
├── main.c            # parâmetros, dados, ROI, oráculo, verificação, RESULT
├── kernel.h          # assinatura do kernel
├── kernel_ref.c      # referência escalar
├── kernel_custom.c   # instruções personalizadas (cnn_insn.h)
└── kernel_rvv.c      # intrínsecos RVV (rcb_rvv.h)
```

- **`main.c`:** segue o roteiro da base: parâmetros, dados, kernel `R` vezes na ROI, oráculo, `rcb_compare_i8` e `rcb_finish`. É o mesmo para todas as variantes.
- **`kernel_ref.c`:** o código medido, compilado em separado do `main.c`. Assim o compilador não move o kernel para fora da ROI nem elimina repetições.
- **`benchmarks/common/kernel.mk`:** concentra as regras de build: `FLAGS ?= -O2`, `VARIANT ?= ref`, o arquivo e o `-march` de cada variante, as flags obrigatórias e a dependência dos headers. Ver [Variantes](#variantes).
- **`conv3x3_im2col/im2col.h`:** a montagem do buffer, comum às três variantes.

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

## Variantes

O `YAML` escolhe a variante por `benchmark.variant` ([experiments.md](experiments.md#variantes)), e o `kernel.mk` compila o arquivo correspondente:

| Variante | Arquivo | Flags da variante | Roda em |
| --- | --- | --- | --- |
| `ref` | `kernel_ref.c` | `-march=rv64gc` | QEMU e qualquer gem5 |
| `custom` | `kernel_custom.c` | `-march=rv64gc -DCNN_INSN_HW` | Só o gem5 do fork. Com `make ... CNN_INSN=model`, usa o modelo em C e roda no QEMU |
| `rvv` | `kernel_rvv.c` | `-march=rv64gcv -fno-tree-vectorize` | QEMU (`-cpu rv64,v=true,vlen=256,vext_spec=v1.0`) e gem5 (`cpu.vlen`, padrão 256) |

Regras comuns às três:

- **Mesmo programa.** `main.c`, dados, ROI, oráculo e verificação são os mesmos, e só o arquivo do kernel muda. As três variantes dão o mesmo checksum.
- **Mesmo layout.** Os pesos ficam como na referência, por exemplo `[Cout][Cin]`. Nenhuma variante reorganiza dados fora da ROI.
- **Mesma ordem de laços externa**, para que as diferenças fiquem no laço interno.
- **Erro proposital.** `-DRCB_INJECT_ERROR` funciona em todas.

### Instruções personalizadas (`kernel_custom.c`)

| Kernel | Laço interno |
| --- | --- |
| `conv3x3_direct` | Por tap válido: `Cin/8` × (2 `ld` + `cnn.dot8`); `cnn.rqnt.relu` por saída |
| `conv3x3_im2col` | Montagem igual à da referência; GEMM com `9·Cin/8` × (2 `ld` + `cnn.dot8`); `cnn.rqnt.relu` por saída |
| `depthwise3x3` | A cada 8 canais: bias com 4 `ld` (pares int32); por tap, 2 `ld` + 4 `cnn.dwmac`; no fim, 4 `srai` (faixa alta), 8 `cnn.rqnt.relu` e 8 `sb` |
| `pointwise1x1` | `Cin/8` × (2 `ld` + `cnn.dot8`); `cnn.rqnt.relu` por saída |
| `maxpool2x2` | A cada 8 canais: 4 `ld`, 3 `cnn.max8`, 1 `sd` |
| `requant_relu` | `lw` + `cnn.rqnt.relu` + `sb` por elemento |
| `fc` | `In/8` × (2 `ld` + `cnn.dot8`); `cnn.rqnt.relu` por saída |

- **Cargas de 8 bytes.** `cnn_ld8`/`cnn_sd8` (`cnn_insn.h`) fazem um `memcpy` com `__builtin_assume_aligned(p, 8)`, que o GCC emite como um único `ld`/`sd`, sem violar as regras de aliasing. Os tensores vêm de `rcb_alloc`, alinhado a 64, e as dimensões contíguas são múltiplas de 8.
- **Acumulador `int64_t`.** `cnn_dot8` e `cnn_rqnt*` recebem e devolvem `int64_t`, a largura do registrador. Com `int32_t`, o GCC colocava um `sext.w` depois de cada `cnn.dot8`, porque não sabe que a instrução já devolve o valor estendido. Eram 7 instruções a cada 8 MACs no laço da FC em vez de 6. Conferido no `objdump`: nenhum `sext.w` nos laços internos das sete variantes `custom`.

### RVV (`kernel_rvv.c`)

Os intrínsecos são independentes da VLEN: há um `vsetvl` por bloco, e a cauda é tratada. Os blocos comuns estão em `benchmarks/common/rcb_rvv.h`, com os tipos na razão SEW/LMUL = 8: int8 em m1, produtos int16 em m2, acumuladores int32 em m4 e o produto da requantização em int64, m8.

| Kernel | Estratégia |
| --- | --- |
| `conv3x3_direct` | Por saída: os taps válidos acumulam no mesmo vetor int32 (`rcb_rvv_mac` sobre `Cin`); uma redução e requantização escalar |
| `conv3x3_im2col` | Montagem igual à da referência; GEMM com `rcb_rvv_mac` sobre `9·Cin`, redução e requantização escalar por saída |
| `depthwise3x3` | Vetoriza sobre os canais: acumulador começa no bias (`vle32`), por tap `vwmul` + `vwadd.wv`, e requantização vetorial (`rcb_rvv_requant_relu`) |
| `pointwise1x1`, `fc` | `rcb_rvv_mac` sobre `Cin`/`In`, redução e requantização escalar por saída |
| `maxpool2x2` | Vetoriza sobre os canais: 4 `vle8`, 3 `vmax`, 1 `vse8` |
| `requant_relu` | Blocos de `vle32` + requantização vetorial + `vse8` |

- **`rcb_rvv_mac`.** Para cada bloco, faz `vle8` + `vle8` + `vwmul` (int16, exato para int8 × int8) + `vwadd.wv` (int32). O acumulador é *tail-undisturbed* (`_tu`), para que um último bloco menor não apague faixas já somadas.
- **Requantização vetorial.** Faz `vwmul.vx` (int64) + `vadd.vx` (arredondamento) + `vnsra.wx` (desloca e estreita para int32, sem perda, porque |y| ≤ 2^31) + `vmax`/`vmin` + dois `vncvt`. É a mesma fórmula de `rcb_requantize`.
- **Requantização escalar nas operações de produto escalar.** Com os pesos `[Cout][Cin]`, comuns às variantes, a dimensão contígua é a da redução. Cada saída sai de uma redução e é requantizada com `rcb_requantize`. Vetorizar sobre as saídas exigiria transpor os pesos.
- **Sem autovetorização.** `-fno-tree-vectorize` garante que o único código vetorial é o dos intrínsecos. O GCC 13.3 do container não autovetoriza RVV em `-O2`, mas a flag deixa isso explícito.

### Limitação do gem5: reduções RVV na O3CPU

Um `vredsum.vs` com LMUL > 1 vira, no gem5, vários micro-ops que encadeiam o parcial pelo registrador de destino, um registrador "fixado" (`VPinVdMicroInst`). A O3CPU só marca esse registrador como pronto depois da última escrita, então não há dependência entre os micro-ops da cadeia, e um deles pode executar antes do anterior. Observado em 21/10/2026 na `fc` e na `pointwise1x1` S: a primeira saída saiu errada só na O3. A atomic, a timing e a minor estavam corretas. No trace `Exec`, o micro-op do segundo registrador do grupo leu `~0`, deixado pelo `vpinvd`, em vez do parcial do micro-op anterior.

Contorno, em `rcb_rvv_reduce`: o acumulador m4 é somado em m1 com 3 `vadd.vv` e só então reduzido por um `vredsum` em LMUL 1, que é um único micro-op. O custo é de 3 instruções vetoriais a mais por saída. As outras instruções com destino fixado que os kernels usam, como os estreitamentos (`vnsra`, `vncvt`) e as cargas com passo, não leem o próprio destino entre micro-ops, e todas as operações passam na O3.

## Oráculos

`benchmarks/common/rcb_ops.h` tem um oráculo por operação. Os oráculos seguem quatro regras:

- os laços estão na ordem da definição matemática;
- a acumulação é em int64;
- o teste de borda é feito por tap, e um tap no padding é pulado;
- a requantização usa `rcb_requantize`.

Os oráculos não mudam entre variantes, e a conv direta e a im2col compartilham o mesmo. Eles rodam fora da ROI, mas também são simulados. Uma versão anterior do oráculo da convolução, com o teste de borda dentro do laço interno, custava cerca de 3 vezes o kernel.

## Instruções medidas

`simInsts` dos dois blocos do `stats.txt`, na variante de referência, medidos no gem5 atomic em 20/10/2026. As três variantes estão em [Três variantes](#três-variantes). Os valores são a contagem da referência, não resultados de desempenho. O tempo de host inclui build, inicialização e saída do gem5.

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

### Três variantes

Medição de 21/10/2026, no gem5 atomic, `-O2`, GCC 13.3 e VLEN 256. A tabela mostra o `numInsts` da ROI (bloco 1 do `stats.txt`) e, na RVV, também o `numOps`. Nas variantes `ref` e `custom`, `numOps` = `numInsts`. As razões dividem as instruções da referência pelas da variante. As colunas "por MAC" usam os MACs nominais, e no pooling e na requantização contam por elemento.

Isto é **contagem de instruções**, não desempenho: a CPU atomic não modela latência, e uma instrução RVV com LMUL 4 faz o trabalho de várias. Ciclos e IPC serão medidos nas CPUs detalhadas (RCB-18 em diante).

| Operação | Tamanho | `ref` | `custom` | `rvv` | `rvv` `numOps` | `ref`/`custom` | `ref`/`rvv` | `custom` por MAC | `rvv` por MAC |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `conv3x3_direct` | S | 2.499.690 | 719.552 | 1.017.131 | 1.143.278 | 3,5× | 2,5× | 2,44 | 3,45 |
| | L | 36.586.544 | 7.886.016 | 8.372.129 | 9.699.748 | 4,6× | 4,4× | 1,67 | 1,77 |
| `conv3x3_im2col` | S | 2.324.694 | 489.465 | 468.967 | 563.178 | 4,7× | 5,0× | 1,66 | 1,59 |
| | L | 34.938.815 | 5.809.561 | 4.496.336 | 5.741.523 | 6,0× | 7,8× | 1,23 | 0,95 |
| `depthwise3x3` | S | 975.113 | 160.373 | 45.146 | 71.222 | 6,1× | 21,6× | 2,18 | 0,61 |
| | L | 7.992.565 | 1.283.237 | 339.430 | 553.246 | 6,2× | 23,5× | 2,18 | 0,58 |
| `pointwise1x1` | S | 1.976.613 | 305.198 | 329.781 | 436.280 | 6,5× | 6,0× | 1,16 | 1,26 |
| | L | 30.480.778 | 4.268.078 | 3.544.474 | 4.855.197 | 7,1× | 8,6× | 1,02 | 0,85 |
| `maxpool2x2` | S | 113.898 | 10.221 | 6.857 | 6.857 | 11,1× | 16,6× | 0,62 por elemento | 0,42 por elemento |
| | L | 898.931 | 71.069 | 26.953 | 26.953 | 12,6× | 33,4× | 0,54 por elemento | 0,21 por elemento |
| `requant_relu` | S | 49.182 | 24.603 | 2.602 | 8.234 | 2,0× | 18,9× | 6,01 por elemento | 0,64 por elemento |
| | L | 393.246 | 196.635 | 20.522 | 65.578 | 2,0× | 19,2× | 6,00 por elemento | 0,63 por elemento |
| `fc` | S | 115.270 | 12.642 | 7.541 | 11.320 | 9,1× | 15,3× | 0,77 | 0,46 |
| | L | 3.678.746 | 398.370 | 226.345 | 344.108 | 9,2× | 16,3× | 0,76 | 0,43 |

Leitura da tabela:

- **Referência.** É idêntica à medição de 20/10/2026, nas 14 combinações. Mover a montagem do im2col para `im2col.h` não mudou o código gerado.
- **`numOps` > `numInsts` na RVV.** Instruções com LMUL > 1, como `vwmul` (m2), `vwadd.wv` (m4) e a requantização em m8, viram vários micro-ops. No pooling, que só usa LMUL 1, os dois são iguais.
- **Custom com `Cin` pequeno.** Com `Cin` = 8 (conv S), cada tap tem um único `cnn.dot8`, e o controle do laço de taps pesa: 2,44 instruções por MAC, contra 1,67 em L (`Cin` = 16).
- **`requant_relu` custom.** A razão é 2,0×, porque continua com um `lw` e um `sb` por elemento, e o laço não é desenrolado. A RVV processa 32 elementos por bloco com VLEN 256.
- **Depois da ROI.** É igual na `ref` e na `rvv`, porque oráculo e verificação são os mesmos. A `custom` tem de 130 a 250 instruções a mais. A causa provável, não investigada, é o nome da variante no `printf` da linha `RESULT`: `custom` tem 6 letras, enquanto `ref` e `rvv` têm 3 e empatam.

Para reproduzir uma linha de outra variante, troque `benchmark.variant` no YAML (por exemplo, `experiments/conv3x3_direct_s_rvv.yaml`).

A estimativa de tempo da campanha em [scope.md](scope.md#estimativa-de-tempo-de-simulação) foi refeita com esses valores.

Para reproduzir uma linha, dentro do container:

```bash
uv run riscvcnnbench run experiments/conv3x3_direct_s.yaml
grep -E '^simInsts ' results/conv3x3_direct_s/<run_id>/gem5/stats.txt   # 1ª linha = ROI
```

## Validação de equivalência

Antes de usar qualquer número de desempenho, as três variantes de cada operação precisam produzir a mesma saída (RCB-15). Como todas recebem os mesmos dados e são comparadas com o mesmo oráculo ([kernel_base.md](kernel_base.md#verificação-e-resultado)), a equivalência é:

1. todas terminam com `mismatches=0` e código 0;
2. todas têm o mesmo `checksum`;
3. o mesmo binário dá o mesmo checksum no QEMU e no gem5.

```bash
make validate                 # e2e + validação; RCB_JOBS=N ajusta o paralelismo
uv run pytest -m validation   # só a validação, dentro do container
```

`tests/test_validation.py` monta a matriz abaixo e simula tudo em paralelo. Em 21/10/2026, com 4 processos, a matriz levou ~5 min (196 execuções: 84 no QEMU e 112 no gem5, mais as 84 compilações), e `make validate` inteiro levou 9 min 22 s (188 testes passaram).

| Variante | QEMU | gem5 atomic |
| --- | --- | --- |
| `ref` | sim | sim |
| `custom`, modo modelo (`CNN_INSN=model`) | sim (valida a lógica do kernel) | sim |
| `custom`, instruções reais | não (instrução ilegal) | sim, só no fork |
| `rvv` | sim, `-cpu rv64,v=true,vlen=256,vext_spec=v1.0` | sim, VLEN 256 |

Cobertura:

- **Tamanhos e conjuntos de dados.** O conjunto aleatório roda em S e L. Os extremos `satpos` e `satneg` ([kernel_base.md](kernel_base.md#dados-determinísticos)) rodam em S. São 7 operações × 4 casos (S aleatório, L aleatório, S `satpos`, S `satneg`) × 7 execuções (3 no QEMU + 4 no gem5), com 7 checksums iguais por caso.
- **Saturação de toda a saída.** Nos conjuntos extremos, além de bater com o oráculo, o checksum precisa ser o de uma saída inteira saturada: 127 em `satpos`, 0 em `satneg` e −128 no pooling. Isso prova que os extremos de fato chegaram às bordas da requantização.
- **Casos de borda das instruções.** São os 39 casos de [custom_instructions.md](custom_instructions.md), no modo hw, nas quatro CPUs (e2e).

Testes negativos (e2e):

| Erro | Como é provocado | Detecção |
| --- | --- | --- |
| Kernel errado | `-DRCB_INJECT_ERROR` muda `y[0]`, nas três variantes | Saída 1, `mismatches=1` e `ERRO: y[0] = ..., oráculo = ...` (`test_wrong_kernel_is_detected`) |
| Semântica errada de uma instrução | `-DCNN_INSN_INJECT_ERROR` no `cnn_insn_semantics` executa outra instrução real (`cnn.dwmac p=0`) no lugar do `cnn.dot8`, como faria um decodificador errado | No gem5, exatamente os 8 casos `dot8-*` em que as duas diferem falham; o de zeros coincide. Saída 1 (`test_wrong_instruction_semantics_is_detected`) |

## Testes

`tests/test_kernels_e2e.py`, executado com `pytest -m e2e`:

| Teste | Confere |
| --- | --- |
| `test_op_passes_on_qemu` | As sete operações em S e L, nas três variantes, passam no QEMU (`mismatches=0`) com o checksum da referência; a `custom` em modo modelo |
| `test_op_s_on_gem5_matches_qemu` | As sete em S, nas três variantes, rodam pelo `riscvcnnbench run` no gem5 atomic (`benchmark.variant` no YAML; a `custom` com as instruções reais), com 2 blocos no `stats.txt`, o checksum da referência no QEMU e `numOps` > `numInsts` na ROI da RVV (igual nas outras e no pooling RVV) |
| `test_rvv_on_detailed_cpus` | A RVV das sete operações nas CPUs timing, minor e o3, com formas reduzidas que exercitam a cauda dos blocos vetoriais |
| `test_vlen_reaches_gem5` | `cpu.vlen: 512` chega ao gem5 (`RVV enabled, VLEN = 512 bits`) e o checksum não muda |
| `test_direct_and_im2col_compute_the_same_layer` | A conv direta e a im2col dão o mesmo checksum em S e L, em cada variante |
| `test_wrong_kernel_is_detected` | Com `-DRCB_INJECT_ERROR`, as sete operações nas três variantes saem com 1 e mostram a diferença |
| `test_invalid_arguments_exit_with_2` | Mensagens de argumento inválido e código 2 |

Os tamanhos L no gem5 e os tamanhos S nas CPUs detalhadas não entram no e2e, pelo tempo de simulação. Os L na atomic foram executados uma vez para as tabelas acima. A RVV em S também passou uma vez na timing, na minor e na o3, depois do contorno da redução.

## Limites

- **Qualidade das implementações.** As três são razoáveis, mas não ajustadas ao máximo: nenhuma desenrola laços à mão, e a RVV requantiza as operações de produto escalar no escalar. As conclusões valem para estas implementações. O ganho das variantes é medido contra a referência. Outra versão do GCC ou outro nível de otimização mudam as contagens; a proveniência de cada execução registra a toolchain.
- **Oráculo simulado.** A verificação custa cerca de tanto quanto o kernel no gem5, e é mantida em todas as CPUs para que cada execução da campanha confira a própria saída (decisão em [scope.md](scope.md#estimativa-de-tempo-de-simulação)).
- **Caches no início da ROI.** A ROI começa com as caches aquecidas pela inicialização ([kernel_base.md](kernel_base.md#cuidados)), e a decisão fica para a RCB-18.
- **im2col escalar nas três variantes.** A montagem do buffer é a mesma em todas, e só a GEMM muda. Uma RVV completa também vetorizaria a cópia.
- **Contorno no gem5.** A redução RVV em LMUL 1 contorna a [limitação da O3](#limitação-do-gem5-reduções-rvv-na-o3cpu), com 3 instruções a mais por saída nas operações de produto escalar.
- **Erro comum.** Kernel e oráculo compartilham `rcb_requantize`. A fórmula é conferida pelos 39 casos de [custom_instructions.md](custom_instructions.md).
