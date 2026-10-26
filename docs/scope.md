# Escopo experimental

Este documento fecha **o que** será medido no TCC: operações de CNN, quantização, dimensões, variantes de implementação, modelos de CPU e métricas. Ele é a referência para as issues de kernels (RCB-11, RCB-12, RCB-14), instruções personalizadas (RCB-10, RCB-13) e métricas (RCB-16, RCB-17).

> Estado: as sete operações existem nas três variantes, referência (RCB-12), personalizada e RVV (RCB-14), ver [kernels.md](kernels.md); a equivalência é validada por `make validate` (RCB-15); a leitura das métricas da região de interesse (RCB-16) e as métricas derivadas com a comparação entre variantes (RCB-17) existem ([results.md](results.md#métricas)); cenários, execução em lote, CSV e a campanha (RCB-18+) são **planejados**. A velocidade de simulação, os nomes de estatísticas e as instruções da referência abaixo foram medidos no gem5 do projeto.

## Pergunta e objetivos

Pergunta da proposta: *como instruções RISC-V personalizadas afetam a quantidade de instruções executadas, o número de ciclos e as instruções por ciclo das principais operações de CNN utilizadas na inferência para Edge AI, em diferentes configurações de cache e memória?*

| Objetivo específico | O que este escopo fixa |
| --- | --- |
| 1. Base comparativa de operações com equivalência de resultados | [Operações](#operações), [Variantes](#variantes-de-implementação), [Quantização](#quantização) |
| 2. Framework para variar a hierarquia de memória e coletar métricas | [Modelos de CPU](#modelos-de-cpu), [Métricas](#métricas) |
| 3. Quantificar diferenças de instruções, ciclos e IPC | [Métricas centrais](#métricas-centrais) |
| 4. Identificar quando menos instruções viram menos ciclos e quando a memória limita | [Dimensões](#dimensões), [Métricas explicativas](#métricas-explicativas) |
| 5. Caracterização comparativa reprodutível | [Estimativa de tempo](#estimativa-de-tempo-de-simulação) e o restante do framework |

## Operações

A avaliação é **por operação**, não pela rede inteira, porque cada operação tem um padrão próprio de cálculo e de acesso à memória.

| Operação | Definição | Por que entra |
| --- | --- | --- |
| Convolução direta 3×3 | Stride 1, padding 1 ("same"), `Cin → Cout` | Concentra a maior parte do custo das CNNs. |
| Convolução im2col + GEMM | Mesma camada da convolução direta, reorganizada em matriz e multiplicada | Compara dois algoritmos para a **mesma** camada; o buffer do im2col troca memória por regularidade. |
| Convolução depthwise 3×3 | Stride 1, padding 1, um filtro por canal | Pouco cálculo por byte: base de MobileNet e DS-CNN. |
| Convolução pointwise 1×1 | `Cin → Cout`, sem vizinhança espacial | Par da depthwise nas convoluções separáveis; equivale a uma GEMM. |
| Max pooling 2×2 | Stride 2, sem requantização (mesma escala) | Operação sem multiplicação, limitada por memória. |
| Ativação/requantização | `int32 → int8` com ReLU, isolada | Aparece no fim de toda camada; nos kernels de convolução ela também vem embutida. |
| Totalmente conectada (FC) | `y = W·x + b` | Pesos lidos uma vez só: o caso mais limitado pela memória. |

## Quantização

Esquema **simétrico por tensor, zero-point 0**, no estilo do CMSIS-NN e do PULP-NN:

- **Tipos:** entradas, pesos e saídas em `int8`; bias e acumulação em `int32`.
- **Valor real:** `r = S · q` com escala `S > 0` por tensor e zero-point 0. O padding da convolução usa `0`, que representa o valor real zero.
- **Acumulação:** `acc = bias + Σ x·w`, em `int32`. Nas dimensões abaixo não há overflow: o pior caso de um termo é `128·128 = 16384`, e o maior número de termos somados é 1024 (FC L), o que dá `|acc| ≤ 2^24` mais o bias.
- **Requantização:** `y = sat8(ReLU((acc · M0 + 2^(30+s)) >> (31 + s)))`.
  - `M0` é um multiplicador `int32` em `[2^30, 2^31)` e `s ≥ 0` é um deslocamento. O produto `M0 · 2^-(31+s)` representa `S_in·S_w / S_out`.
  - O produto é feito em `int64`.
  - `sat8` satura em `[-128, 127]`, e a ReLU, com zero-point 0, é `max(·, 0)`.
- **Dados:** sintéticos e determinísticos, gerados pelo próprio benchmark (RCB-11). Escalas e `M0`/`s` são fixos por operação. Não há dataset nem medição de acurácia: o que importa é a equivalência exata entre as variantes.
- **Layout:**
  - ativações em **NHWC** (canal mais interno), para o produto escalar sobre `Cin` ser contíguo;
  - pesos de convolução em `[Cout][Kh][Kw][Cin]`, depthwise em `[Kh][Kw][C]` e FC em `[Out][In]`.

## Dimensões

Dois tamanhos por operação:

- **S** cabe na L1 de dados de 32KiB.
- **L** excede a L1 e cabe na L2 de 256KiB. A FC L excede também a L2.

As formas seguem camadas de modelos de Edge AI de referência do MLPerf Tiny: ResNet-8 em CIFAR-10 (32×32, 16–64 canais), MobileNetV1 0.25 e DS-CNN (depthwise + pointwise com 64 canais).

| Operação | Tamanho | Entrada | Saída | Pesos | MACs | Dados (≈) |
| --- | --- | --- | --- | --- | --- | --- |
| Conv 3×3 direta | S | 16×16×8 | 16×16×16 | 16×3×3×8 | 294.912 | 7 KiB |
| | L | 32×32×16 | 32×32×32 | 32×3×3×16 | 4.718.592 | 53 KiB |
| Conv 3×3 im2col+GEMM | S | 16×16×8 | 16×16×16 | 16×3×3×8 | 294.912 | 25 KiB (buffer 18 KiB) |
| | L | 32×32×16 | 32×32×32 | 32×3×3×16 | 4.718.592 | 197 KiB (buffer 144 KiB) |
| Depthwise 3×3 | S | 16×16×32 | 16×16×32 | 3×3×32 | 73.728 | 16 KiB |
| | L | 32×32×64 | 32×32×64 | 3×3×64 | 589.824 | 128 KiB |
| Pointwise 1×1 | S | 16×16×32 | 16×16×32 | 32×32 | 262.144 | 17 KiB |
| | L | 32×32×64 | 32×32×64 | 64×64 | 4.194.304 | 132 KiB |
| Max pooling 2×2 | S | 32×32×16 | 16×16×16 | — | — (16.384 elem.) | 20 KiB |
| | L | 64×64×32 | 32×32×32 | — | — (131.072 elem.) | 160 KiB |
| Requantização + ReLU | S | 4.096 `int32` | 4.096 `int8` | — | — (4.096 elem.) | 20 KiB |
| | L | 32.768 `int32` | 32.768 `int8` | — | — (32.768 elem.) | 160 KiB |
| FC | S | 512 | 32 | 32×512 | 16.384 | 17 KiB |
| | L | 1.024 | 512 | 512×1.024 | 524.288 | 515 KiB |

"Dados" soma entrada, pesos, bias, saída e buffers, e não conta pilha nem código. As caches de referência são as do exemplo `hello_param_cache.yaml`: L1 de 32KiB e L2 de 256KiB. Os cenários de memória finais ficam para a RCB-18.

## Variantes de implementação

Cada operação e cada tamanho têm três variantes, com **resultado idêntico byte a byte**, conferido por `make validate` (RCB-15, [kernels.md](kernels.md#validação-de-equivalência)):

| Variante | Compilação | Observação |
| --- | --- | --- |
| Referência escalar | `-march=rv64gc` | C portátil, base de comparação (RCB-12). |
| Instruções personalizadas | `-march=rv64gc` + `.insn` em `custom-0` e `custom-1` | Instruções especificadas em [custom_instructions.md](custom_instructions.md) (RCB-10), implementadas no fork do gem5 (RCB-13, RCB-14). |
| Vetorial RVV | `-march=rv64gcv`, intrínsecos `riscv_vector.h` | Extensão V padrão como comparação com as instruções personalizadas. |

Viabilidade do RVV, verificada em 20/10/2026 com um produto escalar int8 (`vle8`, `vwmul`, `vwredsum`):

- o GCC 13.3 do container compila com `-march=rv64gcv`;
- o QEMU executa com `-cpu rv64,v=true,vlen=256`;
- o gem5 executa com resultado correto nas CPUs atomic, timing, minor e o3, e anuncia `RVV enabled, VLEN = 256 bits, ELEN = 64 bits`.

Como ficou na RCB-14 ([kernels.md](kernels.md#variantes)):
- **VLEN:** campo `cpu.vlen` do YAML (padrão 256, o do gem5), passado ao gem5 e registrado na configuração resolvida de cada execução.
- **Seleção da variante:** campo `benchmark.variant` (`ref`, `custom`, `rvv`); o `kernel.mk` escolhe o arquivo do kernel e o `-march` (`rv64gcv` na RVV) depois das flags do experimento.
- **Contagem de instruções:** confirmado no bloco da ROI que, na RVV, `numOps` > `numInsts` (instruções com LMUL > 1 viram vários micro-ops); nas variantes escalar e personalizada os dois são iguais. As duas são extraídas da ROI (`insts` e `ops`, RCB-16).
- **Limitação do gem5:** reduções RVV com LMUL > 1 podem dar resultado errado na O3CPU; os kernels reduzem em LMUL 1 ([kernels.md](kernels.md#limitação-do-gem5-reduções-rvv-na-o3cpu)).

## Modelos de CPU

| CPU | Uso | Por quê |
| --- | --- | --- |
| atomic | Só validação funcional (equivalência, `RESULT`) | Não modela tempo; seus "ciclos" não são medida de desempenho. |
| timing | Medição: CPU simples sem pipeline | Isola o efeito da memória: cada acesso espera a hierarquia. |
| minor | Medição: em ordem com pipeline | Núcleo embarcado típico. |
| o3 | Medição: fora de ordem | Mostra quanto a execução fora de ordem esconde da latência da memória. |

O clock fica em 1GHz, o padrão. Com o clock fixo, ciclos e tempo simulado são proporcionais, e a comparação usa ciclos.

## Compilação

Todas as variantes são compiladas com GCC 13.3 e `-O2`, o padrão de `compiler.flags`, para que as diferenças medidas venham das instruções e da memória, e não do compilador. O sumário executivo da proposta cita também "otimizações de compilador". Por isso, a matriz terá um **contraste mínimo `-O2` × `-O3`** com uma ou duas operações, ref e custom, em um cenário e uma CPU (decisão de 22/10/2026, **planejado** na RCB-22). O contraste mostra se a otimização do compilador muda a redução de instruções e o speedup. Na variante RVV, `-fno-tree-vectorize` vem depois das flags do experimento, então `-O3` não autovetoriza o código.

## Métricas

Os nomes abaixo foram conferidos no `stats.txt` do gem5 do projeto (25.1.0.1, fork em `0c4d16f`) em 20/10/2026, com `hello_riscv_param` nas quatro CPUs. Estatísticas de cache só existem quando aquele nível está configurado. Nos benchmarks com a base comum, o primeiro bloco do `stats.txt` cobre só a região de interesse (ROI, RCB-11). `riscvcnnbench stats` extrai as métricas abaixo desse bloco, com as chaves e as regras de valor ausente de [results.md](results.md#métricas) (RCB-16). O gem5 não imprime estatísticas de cache e de memória que valem zero, e o parser as trata como 0, e não como ausentes.

### Métricas centrais

| Métrica | Pergunta (objetivo) | Estatística no gem5 | Observação |
| --- | --- | --- | --- |
| Instruções executadas | Quantas instruções cada variante executa? (OE3) | `system.cpu.commitStats0.numInsts` | Igual a `simInsts` em núcleo único. Uma instrução personalizada ou vetorial conta 1. |
| Micro-operações | Quanto trabalho interno há por instrução? (OE3, RVV) | `system.cpu.commitStats0.numOps` / `simOps` | Diferem de `numInsts` em instruções divididas em micro-ops. |
| Ciclos | A redução de instruções vira redução de ciclos? (OE3, OE4) | `system.cpu.numCycles` | Só timing, minor e o3. A atomic também imprime `numCycles`, mas é só `simTicks` / período; o framework o deixa ausente. |
| IPC | Quanto paralelismo o núcleo extrai? (OE3) | `system.cpu.ipc` | Conferir com `numInsts / numCycles`. |
| Tempo simulado | Comparação com clocks diferentes, se houver | `simSeconds` / `simTicks` | Tick não é ciclo (10¹² ticks/s). |

### Métricas explicativas

| Métrica | Pergunta (objetivo) | Estatística no gem5 |
| --- | --- | --- |
| Acessos, faltas e taxa de faltas na L1 de dados | A memória limita o ganho? (OE4) | `system.cpu.dcache.overallAccesses::total`, `overallMisses::total`, `overallMissRate::total` |
| Latência média de falta na L1d | Quanto custa cada falta? (OE4) | `system.cpu.dcache.demandAvgMissLatency::total` (em ticks) |
| Faltas na L1 de instruções | O código maior das variantes pesa? (OE4) | `system.cpu.icache.overallMisses::total`, `overallMissRate::total` |
| Acessos e faltas na L2 | Os dados L cabem na L2? (OE4) | `system.l2cache.overallAccesses::total`, `overallMisses::total`, `overallMissRate::total`, `demandAvgMissLatency::total` |
| Tráfego e latência da DRAM (DDR4) | Quanto vai à memória principal? (OE4) | `system.mem_ctrl.readReqs`, `system.mem_ctrl.writeReqs`, `system.mem_ctrl.dram.bwTotal::total`, `system.mem_ctrl.dram.avgMemAccLat` |
| Tráfego da memória `simple` | Idem, com memória de latência fixa | `system.memory.bytesRead::total`, `bytesWritten::total`, `numReads::total`, `numWrites::total` |
| Mistura de instruções | De onde vem a redução de instruções? (OE3) | `system.cpu.commitStats0.numLoadInsts`, `numStoreInsts`, `numMemRefs` |
| Desvios mal previstos | Laços mais curtos mudam a previsão? (OE4) | `system.cpu.branchPred.condIncorrect` |

### Métricas derivadas (RCB-17)

Calculadas a partir das centrais (`metric.py`; fórmulas em [results.md](results.md#métricas-derivadas-e-comparações)):
- por execução: CPI, faltas por mil instruções, valores por repetição (÷ `R`), instruções e ciclos por MAC e MACs por ciclo, com os MACs **nominais** da tabela de [Dimensões](#dimensões), calculados a partir dos parâmetros da linha `RESULT` (pooling e requantização por elemento);
- por par de variantes no mesmo cenário (ref × custom, ref × rvv, custom × rvv): redução de instruções `R_I` (também em micro-ops), speedup em ciclos `S_C` e razão de IPC, com `S_C = R_I × IPC_b / IPC_a`;
- contraste de compilador: o mesmo par com variante fixa, `-O2` × outro `-O*`.

A pergunta da proposta (OE4) é respondida comparando a redução de instruções com o speedup em ciclos em cada cenário de memória: a razão de IPC diz quanto da economia de instruções se perde (ou se ganha) em ciclos. `riscvcnnbench compare` mostra os pares; o CSV fica para a RCB-20.

## Estimativa de tempo de simulação

Velocidade de simulação medida no host do projeto (20/10/2026). O teste foi `hello_riscv_param 65536 8`, com 3,5 M de instruções, L1 de 32KiB, L2 de 256KiB e DDR4 nas CPUs com tempo:

| CPU | Instruções simuladas por segundo |
| --- | --- |
| atomic | ~1,25 M |
| timing | ~0,94 M |
| minor | ~0,31 M |
| o3 | ~0,27 M |

Instruções da variante de referência, medidas em 20/10/2026 no gem5 atomic (RCB-12; tabela por operação em [kernels.md](kernels.md#instruções-medidas)):

| | ROI (kernel) | Simulado (ROI + verificação) |
| --- | --- | --- |
| Sete operações S | 8,1 M | 18,4 M |
| Sete operações L | 115,0 M | 248,4 M |
| **Por variante** | **123,0 M** | **266,8 M** |

- **Instruções por MAC:** entre 7,0 e 8,5 nas convoluções, na pointwise e na FC, e 13,2 a 13,6 na depthwise. A estimativa anterior supunha 5.
- **Pooling e requantização:** cerca de 6,9 instruções por elemento de entrada e 12,0 por elemento, respectivamente. A estimativa anterior supunha 4 e 10.
- **Verificação:** o oráculo e a comparação rodam fora da ROI, mas também são simulados e custam cerca de tanto quanto o kernel. A inicialização dos dados, antes da ROI, também é simulada e não entra nesses números.

Variantes personalizada e RVV, medidas em 21/10/2026 no gem5 atomic (RCB-14; tabela em [kernels.md](kernels.md#três-variantes)). A verificação é a mesma nas três:

| Variante | ROI S + L | Simulado (ROI + verificação) |
| --- | --- | --- |
| Referência | 123,0 M | 266,8 M |
| Personalizada | 21,6 M | 165,5 M |
| RVV (VLEN 256) | 18,9 M | 162,7 M |
| **Três variantes** | **163,5 M** | **595,0 M** |

As velocidades de simulação acima foram medidas com código escalar. Na atomic, a RVV simulou a uma taxa parecida (~1 M instruções por segundo). Nas CPUs detalhadas, ainda é preciso medir, porque cada instrução vetorial vira vários micro-ops.

| Item | Valor |
| --- | --- |
| Binários | 7 operações × 2 tamanhos × 3 variantes = 42 |
| Configurações | 4 cenários de memória (RCB-18) × 3 CPUs + atomic para validação = 13 |
| Instruções simuladas por configuração | 595,0 M (era ≤ 800 M na estimativa da RCB-12, que supunha as variantes iguais à referência) |
| Tempo por cenário de memória | o3 ≈ 37 min, minor ≈ 32 min, timing ≈ 11 min (≈ 1,3 h) |
| Total por passada da matriz | ≈ 5,3 h nos 4 cenários, mais ≈ 8 min de atomic (546 execuções) |
| Maior execução isolada | Conv direta L, referência, em o3: ≈ 290 s |

**Decisão (21/10/2026):** o oráculo e a comparação são simulados em todas as CPUs, inclusive nas detalhadas. Cada execução da campanha verifica a própria saída (`mismatches=0` e código de saída 0), e uma execução que calculou errado aparece como falha no `metadata.json`. Isso protege as medições contra defeitos do simulador que só aparecem nas CPUs detalhadas, como o da redução RVV na O3CPU ([kernels.md](kernels.md#limitação-do-gem5-reduções-rvv-na-o3cpu)), e por isso a estimativa acima já inclui a verificação.

Forma de reduzir o tempo ainda em aberto, a decidir nas RCB-18 e RCB-22: simular fora da ROI com a CPU atomic e trocar para a CPU detalhada só na ROI, como permite o gem5. A verificação continua valendo, porque a saída calculada na CPU detalhada é comparada com o oráculo, ainda que o oráculo rode na atomic. Isso também afeta o estado das caches no início da ROI.

Mesmo sem reduções, a matriz cabe no cronograma da proposta (experimentos em outubro e novembro), com uma passada por dia. As incertezas:
- a velocidade foi medida com um laço simples; configurações sem cache geram mais eventos de memória e podem simular mais devagar;
- a velocidade de simulação das instruções vetoriais nas CPUs detalhadas não foi medida (na atomic, foi parecida com a do código escalar).

Como o gem5 é determinístico, repetir uma execução com as mesmas entradas deve reproduzir as mesmas estatísticas (a confirmar); repetições servem só para medir o tempo do host.

## Fora do escopo

| Item | Motivo |
| --- | --- |
| Rede completa (mini-CNN) | A avaliação é por operação; fica como trabalho futuro (decisão de 17/10/2026). |
| Treinamento, quantização com treino, acurácia | Os dados são sintéticos; mede-se desempenho e equivalência, não qualidade do modelo. |
| Quantização assimétrica, por canal, outros tipos (int4, float) | Esquema único simétrico int8 para manter as variantes comparáveis. |
| RTL, hardware real, área e energia | O gem5 dá desempenho arquitetural; validação física está fora do alcance (proposta, seção 3). |
| Modo full-system, sistema operacional, multinúcleo | Modo SE com um núcleo isola o efeito de instruções e memória. |
| Autovetorização do compilador | A variante RVV usa intrínsecos, para o código vetorial ser controlado e comparável. |
| Variação de VLEN, latências internas de cache e CPU | Fixos nos padrões; podem virar parâmetros depois. |
