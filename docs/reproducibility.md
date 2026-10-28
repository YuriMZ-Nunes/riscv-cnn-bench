# Reprodução

Como rodar de novo os experimentos do TCC e conferir o resultado com os dados publicados: um exemplo rápido, uma combinação avulsa e a matriz completa. Antes, siga [installation.md](installation.md). Os dados publicados estão em [data.md](data.md).

| Parte | Situação |
| --- | --- |
| Exemplo rápido (`campaigns/exemplo.yaml`) | Existente; 9 simulações em 17 s com 4 tarefas |
| Matriz completa (`campaigns/final.yaml`) | Existente; rodou em 27/10/2026 (2 h 52 min com 4 tarefas, mais a validação) |
| Comparação com os dados publicados | Conferida em 9 combinações da campanha final, sem nenhuma diferença ([abaixo](#reprodução-conferida)) |
| gem5 recompilado ou outro host | Não testado ([limitações](#limitações)) |

## O que se reproduz

O gem5 é determinístico. Com as mesmas entradas, uma simulação repete o `stats.txt` inteiro, menos as estatísticas do host (`hostSeconds`, `hostMemory` e as taxas por segundo real), e a mesma linha `RESULT`. Isso foi conferido em 12 repetições do piloto ([pilot.md](pilot.md#determinismo)) e, na RCB-26, em 9 combinações da campanha final rodadas de novo com o código atual e uma imagem reconstruída.

"As mesmas entradas" são:

| Entrada | Onde fica registrada |
| --- | --- |
| O binário do benchmark | `binary_sha256` no `metadata.json`. Sai igual com o mesmo código e o mesmo compilador ([container.md](container.md)) |
| O executável do gem5 | `gem5_sha256` e o commit do fork em `gem5_repository` ([environment.md](environment.md)) |
| A configuração | `experiment.resolved` no `metadata.json`; numa campanha, a combinação e a chave em `plan.json` |
| O comprimento do caminho da pasta da execução | O binário roda a partir de `<pasta>/inputs/`, e esse caminho entra no `argv` do programa simulado. Outro comprimento desloca a pilha e muda os ciclos em cerca de 0,04 % ([pilot.md](pilot.md#determinismo)) |

O que muda de uma execução para outra: as estatísticas do host, as durações e datas do `metadata.json` e o cabeçalho do gem5 no `stdout.log`.

## Exemplo rápido: uma operação, um cenário

`campaigns/exemplo.yaml` roda a FC no tamanho S, no cenário `l1-l2`: as três variantes nas CPUs timing e minor, a personalizada com latência 6 e o contraste `-O2` × `-O3`, num total de 9 simulações.

```bash
make campaign MATRIX=campaigns/exemplo.yaml JOBS=4   # simulações em results/campaigns/exemplo/
make report DIR=results/campaigns/exemplo            # report/runs.csv e pairs.csv
make plot DIR=results/campaigns/exemplo              # figures/
make analyze DIR=results/campaigns/exemplo           # analysis/tables.md
make relatorio DIR=results/campaigns/exemplo         # relatorio.html
xdg-open results/campaigns/exemplo/relatorio.html
```

Em 27/10/2026, numa pasta de `build/`, as 9 simulações levaram 17 s, e as tabelas, os gráficos e a página mais 12 s. O fim esperado de cada etapa:

```text
Sessão: 0 já concluída(s), 9 executada(s), 9 concluída(s), 0 com problema.
  runs.csv: 9 execução(ões), 9 válida(s), 9 valendo (current), 0 com checksum divergente
  pairs.csv: 11 par(es), 0 rejeitado(s)
```

Para uma só simulação: `make run EXPERIMENT=experiments/fc_s.yaml` e depois `make stats RUN=<pasta da execução>` ([experiments.md](experiments.md)).

## Matriz completa

```bash
make campaign MATRIX=campaigns/final.yaml JOBS=4     # validação e 620 simulações
make campaign-status MATRIX=campaigns/final.yaml     # estado de cada combinação
make campaign-audit DIR=results/campaigns/final      # vale como resultado?
make report DIR=results/campaigns/final
make plot DIR=results/campaigns/final
make analyze DIR=results/campaigns/final
make relatorio DIR=results/campaigns/final
```

- **Tempo.** A validação de equivalência (`validate: true` na matriz) leva cerca de 10 min. As 620 simulações levaram 2 h 52 min com 4 tarefas. `make campaign-estimate` estima o tempo noutra máquina a partir de execuções medidas nela ([matrix.md](matrix.md)).
- **Interrupção.** Ctrl+C para a campanha. O mesmo comando retoma, sem refazer as combinações concluídas ([campaigns.md](campaigns.md)).
- **Árvore limpa.** Não mude nada no repositório enquanto a campanha roda. Cada execução grava o `git status` no início, e uma execução com `dirty: true` não passa na auditoria ([campaigns.md](campaigns.md#árvore-suja)).
- **Disco.** Cerca de 0,7 GB em `results/campaigns/final/`.

O que se espera, como na campanha publicada ([data.md](data.md#o-que-rodou)): auditoria sem problemas, 620 execuções válidas no `runs.csv`, 734 pares no `pairs.csv`, nenhum rejeitado, e 51 figuras. A pasta padrão, `results/campaigns/final`, é a mesma da campanha original. Por isso os caminhos têm o mesmo comprimento, e os ciclos devem sair iguais.

## Conferir com os dados publicados

1. **Baixar e conferir o pacote.** Ele está no Zenodo ([10.5281/zenodo.23698495](https://doi.org/10.5281/zenodo.23698495)) e na release [`dados-v1`](https://github.com/YuriMZ-Nunes/riscv-cnn-bench/releases/tag/dados-v1):

   ```bash
   curl -LO https://github.com/YuriMZ-Nunes/riscv-cnn-bench/releases/download/dados-v1/riscv-cnn-bench-dados-v1.tar.gz
   tar -xzf riscv-cnn-bench-dados-v1.tar.gz
   cd riscv-cnn-bench-dados-v1 && sha256sum -c SHA256SUMS
   ```

2. **Comparar instruções e ciclos de todas as combinações.** Com o `runs.csv` publicado (`campanhas/final/report/runs.csv` no pacote) e o da sua reprodução, dentro do container (`make shell`, depois `uv run python`):

   ```python
   import pandas as pd

   publicado = pd.read_csv("<pacote>/campanhas/final/report/runs.csv")
   reproduzido = pd.read_csv("results/campaigns/final/report/runs.csv")
   juntos = publicado[publicado.current].merge(
       reproduzido[reproduzido.current], on="experiment", suffixes=("_pub", "_rep")
   )
   diferentes = juntos[(juntos.insts_pub != juntos.insts_rep) | (juntos.cycles_pub != juntos.cycles_rep)]
   print(len(juntos), "combinações comparadas,", len(diferentes), "com instruções ou ciclos diferentes")
   ```

   O pacote precisa estar dentro da pasta do projeto, por exemplo em `build/`, para o container enxergá-lo.

3. **Comparar o `stats.txt` inteiro de uma combinação:**

   ```python
   from pathlib import Path

   from riscvcnnbench.parser import stats_differences

   publicada = Path("<pacote>/campanhas/final/runs/<nome>/<run_id>")
   reproduzida = Path("results/campaigns/final/runs/<nome>/<run_id>")
   compared, differences = stats_differences(
       (publicada / "gem5" / "stats.txt").read_text(encoding="utf-8"),
       (reproduzida / "gem5" / "stats.txt").read_text(encoding="utf-8"),
   )
   print(compared, "estatísticas comparadas,", len(differences), "diferenças")
   ```

Os dois trechos foram testados em 27/10/2026 sobre a reprodução descrita abaixo.

### Uma combinação avulsa

Para conferir uma combinação sem rodar a matriz, use o YAML dela, gerado pela campanha (`campanhas/final/experiments/<nome>.yaml` no pacote, ou `results/campaigns/final/experiments/` depois de um `make campaign`). Copie o YAML e troque `output.dir` por uma pasta com o caminho do **mesmo comprimento** de `results/campaigns/final`. Por exemplo, troque `results/campaigns/final/runs/<nome>` por `build/rcb26-repro/final/runs/<nome>`: as duas partes trocadas, `results/campaigns` e `build/rcb26-repro`, têm 17 caracteres. Depois rode `make run EXPERIMENT=<cópia>.yaml`. Assim, a combinação não se mistura com as da campanha, e os ciclos não mudam pelo caminho.

## Reprodução conferida

Em 27/10/2026, 9 combinações da campanha final rodaram de novo, uma de cada vez, como descrito em [Uma combinação avulsa](#uma-combinação-avulsa):

- **Código:** o commit `12af7d4` (a `main` depois da RCB-27), com a árvore limpa. A campanha publicada é do `06fe772`.
- **Imagem:** `localhost/riscv-cnn-bench:rcb27`, reconstruída do zero ([container.md](container.md#verificação-num-container-limpo)).
- **gem5:** o mesmo executável da campanha (`c966242f…`).
- **Pasta:** `build/rcb26-repro/final`, de mesmo comprimento que `results/campaigns/final`.

| Combinação | CPU | Estatísticas comparadas | Diferenças |
| --- | --- | ---: | ---: |
| `fc_s__ref__timing__sem-cache` | timing | 1.472 | 0 |
| `conv3x3_direct_s__custom__minor__l1-l2` | minor | 2.352 | 0 |
| `conv3x3_direct_s__custom__minor__l1-l2__O3` | minor | 2.438 | 0 |
| `conv3x3_im2col_s__rvv__minor__l1-l2` | minor | 2.463 | 0 |
| `fc_s__custom__minor__l1-l2__lat6` | minor | 2.224 | 0 |
| `pointwise1x1_l__custom__minor__l1-l2` | minor | 2.504 | 0 |
| `depthwise3x3_s__rvv__o3-edge__reduzido` | o3-edge | 3.449 | 0 |
| `maxpool2x2_s__custom__o3-edge__l1` | o3-edge | 3.058 | 0 |
| `requant_relu_l__ref__o3-edge__reduzido` | o3-edge | 3.506 | 0 |

Em todas, o binário (`binary_sha256`) e a linha `RESULT` foram os mesmos da campanha publicada, e o `stats.txt` foi idêntico fora das estatísticas do host: 23.466 estatísticas, nenhuma diferença. As 9 cobrem as três variantes, as três CPUs com tempo, os quatro cenários, S e L, a latência 6 e o `-O3`. Também mostram que as mudanças do código entre o `06fe772` e o `12af7d4` não mudaram os binários nem os resultados dessas combinações.

## Limitações

- **9 de 620.** A comparação completa exige rodar a matriz inteira (cerca de 3 h).
- **O mesmo executável do gem5.** Um gem5 recompilado do mesmo commit tem outro hash ([environment.md](environment.md#compilar-e-conferir)). Os resultados deveriam ser os mesmos, mas isso não foi testado.
- **Um só host.** Tudo rodou num Fedora 44 x86-64. Outros hosts não foram testados.
- **O comprimento do caminho entra nos ciclos.** Reproduzir numa pasta com caminho de outro comprimento pode mudar os ciclos em cerca de 0,04 %.
- **A imagem das campanhas publicadas não foi registrada** nas execuções ([data.md](data.md#limitações)). A reconstruída gera o mesmo binário nas combinações conferidas. Versões fixadas do apt podem sumir do Ubuntu ([container.md](container.md#versões-fixadas-e-o-que-fazer-quando-uma-some)).
