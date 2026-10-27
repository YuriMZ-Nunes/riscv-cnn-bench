# Experimento piloto

Uma versão reduzida da matriz final ([matrix.md](matrix.md)), rodada antes da campanha para achar problemas, medir o tempo real e confirmar o determinismo do gem5 (RCB-23). A matriz é [`campaigns/piloto.yaml`](../campaigns/piloto.yaml). Os resultados ficam em `results/campaigns/piloto/`, que o Git ignora, e são publicados junto com os da campanha final no pacote de dados ([data.md](data.md)).

| Parte | Situação |
| --- | --- |
| Piloto executado (64 combinações e 12 repetições), com CSV e gráficos | Existente, 27/10/2026 |
| Comparação de `stats.txt` sem o host (`parser.stats_differences`) e teste de determinismo | Existente |
| Estimativa da matriz final refeita com o piloto | Existente ([matrix.md](matrix.md#estimativa-de-tempo)) |
| Campanha final | Existente (RCB-24, 27/10/2026, [data.md](data.md)) |

## O que rodou

Depthwise e pointwise, em S e L, nas três variantes, com a custom nas latências 3 e 6, na minor e na o3-edge, em dois cenários: `l1-l2`, em que os dados cabem (S na L1d, L na L2), e `reduzido`, em que não cabem (S fora da L1d, L fora da L2). São 64 combinações. As duas operações foram escolhidas porque nunca tinham rodado em L numa CPU com tempo: a estimativa da RCB-22 amostrou só a conv direta e a FC.

```bash
make campaign MATRIX=campaigns/piloto.yaml JOBS=4
uv run riscvcnnbench report results/campaigns/piloto
uv run riscvcnnbench plot results/campaigns/piloto
```

Em 27/10/2026, com o commit `ecb7223` (o merge da RCB-22) e o fork do gem5 em `ce03244`, todas as 64 combinações terminaram com resultado válido em 16 min 54 s com 4 tarefas, das 13:39 às 13:55 UTC (`campaign.json`). A estimativa feita antes, com `campaign estimate`, previa 17,7 min.

O `report` deu 76 execuções, todas válidas e 64 valendo (`current`), sem checksum divergente, e 80 pares, nenhum rejeitado. O `plot` deu 28 figuras: 8 de variantes, 10 de speedup e 10 de R_I × S_C. As 12 execuções a mais são as repetições descritas abaixo.

## Tempo: previsto × medido

`campaign estimate` previu cada combinação a partir das medições da RCB-22. Nas 32 combinações L, todas pelo modelo, a razão medido/previsto ficou assim:

| Operação L | minor | o3-edge |
| --- | --- | --- |
| depthwise3x3 | 0,83–1,06 (média 0,90) | 0,84–1,05 (média 0,93) |
| pointwise1x1 | 1,02–1,14 (média 1,06) | 0,88–1,08 (média 0,94) |

Somadas, as 32 previstas pelo modelo deram 59,5 min previstos e 58,7 min medidos: razão 0,99. As 32 em S, que já tinham duração medida, deram 7,4 min contra 8,9 min, razão 0,83. É a variação de uma execução para outra no mesmo host, numa execução curta, em que build e início do gem5 pesam.

Com o piloto entre as medições, a estimativa da matriz final quase não muda: 11,34 h em série, cerca de 2,8 h com 4 tarefas ([matrix.md](matrix.md#estimativa-de-tempo)). O modelo, que nessas duas operações era interpolado entre a conv direta e a FC, errou o L delas em menos de 17% por combinação e em 1% na soma.

## IPC da o3-edge

A `o3-edge` decodifica e confirma 2 instruções por ciclo ([scenarios.md](scenarios.md#o3-de-borda-o3-edge)), então o IPC dela não passa de 2. No piloto, o IPC da região de interesse ficou entre 0,89 e 1,66, contra 0,50 a 1,18 na minor, nas mesmas combinações. A razão entre as duas CPUs ficou entre 1,30 e 2,12.

Isso é plausível para um núcleo de borda fora de ordem de 2 vias: fica abaixo do teto de 2 e acima da CPU em ordem. A O3 padrão do gem5 chegou a 5,1 na pointwise S ([scenarios.md](scenarios.md)). A configuração da RCB-18 se mantém.

| Faixa | o3-edge | minor |
| --- | --- | --- |
| ref | 0,997–1,661 | 0,757–1,047 |
| custom (latências 3 e 6) | 1,376–1,558 | 0,659–1,180 |
| rvv | 0,889–1,252 | 0,502–0,609 |

O IPC menor da RVV é esperado: cada instrução vetorial conta como uma, mas ocupa a unidade por vários ciclos e vira vários micro-ops. A latência 6 baixa o IPC da custom na minor, mas quase não muda o da o3-edge, que esconde parte da latência. É a hipótese H3, a ser analisada com a campanha (RCB-25).

## Determinismo

Doze combinações rodaram duas vezes com as mesmas entradas, com `riscvcnnbench run` sobre o experimento gerado pela campanha (`results/campaigns/piloto/experiments/<nome>.yaml`). Cobriram as duas operações, S e L, as três variantes, a latência 6, as duas CPUs e os dois cenários. Em todas:

- o binário compilado foi o mesmo (`binary_sha256`);
- o `stats.txt` foi idêntico, menos as estatísticas do host: 0 diferenças em 2.442 a 3.564 estatísticas comparadas por par;
- a saída do programa foi a mesma: a linha `RESULT` e o tick final.

O que muda de uma execução para outra é só o tempo do host: `hostSeconds`, `hostTickRate`, `hostMemory`, `hostInstRate` e `hostOpRate`, e as durações do `metadata.json`. Também muda o cabeçalho do gem5 no `stdout.log`: hora de início, host, pid e caminhos da pasta. Por isso `R = 1` basta na campanha, e uma execução repetida vale tanto quanto a primeira (`current` = a mais recente).

`parser.stats_differences` faz a comparação, e `tests/test_determinism_e2e.py` a repete em todo `make e2e-test`: a FC S, uma vez com a custom na minor, cenário `reduzido`, latência 6, e outra com a RVV na o3-edge, cenário `l1-l2`, rodam duas vezes.

## Problemas encontrados

| Problema | Consequência | Tratamento |
| --- | --- | --- |
| Arquivos do projeto foram editados durante a campanha | A proveniência é gravada no início de cada execução, com `git status --porcelain`; as 8 combinações que começaram depois das edições registraram `project.dirty: true` | As 8 rodaram de novo com a árvore limpa e são as que valem no `report` (as sujas ficam, marcadas como substituídas). Regra para a campanha final: nada muda na árvore enquanto ela roda; matrizes avulsas ficam em `build/`. Tarefa proposta: o `campaign run` avisar quando a árvore está suja e o `campaign status` contar as concluídas com `dirty: true` |
| O `stdout.log` muda entre execuções iguais | O cabeçalho do gem5 tem hora, host, pid e caminhos | Esperado; a comparação usa o `stats.txt` sem o host e a saída do programa |
| A duração de uma execução curta varia | As 32 em S levaram 17% menos que a medição anterior | Dentro da incerteza da estimativa; a campanha cabe com folga |

Nenhuma simulação falhou, nenhum resultado divergiu entre as variantes, e nada levou a mudar a matriz final.

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_parser.py` (`test_stats_differences_ignore_the_host`) | O tempo do host não conta como diferença; uma estatística diferente e um número de blocos diferente contam | `make test` |
| `tests/test_determinism_e2e.py` | Duas execuções iguais pelo `riscvcnnbench run` (custom na minor `reduzido` lat 6; rvv na o3-edge `l1-l2`): mesmo binário, mesmo `stats.txt` sem o host e mesma saída do programa | `make e2e-test` |

## Limitações

- O piloto cobriu duas das sete operações em L, só na minor e na o3-edge. As demais operações L e a timing continuam estimadas pelo modelo.
- O determinismo foi conferido no mesmo host e com o mesmo executável do gem5; outro host ou outro build não foi testado.
- Os resultados do piloto não são da campanha: servem para conferir o processo e o tempo, não como dados da análise.
