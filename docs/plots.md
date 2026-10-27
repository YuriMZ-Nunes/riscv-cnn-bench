# Gráficos de comparação

`riscvcnnbench plot` desenha os gráficos de comparação a partir dos CSVs do `report` ([report.md](report.md)), em PDF e PNG, prontos para a monografia (RCB-21). As figuras respondem à pergunta da proposta ([scope.md](scope.md)): como as instruções personalizadas (e a RVV) mudam instruções, ciclos e IPC de cada operação, em cada CPU e cenário de memória.

| Parte | Situação |
| --- | --- |
| `src/riscvcnnbench/plot.py`, `riscvcnnbench plot`, `make plot` | Existente |
| Figuras com os dados da campanha final | Existente (RCB-24): 51 figuras em `results/campaigns/final/figures/`, publicadas no pacote de dados ([data.md](data.md)) |

## Gerar

```bash
uv run riscvcnnbench report results/campaigns/exemplo   # antes: runs.csv e pairs.csv
uv run riscvcnnbench plot results/campaigns/exemplo     # lê report/, grava figures/
uv run riscvcnnbench plot results --input /tmp/tabelas --output /tmp/figuras
make plot DIR=results/campaigns/exemplo [FORCE=1]      # fora do container
```

Por padrão o comando lê `<pasta>/report/runs.csv` e `<pasta>/report/pairs.csv` e grava em `<pasta>/figures/`. Se alguma figura ou o `figures.json` já existe lá, ele recusa e pede `--force` ou outra pasta com `--output`. Com `--force`, apaga antes o que o `figures.json` anterior listava, para que não sobre figura de uma geração passada.

```text
Gravado em build/rcb21-probe/conferencia/figures (PDF e PNG):
  12 de variantes, 5 de speedup, 5 de R_I × S_C
  runs.csv: 308 execução(ões) usada(s)
  pairs.csv: 364 par(es) usado(s)
  figures.json: contexto, execuções e legenda sugerida de cada figura
```

