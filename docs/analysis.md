# Análise dos resultados

Resposta à pergunta da proposta com os dados da campanha final ([data.md](data.md)): *como as instruções personalizadas afetam a quantidade de instruções executadas, o número de ciclos e o IPC das operações de CNN, em diferentes configurações de cache e memória, tendo a RVV como comparação* (RCB-25).

Os números deste documento saem de `riscvcnnbench analyze results/campaigns/final`, que grava as tabelas em `results/campaigns/final/analysis/`: um CSV por tabela e todas juntas em `tables.md`. Lá estão as tabelas completas, com todas as CPUs, cenários e pares; aqui ficam os recortes que sustentam cada conclusão. As figuras da mesma campanha estão em `results/campaigns/final/figures/` ([plots.md](plots.md)). Os dados, com o `report/`, estão publicados com o DOI [10.5281/zenodo.23698495](https://doi.org/10.5281/zenodo.23698495); as tabelas podem ser refeitas a partir deles.

| Parte | Situação |
| --- | --- |
| Tabelas da análise: `riscvcnnbench analyze` (`src/riscvcnnbench/analysis.py`) | Existente |
| Análise da campanha final (este documento) | Existente, 27/10/2026 |
| Escolha das tabelas e figuras que vão para o texto do TCC | Planejado (RCB-28) |

## Resumo

- **Instruções.** A custom reduz as instruções da região de interesse de 2,0× (requantização) a 12,6× (maxpool L). Nas operações com MAC, a redução vai de 3,5× (conv direta S) a 9,2× (FC L). A RVV reduz mais que a custom em 11 das 14 combinações de operação e tamanho; a custom reduz mais na conv direta (S e L) e na pointwise S.
- **Ciclos.** No cenário de referência (`l1-l2`), o speedup em ciclos da custom sobre a ref vai de 1,6× (requantização na timing) a 22,9× (maxpool L na o3-edge). Nas operações com MAC, de 3,6× (FC L na o3-edge) a 10,1× (pointwise L na o3-edge).
- **Quando instruções viram ciclos.** Na timing, o speedup acompanha a redução de instruções: a eficiência S_C/R_I fica entre 0,78 e 1,20 em S. Na minor e na o3-edge, a custom muitas vezes executa com IPC maior que a ref, e o speedup passa da redução de instruções (eficiência até 1,83 com cache). Nas operações limitadas pela memória, ele fica bem abaixo dela (até 0,39).
- **Memória.** Quando os dados não cabem nas caches, as faltas que vão à DRAM são praticamente as mesmas nas três variantes, e a custom, com muito menos instruções, fica presa a elas. Na FC L, cujos pesos vêm da DRAM em todos os cenários com cache, a eficiência cai para 0,39 a 0,71; no maxpool L, os ciclos da custom crescem 1,4 a 3,0 vezes no `l1` e no `reduzido` em relação ao `l1-l2`, contra 1,03 a 1,12 da ref.
- **Latência.** Com latência 6 em vez de 3, os ciclos da custom sobem até 42,6% na minor (requantização) e pouco na o3-edge: até 3,3% em 5 das 7 operações, em todos os cenários, e até 10,7% na im2col e 11,9% na FC.
- **Compilador.** O `-O3` não muda a ref (menos de 1% em instruções e ciclos). Na custom, tira 6,9% das instruções da conv direta sem mudar os ciclos e piora a im2col (+6,4% de instruções, +23,1% de ciclos), o que baixa o speedup dela de 5,32× para 4,32×.
- **Hipóteses.** A 1 foi parcialmente refutada, a 2 foi confirmada e a 3 foi confirmada para a timing e a o3-edge e refutada para a minor com latência 3 ([Hipóteses](#hipóteses)).

## Dados e método

- **Execuções.** As 620 da campanha final, todas válidas (`mismatches=0` e o mesmo checksum entre as variantes). A análise usa as 616 com `-O2` e os 728 pares de variantes com `-O2`; as 4 com `-O3` entram só no [contraste de compilador](#compilador). Uma execução por configuração basta, porque o gem5 é determinístico ([pilot.md](pilot.md#determinismo)).
- **R_I**, redução de instruções: instruções da região de interesse da base dividido pelas da outra variante.
- **S_C**, speedup em ciclos: ciclos da base dividido pelos da outra variante.
- **Eficiência S_C/R_I**: é a razão entre o IPC da outra variante e o da base. Mostra quanto da redução de instruções vira redução de ciclos. Vale 1 quando vira toda, fica acima de 1 quando a outra variante executa com IPC maior e abaixo de 1 quando executa com IPC menor.
- **Instruções invariantes.** As instruções da região de interesse são as mesmas em todas as CPUs e cenários, nas 14 combinações de operação e tamanho. Então R_I depende só da operação, do tamanho e das variantes.
- **Cenários** ([scenarios.md](scenarios.md#o-que-cabe-em-cada-nível)):
  - no `l1` e no `l1-l2`, os dados S cabem na L1d de 32 KiB;
  - no `l1-l2`, os dados L cabem na L2 de 256 KiB, menos os da FC L (515 KiB);
  - no `reduzido` (L1d de 4 KiB e L2 de 32 KiB), os dados S só cabem na L2, e os L não cabem em nada;
  - no `sem-cache`, instruções e dados vêm da DDR4;
  - o `l1-l2` é o cenário de referência.

## Instruções

Redução de instruções (R_I) e instruções por MAC (por elemento no maxpool e na requantização), da tabela de instruções:

| Operação | Tam. | ref→custom | ref→rvv | custom→rvv | ref por MAC | custom por MAC | rvv por MAC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `conv3x3_direct` | S | 3,47 | 2,48 | 0,71 | 8,48 | 2,44 | 3,42 |
| | L | 4,64 | 4,40 | 0,95 | 7,75 | 1,67 | 1,76 |
| `conv3x3_im2col` | S | 4,75 | 5,05 | 1,06 | 7,88 | 1,66 | 1,56 |
| | L | 6,01 | 7,89 | 1,31 | 7,40 | 1,23 | 0,94 |
| `depthwise3x3` | S | 6,08 | 21,60 | 3,55 | 13,23 | 2,18 | 0,61 |
| | L | 6,23 | 23,55 | 3,78 | 13,55 | 2,18 | 0,58 |
| `pointwise1x1` | S | 6,48 | 6,31 | 0,97 | 7,54 | 1,16 | 1,20 |
| | L | 7,14 | 8,93 | 1,25 | 7,27 | 1,02 | 0,81 |
| `maxpool2x2` | S | 11,14 | 16,61 | 1,49 | 6,95 | 0,62 | 0,42 |
| | L | 12,65 | 33,35 | 2,64 | 6,86 | 0,54 | 0,21 |
| `requant_relu` | S | 2,00 | 18,90 | 9,46 | 12,01 | 6,01 | 0,64 |
| | L | 2,00 | 19,16 | 9,58 | 12,00 | 6,00 | 0,63 |
| `fc` | S | 9,12 | 15,41 | 1,69 | 7,04 | 0,77 | 0,46 |
| | L | 9,23 | 16,33 | 1,77 | 7,02 | 0,76 | 0,43 |

Leitura da tabela:

- **A ref custa de 7 a 8,5 instruções por MAC** nas operações com produto escalar, e 13,2 a 13,6 na depthwise, em que os taps de um canal não são contíguos.
- **A custom chega perto de 1 instrução por MAC** na FC (0,76 a 0,77) e na pointwise (1,02 a 1,16), onde o laço interno é só `ld`, `ld` e `cnn.dot8`. Na conv direta S, com `Cin` = 8, cada tap tem um único `cnn.dot8`, e o controle do laço de taps pesa: 2,44 instruções por MAC, contra 1,67 em L (`Cin` = 16) ([kernels.md](kernels.md#três-variantes)). Na im2col, a montagem do buffer é cópia e não usa as instruções novas.
- **A depthwise usa uma instrução menos densa** (`cnn.dwmac`, 2 MACs por instrução, contra 8 do `cnn.dot8`), mas a ref dela é a mais cara, e a redução fica em 6,1 a 6,2×.
- **A requantização da custom só reduz 2×**: ela continua com um `lw` e um `sb` por elemento, sem desenrolar o laço. A RVV processa 32 elementos por bloco e reduz 19×.
- **O tamanho L reduz mais que o S** em todas as operações das duas variantes, menos na requantização da custom (2,00 nos dois): o controle dos laços pesa menos em L.
- **A RVV reduz mais que a custom** em 11 das 14 combinações. A custom reduz mais na conv direta (S e L) e na pointwise S. A explicação provável, não medida em separado, é que a dimensão contígua (`Cin` de 8 a 32) é curta para o vetor de 256 bits, e cada saída exige uma redução horizontal.

## Ciclos e IPC

Speedup em ciclos (S_C) no cenário de referência `l1-l2`, por CPU. A custom tem latência 3, igual à do `mul`.

| Operação | Tam. | R_I custom | S_C custom timing | minor | o3-edge | R_I rvv | S_C rvv timing | minor | o3-edge |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `conv3x3_direct` | S | 3,47 | 4,16 | 5,02 | 5,28 | 2,48 | 2,87 | 1,92 | 2,99 |
| | L | 4,64 | 5,49 | 6,80 | 6,77 | 4,40 | 5,31 | 3,88 | 6,04 |
| `conv3x3_im2col` | S | 4,75 | 3,99 | 5,32 | 5,61 | 5,05 | 4,08 | 4,86 | 4,83 |
| | L | 6,01 | 4,96 | 6,00 | 6,61 | 7,89 | 6,24 | 5,76 | 4,88 |
| `depthwise3x3` | S | 6,08 | 5,29 | 6,85 | 5,70 | 21,60 | 24,52 | 12,46 | 14,15 |
| | L | 6,23 | 5,38 | 7,02 | 5,84 | 23,55 | 25,97 | 13,08 | 14,64 |
| `pointwise1x1` | S | 6,48 | 7,09 | 7,83 | 9,14 | 6,31 | 6,73 | 4,93 | 7,90 |
| | L | 7,14 | 7,80 | 7,94 | 10,07 | 8,93 | 9,48 | 7,09 | 10,95 |
| `maxpool2x2` | S | 11,14 | 11,73 | 20,21 | 20,08 | 16,61 | 15,77 | 24,58 | 29,11 |
| | L | 12,65 | 11,39 | 16,01 | 22,89 | 33,35 | 23,52 | 25,94 | 59,84 |
| `requant_relu` | S | 2,00 | 1,60 | 2,03 | 2,35 | 18,90 | 14,70 | 5,35 | 5,26 |
| | L | 2,00 | 1,57 | 1,89 | 2,43 | 19,16 | 10,44 | 4,47 | 5,83 |
| `fc` | S | 9,12 | 8,63 | 7,83 | 6,09 | 15,41 | 18,55 | 10,29 | 8,95 |
| | L | 9,23 | 6,00 | 4,90 | 3,59 | 16,33 | 9,55 | 5,29 | 5,77 |

IPC da região de interesse no `l1-l2`, das tabelas de IPC (a timing não aparece: ela não modela latência de unidade funcional, e o IPC dela fica entre 0,19 e 0,42 em todas as execuções no `l1-l2`):

| Operação | Tam. | minor ref | custom | custom lat 6 | rvv | o3-edge ref | custom | custom lat 6 | rvv |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `conv3x3_direct` | S | 0,90 | 1,30 | 1,03 | 0,70 | 1,15 | 1,75 | 1,75 | 1,39 |
| `conv3x3_im2col` | S | 0,78 | 0,88 | 0,79 | 0,75 | 1,37 | 1,62 | 1,59 | 1,31 |
| `depthwise3x3` | S | 1,05 | 1,18 | 1,03 | 0,60 | 1,66 | 1,55 | 1,55 | 1,08 |
| `pointwise1x1` | S | 0,76 | 0,92 | 0,71 | 0,59 | 1,00 | 1,41 | 1,41 | 1,25 |
| `maxpool2x2` | S | 0,68 | 1,23 | 1,23 | 1,00 | 0,78 | 1,40 | 1,40 | 1,36 |
| `requant_relu` | S | 0,84 | 0,85 | 0,60 | 0,24 | 1,26 | 1,48 | 1,48 | 0,35 |
| `fc` | S | 0,78 | 0,67 | 0,66 | 0,52 | 1,73 | 1,16 | 1,08 | 1,01 |
| `fc` | L | 0,69 | 0,37 | 0,37 | 0,22 | 1,44 | 0,56 | 0,54 | 0,51 |

## Quando a redução de instruções vira redução de ciclos

Eficiência S_C/R_I da custom sobre a ref, resumida por CPU e tamanho, nos cenários com cache (`l1`, `l1-l2` e `reduzido`, 21 valores por linha: 7 operações × 3 cenários) e sem cache (7 valores):

| CPU | Tam. | Com cache: faixa | Mediana | Sem cache: faixa | Mediana |
| --- | --- | --- | --- | --- | --- |
| timing | S | 0,78–1,20 | 0,94 | 0,80–1,20 | 0,95 |
| | L | 0,58–1,18 | 0,82 | 0,81–1,19 | 0,95 |
| minor | S | 0,85–1,83 | 1,13 | 0,72–2,50 | 1,17 |
| | L | 0,46–1,47 | 0,98 | 0,75–2,30 | 1,11 |
| o3-edge | S | 0,67–1,82 | 1,18 | 0,73–1,74 | 1,11 |
| | L | 0,39–1,81 | 1,06 | 0,76–1,54 | 0,99 |

Três situações aparecem:

1. **A redução de instruções vira redução de ciclos (eficiência perto de 1).** É o caso da timing em S, em que cada instrução custa um ciclo mais o tempo dos acessos à memória: a eficiência fica entre 0,78 e 1,20. As diferenças em torno de 1 dependem do mix de instruções de cada variante.
2. **A custom executa com IPC maior que a ref (eficiência acima de 1).** Na minor e na o3-edge, a ref encadeia `lb`, `mul` e `add` por byte, e a custom troca isso por poucas instruções largas. No `l1-l2`, o IPC da custom passa o da ref na conv direta (minor: 1,30 contra 0,90; o3-edge: 1,75 contra 1,15), na pointwise e no maxpool (minor: 1,23 contra 0,68). Com isso, a eficiência chega a 1,44 a 1,52 na conv direta S e a 1,80 a 1,83 no maxpool S, no `l1` e no `l1-l2`.
3. **A custom executa com IPC menor (eficiência abaixo de 1).** É o caso da FC e da memória. Na o3-edge, a ref da FC tem IPC 1,73 em S, o mais alto entre as refs, provavelmente porque a execução fora de ordem sobrepõe as cargas e multiplicações independentes. A custom da FC fica em 1,16, e a eficiência em 0,67. Com latência 6, os ciclos dela quase não mudam (+0,6% na minor e +7,8% na o3-edge, em S), então o limite não é a latência do `cnn.dot8`; a causa exata não foi investigada. Os casos de memória estão na seção seguinte.

**Sem cache**, a eficiência em S fica perto de 1 na timing (0,80 a 1,20) e se espalha na minor (0,72 a 2,50). Nesse cenário, a busca de cada instrução também vai à DDR4. Na conv direta S na minor, a ref faz 1.460.884 leituras da DRAM e a custom 233.419, 6,3 vezes menos, contra R_I de 3,47; o S_C chega a 8,70. Os valores extremos da minor sem cache (eficiência de 2,50 na conv direta S e 2,11 no maxpool S) foram observados, mas não investigados.

## Onde a memória limita o ganho

As três variantes leem e escrevem os mesmos dados. Quando eles não cabem nas caches, as faltas absolutas são quase as mesmas nas três, mas a custom e a RVV executam muito menos instruções no meio delas. Uma parte maior dos ciclos vira espera pela memória, e o speedup cai abaixo da redução de instruções. Nas tabelas de faltas, isso aparece como faltas por mil instruções (MPKI) muito maiores na custom.

Ciclos em cada cenário relativos ao `l1-l2`, mesma CPU e variante, em L (tabela "Ciclos relativos ao l1-l2"). As operações em que os dados L não cabem fora do `l1-l2` (maxpool, requantização) e a FC, que não cabe em nenhum:

| Operação L | Variante | timing `l1` | `reduzido` | minor `l1` | `reduzido` | o3-edge `l1` | `reduzido` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `maxpool2x2` | ref | 1,03 | 1,06 | 1,08 | 1,12 | 1,04 | 1,06 |
| | custom | 1,41 | 1,63 | 2,38 | 3,04 | 1,86 | 2,28 |
| | rvv | 1,82 | 2,27 | 2,80 | 3,64 | 1,90 | 2,23 |
| `requant_relu` | ref | 1,13 | 1,16 | 1,24 | 1,36 | 1,22 | 1,36 |
| | custom | 1,15 | 1,25 | 1,43 | 1,66 | 1,40 | 1,76 |
| | rvv | 2,11 | 2,59 | 1,86 | 2,22 | 1,27 | 1,67 |
| `fc` | ref | 0,98 | 1,00 | 0,95 | 1,00 | 0,93 | 1,00 |
| | custom | 0,90 | 1,00 | 0,82 | 0,98 | 0,70 | 0,97 |
| | rvv | 0,83 | 0,99 | 0,80 | 0,98 | 0,73 | 0,94 |

- **Maxpool L.** No `l1-l2`, os 160 KiB cabem na L2, e o speedup da custom é de 11,4× a 22,9×. Sem a L2 (`l1`) ou com a L2 de 32 KiB (`reduzido`), as 2.560 linhas vêm da DRAM: no `reduzido`, a L2 tem de 2.570 a 2.572 faltas nas três variantes (minor). A ref quase não sente (1,03 a 1,12): tem 899 mil instruções para executar entre as faltas. A custom, com 71 mil, fica 1,4 a 3,0 vezes mais lenta. O speedup cai para 5,9× a 10,6× no `reduzido` (eficiência de 0,46 a 0,84). Na L1d, a custom tem 72 faltas por mil instruções, contra 3,7 a 4,4 da ref. Isso explica por que o speedup não segue a ordem dos cenários: o `l1-l2` fica acima do `l1` e do `reduzido` nas três CPUs, e o `sem-cache` fica acima de todos na timing (13,0×) e na minor (25,6×). O ganho depende de onde os dados estão, e não só de quantas instruções a custom tira.
- **Requantização L.** O mesmo efeito, menor: os ciclos da custom crescem 1,15 a 1,76 vez fora do `l1-l2`, contra 1,13 a 1,36 da ref, e a eficiência no `reduzido` cai para 0,72 a 0,94.
- **FC L** ([hipótese 2](#hipóteses)). Os pesos (512 × 1.024 int8, 515 KiB) não cabem na L2 de 256 KiB: a L2 tem 8.234 a 8.256 faltas no `l1-l2` e no `reduzido`, nas três variantes, que é o número de linhas dos dados. Na L1d, a custom tem 20,7 faltas por mil instruções, contra 2,2 da ref. A eficiência fica em 0,65 a 0,71 na timing, 0,53 a 0,62 na minor e 0,39 a 0,51 na o3-edge. O `l1`, sem L2, é até mais rápido que o `l1-l2` (0,70 a 0,98), provavelmente porque, sem reuso, a L2 só acrescenta a latência da consulta a cada falta.
- **Operações limitadas pelo cálculo.** Na conv direta, na im2col e na pointwise L, os ciclos variam pouco entre `l1`, `l1-l2` e `reduzido`: no máximo 1% na ref, 8% na custom e 14% na RVV. Isso vale mesmo no `reduzido`, em que a conv direta L tem cerca de 65 mil faltas na L1d. O speedup varia pouco entre esses cenários (conv direta L na minor: 6,34 a 6,80).
- **Depthwise L no `reduzido`.** As cargas largas também reduzem faltas quando a janela da operação não cabe na L1d de 4 KiB: 239.308 faltas na ref, 41.491 na custom e 9.979 na RVV (minor).
- **S.** Os dados cabem na L1d ou na L2 em todos os cenários com cache, e o speedup da custom muda pouco entre eles. A exceção é o maxpool S no `reduzido`, que cai de 20,2× para 15,2× na minor.

## Sensibilidade à latência

Aumento dos ciclos da custom com a latência pessimista (6) em relação à igual à do `mul` (3), da tabela de latência. Na timing não há latência de unidade funcional, e o grupo de latência não a inclui.

| Operação | Tam. | minor: ciclos (`l1-l2`) | minor: S_C 3 → 6 | o3-edge: ciclos (`l1-l2`) | o3-edge: S_C 3 → 6 |
| --- | --- | --- | --- | --- | --- |
| `conv3x3_direct` | S | +26,7% | 5,02 → 3,96 | +0,0% | 5,28 → 5,28 |
| | L | +25,6% | 6,80 → 5,42 | +0,0% | 6,77 → 6,77 |
| `conv3x3_im2col` | S | +11,0% | 5,32 → 4,79 | +2,1% | 5,61 → 5,50 |
| | L | +10,3% | 6,00 → 5,44 | +4,9% | 6,61 → 6,30 |
| `depthwise3x3` | S | +14,7% | 6,85 → 5,98 | +0,0% | 5,70 → 5,70 |
| | L | +13,8% | 7,02 → 6,16 | +0,0% | 5,84 → 5,84 |
| `pointwise1x1` | S | +29,5% | 7,83 → 6,05 | +0,0% | 9,14 → 9,14 |
| | L | +21,1% | 7,94 → 6,56 | +0,0% | 10,07 → 10,07 |
| `maxpool2x2` | S | +0,0% | 20,21 → 20,21 | +0,0% | 20,08 → 20,08 |
| | L | +0,0% | 16,01 → 16,01 | +0,0% | 22,89 → 22,89 |
| `requant_relu` | S | +42,5% | 2,03 → 1,42 | +0,0% | 2,35 → 2,35 |
| | L | +34,6% | 1,89 → 1,41 | +0,0% | 2,43 → 2,43 |
| `fc` | S | +0,6% | 7,83 → 7,78 | +7,8% | 6,09 → 5,65 |
| | L | +0,1% | 4,90 → 4,90 | +3,1% | 3,59 → 3,48 |

- **Na minor, a latência pesa** onde a instrução da classe `CnnMult` está no caminho crítico do laço: requantização (+34,6 a +42,5%), pointwise (+21,1 a +29,5%) e conv direta (+25,6 a +26,7%). O speedup cai 9 a 30%, mas continua acima de 1,4× em todas e acima de 3,9× nas operações com MAC.
- **Na o3-edge, a latência fica escondida**: no `l1-l2`, 0% em 5 das 7 operações, +2,1 a +4,9% na im2col e +3,1 a +7,8% na FC. No pior cenário, chega a 10,7% na im2col L e 11,9% na FC S.
- **O maxpool não muda**, porque o `cnn.max8` está na classe `IntAlu`, fora da `CnnMult`. É uma conferência de que a latência configurada afeta só as instruções da classe.
- **Sem cache, a latência some na minor**: o aumento fica entre −0,2% e +1,0% nas 14 combinações, porque a espera pela DDR4 domina.

## Compilador

Contraste `-O2` × `-O3` na minor, cenário `l1-l2`, nas duas operações em que o `-O3` mais mudou as instruções da custom ([matrix.md](matrix.md#conferência-do--o3)):

| Operação S | Variante | Instruções `-O2` → `-O3` | Ciclos `-O2` → `-O3` | R_I ref→custom | S_C ref→custom |
| --- | --- | --- | --- | --- | --- |
| `conv3x3_direct` | ref | 2.499.690 → 2.480.219 (−0,8%) | 2.769.311 → 2.786.388 (+0,6%) | 3,47 → 3,70 | 5,02 → 5,04 |
| | custom | 719.552 → 670.065 (−6,9%) | 551.814 → 552.910 (+0,2%) | | |
| `conv3x3_im2col` | ref | 2.324.694 → 2.323.414 (−0,1%) | 2.970.373 → 2.971.679 (+0,0%) | 4,75 → 4,46 | 5,32 → 4,32 |
| | custom | 489.465 → 520.953 (+6,4%) | 558.613 → 687.754 (+23,1%) | | |

O `-O3` não melhora a ref escalar: sem a extensão V no `-march` da ref, não há vetorização automática, e as mudanças ficam abaixo de 1%. Na custom, ele mexe no código em volta das instruções novas (as intrínsecas `.insn` são opacas para o compilador). Na conv direta, tira 6,9% das instruções, mas não muda os ciclos. Na im2col, acrescenta instruções e piora os ciclos em 23%. O ganho das instruções personalizadas não depende de um compilador mais agressivo, e o `-O3` pode até reduzi-lo. Com só duas operações, numa CPU e num cenário, isso é um contraste, não uma caracterização do compilador.

## Custom × RVV

S_C da custom para a RVV no `l1-l2` (acima de 1, a RVV é mais rápida):

| Operação | Tam. | timing | minor | o3-edge |
| --- | --- | --- | --- | --- |
| `conv3x3_direct` | S | 0,69 | 0,38 | 0,57 |
| | L | 0,97 | 0,57 | 0,89 |
| `conv3x3_im2col` | S | 1,02 | 0,91 | 0,86 |
| | L | 1,26 | 0,96 | 0,74 |
| `depthwise3x3` | S | 4,63 | 1,82 | 2,48 |
| | L | 4,83 | 1,86 | 2,50 |
| `pointwise1x1` | S | 0,95 | 0,63 | 0,86 |
| | L | 1,22 | 0,89 | 1,09 |
| `maxpool2x2` | S | 1,34 | 1,22 | 1,45 |
| | L | 2,06 | 1,62 | 2,61 |
| `requant_relu` | S | 9,17 | 2,64 | 2,23 |
| | L | 6,65 | 2,36 | 2,40 |
| `fc` | S | 2,15 | 1,32 | 1,47 |
| | L | 1,59 | 1,08 | 1,61 |

- **A RVV executa com IPC menor.** Cada instrução vetorial conta como uma, mas ocupa a unidade por vários ciclos e vira vários micro-ops (LMUL > 1). Na minor, a eficiência da RVV sobre a custom tem mediana de 0,61 a 0,65, e a vantagem dela em instruções encolhe ou se inverte.
- **A custom é mais rápida ou empata** na conv direta (todas as CPUs), na pointwise S, na im2col na minor e na o3-edge e na pointwise L na minor. São as operações de produto escalar com dimensão contígua curta, em que o `cnn.dot8` faz o mesmo que um bloco vetorial com menos instruções de controle.
- **A RVV é mais rápida** na depthwise (1,8 a 4,8×), na requantização (2,2 a 9,2×), no maxpool (1,2 a 2,6×) e na FC (1,1 a 2,2×). São as operações elemento a elemento, ou com muitos canais independentes, em que 32 faixas de 8 bits rendem mais que 8.
- **A minor é a CPU que mais penaliza a RVV**: na conv direta S, a custom é 2,6 vezes mais rápida (0,38).

## Hipóteses

As hipóteses da RCB-10, como foram formuladas na issue RCB-25:

| Hipótese | Resultado | Evidência |
| --- | --- | --- |
| 1. A maior redução de instruções ocorre em conv, pointwise e FC, e a menor na depthwise | **Parcialmente refutada.** FC (9,1 a 9,2×) e pointwise (6,5 a 7,1×) têm as maiores reduções entre as operações com MAC. A conv não: a direta (3,5 a 4,6×) e a im2col (4,7 a 6,0×) têm as menores. A depthwise (6,1 a 6,2×) fica acima das duas convs | [Instruções](#instruções): o controle do laço de taps com `Cin` pequeno pesa na conv direta, a montagem do buffer não é acelerada na im2col, e a ref da depthwise é a mais cara (13,2 a 13,6 instruções por MAC) |
| 2. Na FC L, que excede a L2, o speedup fica bem abaixo da redução de instruções | **Confirmada.** Com cache, o speedup é de 0,39 a 0,71 vez a redução de instruções (3,6× a 6,5× para R_I de 9,2×) | [Memória](#onde-a-memória-limita-o-ganho): 8.234 a 8.256 faltas na L2 nas três variantes, e 20,7 faltas por mil instruções na L1d da custom contra 2,2 da ref |
| 3a. Na timing, o speedup acompanha a redução de instruções em S | **Confirmada**, com desvio de até 22%: eficiência de 0,78 a 1,20 | [Eficiência](#quando-a-redução-de-instruções-vira-redução-de-ciclos) |
| 3b. Na minor, a latência e a unidade única reduzem o ganho | **Refutada com latência 3; confirmada com latência 6.** Com latência 3, o speedup na minor é maior que na timing em 6 das 7 operações, em S e em L (a exceção é a FC), e a eficiência chega a 1,83. Com latência 6, ele cai 9 a 30% e fica abaixo do da timing em 4 das 7 operações em S. O efeito de ter uma só unidade não foi isolado: a campanha não tem configuração com duas. Desde a RCB-33, `cpu.custom_units` permite essa medição ([scenarios.md](scenarios.md#unidades-e-pipeline)) | [Latência](#sensibilidade-à-latência) e [IPC](#ciclos-e-ipc) |
| 3c. Na o3, parte da latência é escondida | **Confirmada.** Na o3-edge, latência 6 custa 0% em 5 das 7 operações no `l1-l2` e no máximo 11,9% (FC S no `reduzido`) | [Latência](#sensibilidade-à-latência) |

## Trade-offs

| Escolha | Ganha | Perde ou depende de |
| --- | --- | --- |
| Instruções personalizadas | 3,5 a 12,6× menos instruções num núcleo escalar `rv64gc`, sem estado vetorial; 4 a 10× menos ciclos nas operações com MAC quando os dados estão nas caches; o melhor resultado na conv direta e na pointwise | Pouco na requantização (2×), enquanto ela continuar com uma carga e um armazenamento por elemento; latência no núcleo em ordem (até 30% do speedup com latência 6); memória quando os dados não cabem (FC L com 40 a 70% do ganho em instruções); custo de hardware não avaliado |
| RVV | Maior redução de instruções em 11 de 14 casos; muito melhor nas operações elemento a elemento (requantização, maxpool) e na depthwise | IPC menor, sobretudo na minor; perde da custom nas convs e na pointwise S; exige a unidade vetorial e os registradores de VLEN bits, de área não avaliada |
| Núcleo em ordem (minor) | Aproveita a custom (IPC dela acima do da ref) | Sensível à latência das instruções; penaliza a RVV |
| Fora de ordem de borda (o3-edge) | Esconde a latência da custom; os maiores speedups da custom na pointwise, na im2col e no maxpool L | A ref também melhora (IPC até 1,73), e o speedup da FC é o menor das três CPUs |
| Hierarquia de memória | Com os dados na L2 (`l1-l2`), o speedup do maxpool L na o3-edge é 22,9×, contra 12,9× no `l1` e 10,6× no `reduzido` | Sem lugar para os dados, o ganho da custom e da RVV encolhe mais que o da ref; uma L2 sem reuso (FC L) só acrescenta latência |
| `-O3` | Nada para a ref; −6,9% de instruções na conv direta custom | +23% de ciclos na im2col custom |

## Limitações

- **Modo SE do gem5**: sem sistema operacional; as chamadas de sistema são emuladas.
- **Latências fixas**: as de cache e DRAM são as do gem5. A latência das instruções personalizadas é uma suposição, avaliada em dois valores (3 e 6). Desde a RCB-32, latências, MSHRs, prefetcher e linha das caches são configuráveis ([scenarios.md](scenarios.md#ajustes-das-caches)), mas a campanha usou os padrões e não tem prefetcher.
- **Caminho da pasta**: reproduzir uma execução numa pasta com caminho de outro comprimento pode mudar os ciclos em cerca de 0,04% ([pilot.md](pilot.md#determinismo)).
- **O3 de borda**: a `o3-edge` foi configurada a partir das larguras e filas do MediumBOOM, sem corresponder a um núcleo comercial específico ([scenarios.md](scenarios.md)).
- **Contorno da redução RVV na O3CPU** do gem5 ([kernels.md](kernels.md#limitação-do-gem5-reduções-rvv-na-o3cpu)): a RVV reduz em LMUL 1 e soma o valor inicial no escalar, o que pode custar instruções que um simulador sem o defeito não pediria.
- **Classes de unidade diferentes**: as instruções personalizadas usam `CnnMult` e `IntAlu`, e a RVV usa as classes `Simd*` do gem5, com latências próprias.
- **Caches aquecidas** no início da região de interesse em toda a campanha; caches frias são uma opção do framework fora da matriz ([scenarios.md](scenarios.md)).
- **Referência sem Zbb**, compilada com `rv64gc`.
- **Compilador**: `-O2` como base e contraste mínimo, só `-O2` × `-O3`, em duas operações, uma CPU e um cenário.
- **MACs nominais** nas métricas por MAC das convoluções (decisão da RCB-17); o padding conta como MAC.
- **Tamanhos reduzidos**: dois tamanhos por operação, menores que camadas inteiras de redes reais; dados sintéticos; avaliação por operação, sem a rede inteira.
- **Sem validação em RTL**, nem estimativa de área ou energia: o custo de hardware das instruções e da unidade vetorial não entra na comparação.
- **Causas não investigadas**: o IPC da custom da FC, e os valores extremos da minor sem cache, ficam como observação.

O que estender a partir destas limitações, e o que cada extensão exigiria, está em [future.md](future.md).

## Reproduzir

```bash
uv run riscvcnnbench report results/campaigns/final    # runs.csv e pairs.csv
uv run riscvcnnbench analyze results/campaigns/final   # tabelas em results/campaigns/final/analysis/
```

Fora do container, `make analyze DIR=results/campaigns/final [FORCE=1]`. O `analyze` lê `<pasta>/report/` (ou `--input`) e grava em `<pasta>/analysis/` (ou `--output`); recusa sobrescrever sem `--force`. A seleção das execuções e dos pares é a do `plot`: válidas, valendo (`current`), com checksum consistente e com ciclos. Ficam no contexto comum: clock de 1 GHz e dados `random`.

| Arquivo | Conteúdo |
| --- | --- |
| `instructions.csv` | Por operação e tamanho: instruções e instruções por unidade de trabalho de cada variante, R_I dos três pares, e se as instruções foram iguais em todas as execuções (`invariant`) |
| `speedup.csv` | Por par, operação, tamanho, CPU e cenário: R_I, S_C e eficiência (S_C/R_I) |
| `variants.csv` | Por execução: instruções, ciclos, IPC, ciclos por trabalho, faltas na L1d e na L2, MPKI, leituras da DRAM e ciclos relativos ao `l1-l2` |
| `latency.csv` | Por operação, tamanho, CPU e cenário: ciclos da custom com latência 3 e 6, o aumento, e o S_C de cada uma |
| `compiler.csv` | Execuções com outras flags ao lado das com `-O2`: instruções, ciclos, R_I e S_C ref→custom |
| `tables.md` | Todas as tabelas em Markdown, com vírgula decimal |
| `analysis.json` | Versão do gerador, hash SHA-256 dos CSVs de entrada e número de linhas de cada tabela |

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_analysis.py` | Com CSVs sintéticos: R_I e invariância (inclusive com uma execução diferente), pares e eficiência com as rejeitadas e o `-O3` de fora, ciclos relativos ao `l1-l2`, IPC, faltas, latência, compilador, formatação dos números, os arquivos gravados com o hash das entradas, recusa sem `--force` e a CLI | `make test` |
