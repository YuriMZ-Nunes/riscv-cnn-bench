# Cenários de CPU e memória

Os cenários arquiteturais das comparações (RCB-18). O objetivo específico 4 pergunta quando uma redução de instruções vira redução de ciclos. Três fatores podem impedir isso, e cada um tem aqui um eixo configurável:

| Fator | Eixo | Campo do YAML |
| --- | --- | --- |
| Hierarquia de memória | Quatro [cenários de memória](#cenários-de-memória) nomeados e o [estado das caches](#estado-das-caches-no-início-da-roi) no início da ROI | `scenario`, `benchmark.cache_state` |
| Organização da CPU | timing, minor e uma [O3 de borda](#o3-de-borda-o3-edge) | `cpu.model` |
| Latência das instruções | [Latência](#latência-das-instruções-personalizadas) de `cnn.dot8`, `cnn.dwmac` e `cnn.rqnt[.relu]` | `cpu.custom_latency` |

| Parte | Situação |
| --- | --- |
| Cenários de memória em [`configs/scenarios.yaml`](../configs/scenarios.yaml) e campo `scenario` | Existente |
| CPU `o3-edge` e os parâmetros fixos das CPUs | Existente, em [`configs/gem5/se_riscv_configurable.py`](../configs/gem5/se_riscv_configurable.py) |
| Classe `CnnMult` no fork do gem5 e campo `cpu.custom_latency` | Existente ([custom_instructions.md](custom_instructions.md#latência-configurável)) |
| Caches frias no início da ROI (`benchmark.cache_state: cold`) | Existente |
| Benchmark [`insn_latency`](../benchmarks/insn_latency/main.c), testes e2e e validação nas CPUs com tempo | Existente |
| Execução em lote da matriz (operações × variantes × CPUs × cenários) | Planejado (RCB-19) |
| Escolha final da matriz (quais latências, se haverá caches frias) | Planejado (RCB-22) |

As medições citadas aqui são de 26/10/2026, com o gem5 do fork em `ce03244`, e servem só de ilustração. Não são resultados da campanha.

## Cenários de memória

Um experimento escolhe um cenário com `scenario: <nome>`, que preenche `cache` e `memory` (as duas seções não podem aparecer junto com ele). Todos usam DDR4 e, quando têm caches, a mesma L1i de 32KiB, para que só a hierarquia de dados mude de um para outro.

| Cenário | L1i | L1d | L2 | Memória | O que mostra |
| --- | --- | --- | --- | --- | --- |
| `sem-cache` | — | — | — | DDR4 | Caso-limite: instruções e dados vêm direto da DRAM, a conexão de pior desempenho para aceleradores matriciais RISC-V no gem5 em Aquino et al. (2025). Como cada busca de instrução também vai à DRAM, a redução de instruções diminui também esse tráfego |
| `l1` | 32KiB, 4 vias | 32KiB, 4 vias | — | DDR4 | Os dados S cabem na L1d; os L vêm da DRAM |
| `l1-l2` | 32KiB, 4 vias | 32KiB, 4 vias | 256KiB, 8 vias | DDR4 | As caches de referência dos tamanhos de [scope.md](scope.md#dimensões): S cabe na L1d, L cabe na L2 (menos a FC L) |
| `reduzido` | 32KiB, 4 vias | 4KiB, 4 vias | 32KiB, 8 vias | DDR4 | Os dados S não cabem na L1d, mas cabem na L2; os dados L não cabem na L2 |

O cenário `reduzido` cobre de uma vez os dois casos que faltavam: com L1 de 32KiB, todos os dados S cabem; com L2 de 256KiB, todos os L cabem, menos a FC. Sem ele, a memória de dados quase não pesaria nos cenários com cache. A L1d de 4KiB e a L2 de 32KiB são tamanhos de microcontroladores e núcleos de borda pequenos.

A memória `simple` (latência fixa) continua sendo o padrão do YAML, para que um experimento sem `scenario` e sem `memory` siga equivalente a `configs/gem5/se_riscv.py`, mas não entra nos cenários.

### O que cabe em cada nível

"Dados na ROI" soma o que o kernel lê e escreve: entrada, pesos, bias, saída e, na im2col, o buffer das colunas. A saída do oráculo não entra, porque ele roda depois da ROI. As células trazem as faltas de **dados** na ROI, medidas no gem5 atomic, com a variante de referência e as caches aquecidas (`system.cpu.dcache.overallMisses::total` e `system.l2cache.overallMisses::cpu.data`). Cabe quando as faltas ficam perto de zero; não cabe quando elas chegam ao número de linhas de 64 bytes dos dados ou o passam.

| Operação | Tam. | Dados na ROI | Linhas | L1d 32KiB (`l1`, `l1-l2`) | L2 256KiB (`l1-l2`) | L1d 4KiB (`reduzido`) | L2 32KiB (`reduzido`) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `conv3x3_direct` | S | 7,2 KiB | 115 | cabe (0) | cabe (0) | não cabe (95) | cabe (0) |
| | L | 52,6 KiB | 842 | não cabe (640) | cabe (0) | não cabe (66.302) | não cabe (674) |
| `conv3x3_im2col` | S | 25,2 KiB | 403 | cabe (17) | cabe (0) | não cabe (695) | cabe (13) |
| | L | 196,6 KiB | 3.146 | não cabe (5.429) | cabe (7) | não cabe (64.457) | não cabe (5.427) |
| `depthwise3x3` | S | 16,4 KiB | 263 | cabe (9) | cabe (0) | não cabe (259) | cabe (6) |
| | L | 128,8 KiB | 2.061 | não cabe (2.050) | cabe (0) | não cabe (262.204) | não cabe (2.051) |
| `pointwise1x1` | S | 17,1 KiB | 274 | cabe (8) | cabe (0) | não cabe (258) | cabe (8) |
| | L | 132,3 KiB | 2.116 | não cabe (2.050) | cabe (0) | não cabe (31.507) | não cabe (2.050) |
| `maxpool2x2` | S | 20 KiB | 320 | cabe (1) | cabe (0) | não cabe (324) | cabe (0) |
| | L | 160 KiB | 2.560 | não cabe (2.564) | cabe (0) | não cabe (2.564) | não cabe (2.564) |
| `requant_relu` | S | 20 KiB | 320 | cabe (2) | cabe (1) | não cabe (321) | cabe (4) |
| | L | 160 KiB | 2.560 | não cabe (2.561) | cabe (1) | não cabe (2.561) | não cabe (2.561) |
| `fc` | S | 16,7 KiB | 267 | cabe (0) | cabe (0) | não cabe (268) | cabe (0) |
| | L | 515,5 KiB | 8.248 | não cabe (8.248) | não cabe (8.234) | não cabe (8.249) | não cabe (8.248) |

Leitura da tabela:

- **A previsão por capacidade se confirma** em todas as 56 células. As poucas faltas onde os dados cabem (até 17, na im2col S) são conflitos de associatividade.
- **Faltas acima do número de linhas** aparecem quando a janela da operação não cabe na L1d de 4KiB e as mesmas linhas são lidas várias vezes: na depthwise L, 262 mil faltas para 2 mil linhas. O pooling, a requantização e a FC leem cada linha uma vez, e as faltas igualam as linhas.
- **Faltas de instrução.** A L2 também falta no código do kernel, que só é executado dentro da ROI: de 3 a 8 linhas em cada execução, mesmo com as caches aquecidas. Por isso `l2_misses` (que soma instruções e dados) não chega a zero.

## Estado das caches no início da ROI

| `benchmark.cache_state` | O que acontece | Uso |
| --- | --- | --- |
| `warm` (padrão) | A ROI começa com as caches no estado deixado pela inicialização, que acabou de escrever os tensores | Uma camada que consome a saída da anterior, com os dados ainda nas caches |
| `cold` | Logo antes da ROI, o gem5 grava as linhas sujas na memória e invalida todas as caches (L1i, L1d e L2) | Dados que vêm da memória, como pesos lidos pela primeira vez |

**Decisão.** O padrão é `warm`. O efeito da memória de dados aparece nos cenários em que os dados não cabem (tabela acima) e no `sem-cache`, sem misturar faltas compulsórias, que são as mesmas para as três variantes. A opção `cold` existe para medir o outro extremo, e a matriz da campanha decide se a usa (RCB-22).

**Como funciona.** `rcb_roi_begin` emite um `m5_work_begin` logo antes do `m5_reset_stats` ([kernel_base.md](kernel_base.md#região-de-interesse)). Com `cold`, a configuração gem5 liga `system.exit_on_work_items`, e a simulação para nesse ponto. O script drena o sistema (`m5.drain()`), chama `memWriteback` e `memInvalidate` só nos objetos de cache e continua. `m5.memInvalidate(root)` esvaziaria também as TLBs e o BTB, e eles ficam como estavam. O `stdout.log` mostra `Caches esvaziadas antes da ROI no tick N: <caches>`. Com `warm`, o `m5_work_begin` não faz nada. É o mesmo binário nos dois casos, e as instruções da ROI são as mesmas.

`cold` exige caches e um benchmark que marque a ROI, e o YAML recusa o resto. O que continua aquecido: TLBs, preditor de desvios e o estado da DRAM (linhas abertas nos bancos).

Exemplo (fc S, `l1-l2`, ciclos da ROI):

| CPU | Variante | `warm` | `cold` | Aumento |
| --- | --- | --- | --- | --- |
| timing | ref | 329.558 | 352.640 | +7,0% |
| | custom | 38.208 | 60.075 | +57,2% |
| minor | ref | 148.403 | 167.278 | +12,7% |
| | custom | 18.963 | 35.261 | +85,9% |
| o3-edge | ref | 66.455 | 80.288 | +20,8% |
| | custom | 10.909 | 21.910 | +100,8% |

O custo de buscar os 17 KiB na DRAM é parecido nas duas variantes, mas pesa muito mais na custom, que executa 9 vezes menos instruções. O speedup em ciclos da custom sobre a ref cai de 8,63 para 5,87 na timing, de 7,83 para 4,74 na minor e de 6,09 para 3,66 na o3-edge. É o efeito que o objetivo específico 4 quer medir. Com `cold`, a L1d tem 268 a 270 faltas de dados na timing e na minor, uma por linha. Na o3-edge são 2.107, porque a O3 conta cada acesso a uma linha que ainda está chegando (faltas que se juntam no mesmo MSHR); a L2 tem 268 a 271 nas três.

## CPUs

| CPU | Uso | Organização |
| --- | --- | --- |
| `atomic` | Só validação funcional | Sem tempo; não entra nas medições |
| `timing` | Medição | Uma instrução por vez, sem pipeline; cada acesso espera a hierarquia. Isola o efeito da memória |
| `minor` | Medição | Em ordem, dupla emissão (padrão do gem5) |
| `o3-edge` | Medição | Fora de ordem, estreita, de borda |
| `o3` | Contraste | Fora de ordem, padrão do gem5, 8 instruções por ciclo |

Todas a 1GHz. Nas CPUs `timing`, `minor` e `o3-edge` com o cenário `l1-l2`, as três variantes das sete operações em S passam com `mismatches=0` e o mesmo checksum da atomic (`make validate`, RCB-18).

### MinorCPU

A MinorCPU padrão do gem5 é adequada como núcleo de borda em ordem, sem mudanças. Ela emite e completa até 2 instruções por ciclo (`decodeInputWidth`, `executeInputWidth`, `executeIssueLimit` e `executeCommitLimit` iguais a 2) e no máximo 1 acesso à memória por ciclo (`executeMemoryIssueLimit`). Tem 2 unidades inteiras, 1 de multiplicação (3 ciclos), 1 de divisão (9 ciclos), 1 de ponto flutuante e SIMD (6 ciclos), 1 de memória e preditor de desvios torneio. É o perfil dos núcleos de dupla emissão em ordem usados na borda, como o Cortex-A53 e o SiFive U74. O próprio gem5 modela o U74 da placa HiFive Unmatched a partir da MinorCPU (`src/python/gem5/prebuilt/riscvmatched/`).

A única mudança na Minor é a [unidade própria das instruções personalizadas](#latência-das-instruções-personalizadas).

### O3 de borda (`o3-edge`)

A O3CPU padrão do gem5 busca, decodifica, emite e completa 8 instruções por ciclo, com ROB de 192 entradas, largura dos maiores núcleos de alto desempenho. Na pointwise S chegou a IPC 5,1 (tabela abaixo), o que nenhum núcleo de borda faz. A `o3-edge` usa as larguras, as filas e os registradores do **MediumBOOM**, a configuração de 2 instruções por ciclo do BOOM v3, núcleo fora de ordem RISC-V da UC Berkeley (Zhao et al., "SonicBOOM: The 3rd Generation Berkeley Out-of-Order Machine", CARRV 2020). Os valores vêm de `WithNMediumBooms` em [`src/main/scala/v3/common/config-mixins.scala`](https://github.com/riscv-boom/riscv-boom/blob/66a928483a5daaa2eac503e71b8fff466c1e4143/src/main/scala/v3/common/config-mixins.scala), conferidos em 26/10/2026.

| Parâmetro da O3CPU | Padrão do gem5 | `o3-edge` | MediumBOOM |
| --- | --- | --- | --- |
| `fetchWidth` | 8 | 4 | `fetchWidth = 4` |
| `fetchBufferSize` (bytes) / `fetchQueueSize` | 64 / 32 | 16 / 16 | `numFetchBufferEntries = 16` |
| `decodeWidth`, `renameWidth`, `dispatchWidth` | 8 | 2 | `decodeWidth = 2`, `dispatchWidth = 2` |
| `issueWidth`, `wbWidth` | 8 | 4 | Portas de emissão: memória 1 + inteira 2 + ponto flutuante 1 |
| `commitWidth` | 8 | 2 | Igual a `decodeWidth` |
| `numROBEntries` | 192 | 64 | `numRobEntries = 64` |
| Fila de emissão (`instQueues[0].numEntries`) | 64 | 48 | Filas de 12 (memória) + 20 (inteira) + 16 (ponto flutuante) |
| `LQEntries` / `SQEntries` | 32 / 32 | 16 / 16 | `numLdqEntries = 16`, `numStqEntries = 16` |
| `numPhysIntRegs` / `numPhysFloatRegs` | 256 / 256 | 80 / 64 | `numIntPhysRegisters = 80`, `numFpPhysRegisters = 64` |
| `numPhysVecRegs` | 256 | 96 | — (o BOOM não tem a extensão V) |
| Unidades `IntALU` / `IntMultDiv` | 6 / 2 | 2 / 1 | 2 portas inteiras, uma delas com multiplicador e divisor |
| `FP_ALU` / `FP_MultDiv` | 4 / 2 | 1 / 1 | 1 porta de ponto flutuante |
| `SIMD_Unit` | 4 | 1 | — |
| Portas de memória (`RdWrPort`) | 4 | 1 | 1 porta de memória |

Escolhas que não vêm do BOOM:

- **Uma fila de emissão só.** O BOOM tem três filas, uma por tipo. A O3CPU do gem5 25.1 aceita várias (`instQueues`), mas o mapeamento das classes de operação para filas não foi estudado; a fila única de 48 entradas tem a soma das três.
- **Extensão V.** O BOOM não a implementa. A `o3-edge` tem 1 unidade SIMD, o mínimo para executar a variante RVV, e 96 registradores vetoriais físicos (32 arquiteturais + 8 internos do gem5, mais folga para renomear), na mesma proporção dos inteiros.
- **Preditor de desvios e atrasos entre estágios.** Ficam os padrões do gem5 (preditor torneio). O BOOM usa TAGE-L.

Com uma só unidade SIMD, a `o3-edge` expôs um segundo defeito do gem5 com registradores vetoriais fixados, e a variante RVV de duas operações dava resultado errado. O contorno está no kernel ([kernels.md](kernels.md#limitação-do-gem5-reduções-rvv-na-o3cpu)), e as sete operações passam.

IPC da ROI em S, cenário `l1-l2`, caches aquecidas:

| Operação | Variante | Instruções | minor | o3-edge | o3 (padrão) |
| --- | --- | --- | --- | --- | --- |
| `fc` | ref | 115.270 | 0,78 | 1,73 | 1,74 |
| | custom | 12.642 | 0,67 | 1,16 | 1,44 |
| `conv3x3_direct` | ref | 2.499.690 | 0,90 | 1,15 | 2,12 |
| | custom | 719.552 | 1,30 | 1,75 | 5,08 |
| `pointwise1x1` | ref | 1.976.613 | 0,76 | 1,00 | 5,09 |
| | custom | 305.198 | 0,92 | 1,41 | 5,32 |

A `o3-edge` fica abaixo de 2, o limite da largura de commit, e a O3 padrão passa de 5 nas operações com laços regulares. Por isso a O3 padrão fica só como contraste: com ela, a capacidade da CPU de esconder latências seria muito maior que a de qualquer núcleo de borda.

## Latência das instruções personalizadas

`cnn.dot8`, `cnn.dwmac` e `cnn.rqnt[.relu]` têm a classe de operação própria `CnnMult` no fork do gem5 (RCB-18). Até a RCB-17 elas usavam `IntMult`, a classe do `mul`, e mudar a latência dela mudaria também a referência. `cnn.max8` continua em `IntAlu`: é um máximo byte a byte, do custo de um `add`.

O campo `cpu.custom_latency` (padrão 3, a latência do `mul`) define a latência de `CnnMult`:

| CPU | Como a latência é aplicada |
| --- | --- |
| `o3`, `o3-edge` | `CnnMult` tem um `OpDesc` próprio na mesma unidade `IntMultDiv` do `mul`, com pipeline. Com 3, o comportamento é o das unidades padrão |
| `minor` | Uma unidade da Minor tem uma latência só, e o scoreboard libera o destino no commit, no fim da unidade. Por isso `CnnMult` tem uma unidade só dela, com pipeline e `opLat` igual à latência, ao lado da de multiplicação, como a de divisão. Vale também com 3, para que só a latência mude entre os valores da matriz. A diferença para a unidade compartilhada só aparece quando um `mul` e uma instrução personalizada disputam a unidade no mesmo ciclo |
| `atomic`, `timing` | Não modelam a latência das unidades. O YAML só aceita o padrão nelas |

**Valores para a matriz:** 3, igual ao `mul`, e 6, o dobro, como hipótese pessimista para a análise de sensibilidade. O argumento, que não foi verificado em hardware: um `cnn.dot8` faz 8 produtos de 8×8 bits e os soma ao acumulador, e a árvore que soma os produtos parciais tem profundidade parecida com a de um multiplicador de 64×64 bits, então 3 ciclos é plausível, mas não garantido, porque a soma ao acumulador de 32 bits pode pedir mais um estágio. O valor 6 cobre, por exemplo, uma implementação que reusa o multiplicador em duas passagens. A escolha final fica para a RCB-22.

**Medição com o `insn_latency`.** O benchmark executa, na ROI, 1000 iterações de 8 instruções em cadeia, em que cada uma lê o resultado da anterior. Ciclos da ROI, com L1i e L1d de 32KiB e memória `simple` (o teste e2e repete a medição no cenário `l1-l2`):

| CPU | `mul`, latência 3 | `mul`, latência 6 | `cnn.dot8`, latência 3 | `cnn.dot8`, latência 6 |
| --- | --- | --- | --- | --- |
| minor | 24.143 | 24.143 | 24.073 | 48.047 |
| o3 | 24.068 | 24.068 | 24.018 | 48.018 |
| o3-edge | 24.076 | 24.076 | 24.035 | 48.035 |

A latência das instruções personalizadas não muda o `mul`. Com 6, cada `cnn.dot8` da cadeia leva 3 ciclos a mais (24.000 ciclos para 8.000 instruções). Com 3, ele custa o mesmo que o `mul`. O teste `test_custom_latency_changes_only_custom_cycles` confere isso.

Num kernel real o efeito depende de quanto a CPU esconde a latência. Ciclos da ROI da variante custom em S, `l1-l2`:

| Operação | CPU | Latência 3 | Latência 6 | Variação |
| --- | --- | --- | --- | --- |
| `fc` | minor | 18.963 | 19.075 | +0,6% |
| | o3-edge | 10.909 | 11.757 | +7,8% |
| `conv3x3_direct` | minor | 551.814 | 698.942 | +26,7% |
| | o3-edge | 411.831 | 411.829 | 0,0% |

## Parâmetros fixos

Ficam fixos na configuração gem5 e documentados como limitação, sem campo no YAML. O clock é campo (`cpu.clock`), mas todos os cenários usam 1GHz.

| Parâmetro | Valor | Onde |
| --- | --- | --- |
| Linha de cache | 64 bytes | Padrão do gem5 (`cache_line_size`) |
| Latências da L1 (tag, dados, resposta) | 2 ciclos | `make_cache` |
| Latências da L2 | 10 ciclos | `make_cache` |
| MSHRs e alvos por MSHR | 16 e 20, em todos os níveis | `make_cache` |
| Substituição | LRU | Padrão do gem5 |
| Prefetcher | Nenhum | Padrão do gem5 |
| Inclusão da L2 | `mostly_incl` | Padrão do gem5 |
| DRAM | DDR4-2400, `DDR4_2400_8x8` (1 canal, 2 ranks, 8 chips por rank) | `MemCtrl` |
| Latência da memória `simple` | 30ns | Padrão do gem5; fora dos cenários |
| Preditor de desvios | Torneio, na minor e nas O3 | Padrão do gem5 |
| Larguras e unidades da `o3-edge` | Tabela acima | `O3_EDGE` |
| Latência do `mul` e das demais classes | Padrões do gem5 (`mul` = 3) | Unidades padrão |

Mudar qualquer um deles exige editar `configs/gem5/se_riscv_configurable.py`. Mudanças assim devem ser registradas como um novo cenário, não feitas silenciosamente.

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_config.py` | `scenario` (expansão, nome desconhecido com sugestão, conflito com `cache`/`memory`), `cpu.custom_latency` (faixa, recusa na atomic e timing), `benchmark.cache_state` (recusa sem caches e sem ROI), `o3-edge` nos argumentos do gem5, os quatro cenários do arquivo | `make test` |
| `tests/test_metric.py` | A latência não entra na chave de ref e rvv (uma ref pareia com a custom de cada latência), caches frias e aquecidas não se misturam, rótulos `custom@lat6` e `l1-l2,cold` | `make test` |
| `tests/test_scenarios_e2e.py` | Latência pelo `insn_latency` (minor, o3, o3-edge), fc S nos quatro cenários de memória, caches frias (timing e o3-edge), parâmetros e IPC da `o3-edge` × `o3` | `make e2e-test` |
| `tests/test_validation.py::test_variants_pass_on_detailed_cpus` | As três variantes das sete operações em S, nas CPUs timing, minor e o3-edge, no cenário `l1-l2`, com `mismatches=0` e o checksum da atomic | `make validate` |

## Limitações

- As medições desta página são ilustrações de 26/10/2026, não resultados da campanha, que depende da matriz (RCB-22) e da execução em lote (RCB-19).
- A tabela "o que cabe" foi medida só na variante de referência. As três variantes têm os mesmos dados, mas os padrões de acesso diferem.
- Nas CPUs `timing`, `minor` e `o3-edge`, a validação roda só os tamanhos S, pelo tempo de simulação. As quatro operações afetadas pelo defeito da RVV na `o3-edge` foram conferidas também em L, fora dos testes.
- A latência configurável vale para as três instruções de `CnnMult` juntas. Uma latência diferente para `cnn.rqnt` exigiria outra classe.
- A unidade própria de `CnnMult` na Minor muda a disputa com o `mul` em relação ao padrão do fork (unidade compartilhada).
- Com `cold`, o gem5 drena o sistema antes de esvaziar as caches, então a ROI começa com o pipeline vazio. Com `warm`, ela começa logo depois das m5ops, que também esvaziam o pipeline por serem serializantes.