Saída real de 26/10/2026 (25 s), sobre a campanha de conferência descrita em [Conferência](#conferência). Quando execuções ou pares ficam de fora, as linhas `runs.csv` e `pairs.csv` dizem quantos e por quê (`fora: 2 sem ciclos (CPU atomic), 1 inválida (problem)`), e uma linha a mais conta os pontos repetidos.

## As figuras

| Tipo | Arquivo | Uma figura por | Eixos e séries |
| --- | --- | --- | --- |
| Variantes | `variantes_<tamanho>_<cpu>_<cenário>` | Tamanho, CPU e cenário de memória | Três painéis: instruções por MAC, ciclos por MAC e IPC. Um grupo por operação, uma barra por variante |
| Speedup | `speedup_<tamanho>_<par>` | Par de variantes e tamanho | Speedup em ciclos `S_C` por operação, uma barra por cenário de memória, um painel por CPU; linha tracejada em 1 (sem ganho) |
| R_I × S_C | `ri_sc_<tamanho>_<par>` | Par de variantes e tamanho | `R_I` no eixo x, `S_C` no y, ambos em escala log, com a diagonal `S_C = R_I`; marcador por operação, tom e tamanho por cenário, um painel por CPU |

Os pares são os do `compare` ([results.md](results.md#comparações)): `ref→custom`, `ref→rvv`, `custom→rvv`, com latência ou VLEN fora do padrão (`ref→custom@lat6`, `custom@lat6→rvv`) e os de compilador (`ref(-O2→-O3)`). No nome do arquivo, o rótulo perde os símbolos: `ref→custom@lat6` vira `ref-custom-lat6`. Clock, flags e conjunto de dados diferentes dos da base (`1GHz`, `-O2`, `random`) entram no fim do nome, como em `variantes_S_minor_l1-l2_O3`.

### Variantes por operação

Mostra, para cada operação, o que cada variante faz com o número de instruções, com os ciclos e com o IPC. Instruções e ciclos são divididos pelo trabalho nominal da operação ([results.md](results.md#métricas-derivadas-e-comparações)), em MACs, o que deixa as operações comparáveis entre si e com a estimativa analítica de [custom_instructions.md](custom_instructions.md). Maxpool e requantização não têm MACs: nelas a unidade é o elemento, indicado embaixo do nome da operação (`por elem.`).

As séries são as variantes, com a latência das instruções personalizadas ou a VLEN quando não são as padrão (3 e 256): Referência, Personalizada, Personalizada (latência 6), RVV, RVV (VLEN 512).

### Speedup por cenário

Mostra como o ganho em ciclos de um par muda com a hierarquia de memória e com a CPU. Os cenários seguem a ordem de `configs/scenarios.yaml` ([scenarios.md](scenarios.md)); caches frias aparecem como outro cenário (`l1-l2,cold`), logo depois do aquecido.

### Redução de instruções contra speedup

`S_C = R_I · ipc_ratio` ([results.md](results.md#métricas-derivadas-e-comparações)). Um ponto sobre a diagonal tem o mesmo IPC na base e na variante: todo o ganho em instruções virou ganho em ciclos. Abaixo da diagonal, o IPC da variante caiu, porque a memória ou a latência das instruções limitaram o ganho. Acima, o IPC subiu. Os dois eixos usam a mesma escala log, então a distância vertical até a diagonal é a razão de IPC.

O `R_I` não depende da memória, então os pontos de uma operação ficam na mesma vertical, e muitas vezes no mesmo lugar, quando a memória também não muda o speedup. Por isso cada cenário tem um tamanho, do maior ao menor na ordem de `configs/scenarios.yaml`, e os menores ficam por cima: pontos que coincidem aparecem como marcadores concêntricos.

## O que entra

- Execuções de `runs.csv` sem `problem`, com `current = true` e sem `checksum_consistent = false` ([report.md](report.md#identificação-e-situação)).
- Pares de `pairs.csv` sem `problem`.
- Só com ciclos: a CPU atomic não modela tempo e fica fora das três figuras.
- Duas execuções que caem no mesmo ponto (mesma operação e série na mesma figura, por exemplo com outro `R` ou outra forma fora de S e L) valem pela mais recente, como no `compare`. O resumo conta esses pontos.

O resumo do comando e o `figures.json` dizem quantas execuções e pares ficaram de fora, e por quê.

## Formato

Pensado para a monografia:

- **PDF** vetorial, com as fontes embutidas como TrueType, para o `\includegraphics` do LaTeX; **PNG** em 300 dpi para ver rápido. Largura de 16 cm, a do texto numa página A4 com as margens da ABNT; use `\includegraphics[width=\textwidth]{...}`.
- **Sem título dentro da figura**: o título e a fonte vêm da legenda do LaTeX. O `figures.json` traz uma legenda sugerida para cada figura, com o contexto (tamanho, CPU, cenário, par).
- **Legível em preto e branco**: as barras têm hachuras diferentes por série, e os pontos, marcadores diferentes por operação e tamanhos diferentes por cenário. As cores vêm do mapa viridis, do claro para o escuro, então também se distinguem em tons de cinza; nas barras, clareadas, para a hachura preta aparecer. Conferido convertendo figuras da campanha de conferência para cinza.
- **Vírgula decimal** nos eixos, como no texto em português.
- Os rótulos de painel (`CPU minor`) e as legendas das séries ficam dentro da figura.

## figures.json e reprodutibilidade

A pasta das figuras guarda também os CSVs usados (`runs.csv` e `pairs.csv`, cópias exatas) e o `figures.json`:

| Campo | Conteúdo |
| --- | --- |
| `generated_by`, `matplotlib` | Versões do framework e do matplotlib |
| `inputs` | Caminho de origem e SHA-256 de cada CSV |
| `skipped` | Execuções e pares que ficaram de fora, por motivo |
| `figures[]` | `name`, `files` (PDF e PNG), `kind`, `context` (tamanho, CPU, cenário, par, clock, flags, dados), `caption` (legenda sugerida), `operations`, `series` ou `cpus` e `scenarios`, e `runs` ou `pairs` (os `run_id` usados, para cruzar com `runs.csv`) |

O mesmo CSV gera os mesmos bytes: o PDF sai sem data de criação, e o PNG não tem data. Por isso, para refazer as figuras basta a pasta delas:

```bash
uv run riscvcnnbench plot --input results/campaigns/exemplo/figures --output /tmp/de-novo
```

## Conferência

As figuras foram conferidas à mão numa campanha feita só para isso, rodada em `build/rcb21-probe/` em 26/10/2026 (não é a matriz da RCB-22 nem o piloto da RCB-23): as sete operações em S, nas três variantes, nas CPUs timing, minor e o3-edge, nos quatro cenários de memória, com a personalizada também com latência 6. São 308 execuções, todas concluídas com resultado válido, em 22 min com `--jobs 4`, que viraram 308 linhas em `runs.csv`, 364 pares e 22 figuras. A conferência levou a três ajustes: o rótulo da unidade abreviado (`por elem.`, que antes se sobrepunha ao vizinho), os tamanhos por cenário no R_I × S_C (pontos coincidentes se escondiam) e o rótulo do eixo x em cada painel (um rótulo único caía sobre a legenda). Os números dessas figuras servem para conferir o desenho, não como resultado.

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_plot.py` | Com CSVs sintéticos: operações iguais às do escopo, ordem das séries e dos cenários, rótulos, hachuras distintas e luminância decrescente, vírgula decimal, marcas da escala log, alturas das barras e posição dos pontos, legendas, figura sem título, seleção (atomic, inválida, substituída, checksum divergente, par rejeitado), `figures.json`, cópia dos CSVs, mesmos bytes em duas gerações, ponto repetido, recusa sem `--force` e limpeza com ele, erros e CLI | `make test` |
| `tests/test_campaign_e2e.py` | O `plot` sobre o report de uma campanha real pequena: as três figuras, o que ficou de fora e a cópia do CSV | `make e2e-test` |

## Limitações

- O conteúdo das figuras foi conferido nos testes pelas alturas das barras e pelas posições dos pontos; a aparência (sobreposição de rótulos, legibilidade) foi conferida à mão nas figuras da campanha de conferência, não por teste.
- Uma figura de variantes por tamanho, CPU e cenário pode render muitas figuras numa matriz grande; a escolha das que vão para a monografia fica com o autor (RCB-25).
- Os tons e as hachuras das séries de cenário dependem de quais cenários aparecem na figura; os das variantes são fixos.
