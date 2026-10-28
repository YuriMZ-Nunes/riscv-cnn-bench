# Tabelas de resultados (CSV)

`riscvcnnbench report` junta as execuções de uma pasta, que pode ser `results/` inteira ou uma campanha ([campaigns.md](campaigns.md)), em duas tabelas CSV (RCB-20):

| Arquivo | Uma linha por |
| --- | --- |
| `runs.csv` | Execução: identificação, configuração, linha `RESULT`, métricas brutas e derivadas da região de interesse, proveniência |
| `pairs.csv` | Par do `compare` ([results.md](results.md#comparações)): ref × custom, ref × rvv, custom × rvv e o contraste de compilador `-O2` × `-O3` |

Os CSVs são gerados só a partir das pastas de execução, sem edição manual, e podem ser refeitos a qualquer momento. Nada é descartado. Execuções com falha, com resultado inválido, com checksum diferente das outras ou substituídas por uma mais recente aparecem, marcadas nas colunas `problem`, `current` e `checksum_consistent`.

| Parte | Situação |
| --- | --- |
| `src/riscvcnnbench/report.py`, `riscvcnnbench report`, `make report` | Existente |
| Gráficos a partir destes CSVs: `riscvcnnbench plot` | Existente (RCB-21, [plots.md](plots.md)) |
| Relatório HTML a partir destes CSVs: `riscvcnnbench relatorio` | Existente (RCB-35, [html_report.md](html_report.md)) |

## Gerar

```bash
uv run riscvcnnbench report results/campaigns/exemplo     # grava results/campaigns/exemplo/report/
uv run riscvcnnbench report results --output /tmp/tabelas
make report DIR=results/campaigns/exemplo [FORCE=1]      # fora do container
```

Por padrão os arquivos vão para `<pasta>/report/`. Se `runs.csv` ou `pairs.csv` já existem lá, o comando recusa e pede `--force`, que regrava os dois, ou outra pasta com `--output`. O resumo no fim:

```text
Gravado em build/rcb20-probe/exemplo2:
  runs.csv: 9 execução(ões), 9 válida(s), 9 valendo (current), 0 com checksum divergente
  pairs.csv: 11 par(es), 0 rejeitado(s)
```

Saída real de 26/10/2026, para a campanha de exemplo rodada numa pasta de `build/`.

## Formato

- UTF-8, separador vírgula, decimal com ponto e uma linha de cabeçalho com os nomes das colunas abaixo. Num LibreOffice ou Excel em português, escolha a vírgula como separador ao abrir.
- **Célula vazia = valor ausente**: cache que não existe, ciclos na CPU atomic, média sem eventos (0/0), métricas de uma execução sem `stats.txt` legível. Nunca 0. O motivo de cada ausência aparece em `riscvcnnbench stats <pasta>`.
- Verdadeiro e falso são `true` e `false`; listas, como as flags, são separadas por espaço.
- Números saem com a precisão completa, às vezes em notação científica (`2.3e-05`).
- Datas em ISO 8601, UTC.

Em Python, com o pandas (dependência do projeto):

```python
import pandas as pd

runs = pd.read_csv("results/campaigns/exemplo/report/runs.csv")
valid = runs[runs["problem"].isna() & runs["current"]]   # as que valem como resultado
pairs = pd.read_csv("results/campaigns/exemplo/report/pairs.csv")
pairs = pairs[pairs["problem"].isna()]
```

## `runs.csv`

### Identificação e situação

| Coluna | Significado |
| --- | --- |
| `run_id`, `path` | Identificador e pasta da execução |
| `campaign`, `groups` | Campanha e grupos, se a execução está em `<campanha>/runs/<nome>/` (lidos do `plan.json`); vazias fora de campanhas |
| `experiment` | `name` da configuração resolvida |
| `status` | `status` do `metadata.json` (`completed`, `failed`, `interrupted`...) |
| `diagnosis` | Tipo do diagnóstico de falha da RCB-08 (`build`, `benchmark`, `gem5`, `interrupted`...), vazio se concluída |
| `problem` | Por que a execução **não vale como resultado**: não concluída, `stats.txt` ilegível, sem linha `RESULT`, `mismatches` > 0. Vazio se vale |
| `current` | `true` para a execução que vale entre as da mesma identidade (mesma configuração resolvida, sem nome, descrição e pasta, e mesmo executável do gem5): a mais recente sem `problem`, ou a mais recente se nenhuma vale |
| `checksum_consistent` | `false` se o checksum difere do esperado para a mesma operação, parâmetros e dados: o mais frequente entre as execuções `ref` válidas ou, sem nenhuma, entre todas as válidas. Vazio sem checksum ou sem referência |

### Operação e configuração

| Coluna | Significado |
| --- | --- |
| `bench`, `variant`, `data` | Da linha `RESULT` (operação, variante, conjunto de dados); sem ela, operação e variante vêm do YAML |
| `size` | `S` ou `L` se os parâmetros (sem `R`) são uma das formas de [scope.md](scope.md#dimensões); vazio para outras formas |
| `params` | Parâmetros da linha `RESULT`, com `R`, como `In=512;Out=32;R=1` |
| `work_unit` | `MAC` ou `elemento` (pooling e requantização) |
| `flags`, `optimization` | `compiler.flags` e o último `-O*` delas |
| `cpu`, `clock`, `vlen`, `custom_latency` | Seção `cpu` |
| `scenario` | Cenário de memória ([scenarios.md](scenarios.md)), vazio se o YAML define as caches à mão |
| `l1i_size`, `l1i_assoc`, `l1d_size`, `l1d_assoc`, `l2_size`, `l2_assoc` | Caches; vazias se o nível não existe |
| `memory`, `memory_size` | `simple` ou `ddr4` e o tamanho |
| `cache_state` | `warm` ou `cold` no início da ROI |
| `custom_units`, `custom_pipelined` | Unidades próprias das instruções personalizadas (vazio = montagem padrão) e se têm pipeline (RCB-33; [scenarios.md](scenarios.md#unidades-e-pipeline)) |
| `cache_tuning` | Ajustes das caches que não são o padrão (RCB-32), como `line=128,l1d.pf=stride,l2.lat=20`; vazio sem ajustes. Entra no rótulo do cenário ([scenarios.md](scenarios.md#ajustes-das-caches)) |
| `checksum`, `mismatches` | Da linha `RESULT` |
| `program_exit_code` | Código com que o programa simulado terminou |

### Métricas

As 30 métricas brutas da ROI, com as chaves e as unidades da tabela de [results.md](results.md#métricas): `insts`, `ops`, `cycles`, `ipc`, `sim_ticks`, `loads`, `stores`, `mem_refs`, `branch_mispredicts`, as quatro de cada cache (`l1i_*`, `l1d_*`, `l2_*`), as da DDR4 (`dram_*`), as da memória `simple` (`simple_*`) e `host_seconds`. Depois delas, as 13 derivadas de [results.md](results.md#por-execução): `repetitions`, `work`, `work_total`, `cpi`, `l1i_mpki`, `l1d_mpki`, `l2_mpki`, `insts_per_rep`, `ops_per_rep`, `cycles_per_rep`, `insts_per_work`, `cycles_per_work` e `work_per_cycle`.

As colunas vêm de `METRICS` (`parser.py`) e `DERIVED` (`metric.py`). Uma métrica nova aparece no CSV sem mudar o `report.py`.

### Proveniência

| Coluna | Significado |
| --- | --- |
| `project_commit`, `project_dirty` | Commit do projeto e se havia mudanças não commitadas |
| `gem5_commit`, `gem5_dirty` | Commit do fork do gem5 (submódulo) e se havia mudanças |
| `gem5_sha256`, `gem5_matches_executable` | Hash do executável e se ele bate com o build-info do fork ([results.md](results.md#metadatajson)) |
| `binary_sha256` | Hash do binário simulado |
| `started_at`, `finished_at`, `duration_s` | Início, fim e duração total da execução (build e simulação), em segundos |

Para os resultados da campanha, o esperado é `project_dirty: false`, `gem5_dirty: false` e `gem5_matches_executable: true`.

## `pairs.csv`

Os pares são os do `riscvcnnbench compare`, com as mesmas regras: só execuções válidas entram, repetidas valem pela mais recente, e a chave do par ignora o que não afeta cada variante (VLEN na ref e na custom, latência na ref e na rvv).

| Coluna | Significado |
| --- | --- |
| `kind` | `variante` ou `compilador` |
| `pair` | Rótulo do par, como `ref→custom`, `ref→custom@lat6`, `ref→rvv@vlen512`, `ref(-O2→-O3)` |
| `problem` | Vazio, ou o motivo da rejeição (`checksums diferentes: ...`); um par rejeitado fica sem valores |
| `campaign` | Campanha das duas execuções, se for a mesma |
| `bench`, `size`, `params`, `data` | Operação, tamanho, parâmetros e dados (iguais nas duas) |
| `cpu`, `clock`, `scenario`, `cache_state` | CPU e memória comuns (`scenario` traz o rótulo do `compare`: nome do cenário ou tamanhos das caches) |
| `variant_a`, `variant_b`, `flags_a`, `flags_b` | Variante e flags de cada lado (`a` é a base) |
| `custom_latency`, `vlen` | Latência do lado custom e VLEN do lado rvv, se houver |
| `run_id_a`, `run_id_b` | As duas execuções, para cruzar com `runs.csv` |
| `insts_a`, `insts_b`, `ops_a`, `ops_b`, `cycles_a`, `cycles_b`, `ipc_a`, `ipc_b` | Métricas brutas das duas |
| `r_i`, `r_i_ops`, `s_c`, `ipc_ratio` | Redução de instruções, de micro-operações, speedup em ciclos e razão de IPC, com `s_c = r_i × ipc_ratio` |

Na CPU atomic, `s_c` e `ipc_ratio` ficam vazios.

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_report.py` | Tabela S/L igual aos YAMLs de `experiments/`, formato das células, cada grupo de colunas de `runs.csv` (execuções válidas, repetida, checksum divergente, falha do benchmark com a linha `RESULT`, atomic sem ciclos, falha do build sem métricas), `pairs.csv` com par aceito e rejeitados, colunas da campanha, recusa sem `--force`, CLI | `make test` |
| `tests/test_campaign_e2e.py` | O `report` sobre uma campanha real: as tentativas da combinação que falha marcadas (só a última `current`), tamanho, campanha e grupo das válidas, pares | `make e2e-test` |

## Limitações

- `size` só reconhece as formas S e L do escopo; as formas reduzidas dos testes ficam vazias.
- O checksum esperado é o mais frequente entre as `ref` válidas. Se a própria `ref` estiver errada em todas as execuções, a divergência não aparece. A validação de equivalência (RCB-15) cobre esse caso antes da campanha.
- `current` compara a configuração resolvida e o executável do gem5, não o código do benchmark ([campaigns.md](campaigns.md#limitações)).
- Só a região de interesse entra nas métricas; as instruções simuladas fora dela (verificação) não aparecem. `duration_s` mede a execução inteira.
- `host_seconds` e `duration_s` variam entre execuções iguais: são tempo do host.
