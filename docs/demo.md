# Demonstração

Roteiro de um vídeo curto, de 6 a 8 minutos, que mostra o problema, o framework, uma operação nas três variantes em dois cenários de memória e os resultados comparados (RCB-29). A parte simulada é a convolução 3×3 por im2col + GEMM no tamanho S, na CPU fora de ordem de borda (`o3-edge`), com as caches L1 e L2 (`l1-l2`) e sem caches (`sem-cache`): 6 simulações, cerca de 1 min 30 s com 4 tarefas.

| Parte | Situação |
| --- | --- |
| Matriz [`campaigns/demo.yaml`](../campaigns/demo.yaml) e `make demo` (simulações, tabelas, gráficos e relatório numa pasta nova) | Existente; 1 min 26 s em 29/10/2026 |
| `riscvcnnbench campaign diff` / `make campaign-diff`: compara com a campanha final publicada | Existente; 6 combinações iguais, 0 diferenças |
| Plano B: resultados pré-gerados em `results/demo/pre-gerado/` | Existente na máquina do autor (fora do Git); auditoria sem problemas |
| Roteiro em cenas (abaixo) | Existente |
| Vídeo gravado | Fora do repositório |

As 6 combinações são as mesmas da campanha final, com a mesma chave no `plan.json` (conferido em `tests/test_matrix.py`). Por isso os números da demonstração são os publicados, e a cena 6 mostra isso.

## Antes de gravar

1. **Ambiente:** `make ambiente` sai com todos os itens ok ([container.md](container.md)).
2. **Árvore limpa:** `git status` sem mudanças, no projeto e no submódulo. Senão cada linha do `make demo` sai com `(project.dirty: true)` e um aviso no início.
3. **Ensaio:** rode `make demo` uma vez, para conferir que tudo funciona e ver o tempo na sua máquina. Cada `make` abre um container novo, e o `uv` reinstala o pacote do framework no começo (as linhas "Building riscv-cnn-bench" e "Installed 1 package"), em menos de um segundo. Isso acontece toda vez, mesmo depois do ensaio; na edição, dá para cortar.
4. **Plano B:** `make campaign-audit DIR=results/demo/pre-gerado` termina com `Sem problemas.` ([Plano B](#plano-b)).
5. **Na tela, antes de começar:** um terminal com fonte grande; o editor com `experiments/conv3x3_im2col_s.yaml`, `campaigns/demo.yaml` e a pré-visualização de [architecture.md](architecture.md) (o diagrama); o navegador com `results/demo/pre-gerado/relatorio.html` numa aba, para o caso de precisar dele.
6. **Um container por vez:** não deixe um `make shell` aberto enquanto roda o `make demo`. Os dois montam a raiz com `:Z`, e o segundo tira o acesso do primeiro.

## Roteiro

Os tempos somam cerca de 7 minutos. A espera da cena 4 pode ser cortada ou acelerada na edição.

### Cena 1: o problema (1 min)

**Na tela:** o README do repositório no GitHub.

- A inferência de CNNs quantizadas em int8 na borda (Edge AI) gasta a maior parte do tempo em multiplicações e acumulações (MAC) de 8 bits.
- Em RISC-V, há duas formas de acelerar sem trocar de processador: instruções personalizadas, como o `cnn.dot8` (o produto escalar de 8 pares de int8 numa instrução), ou a extensão vetorial padrão (RVV).
- A pergunta do TCC: como as instruções personalizadas mudam as instruções executadas, os ciclos e o IPC das operações de CNN, em diferentes configurações de cache e memória ([evidence.md](evidence.md#pergunta-de-pesquisa)).
- Sem o hardware, a resposta vem de simulação no gem5, e a simulação precisa ser controlada e repetível. Esse é o papel do framework.

### Cena 2: o framework (1 min)

**Na tela:** o diagrama de [architecture.md](architecture.md).

- Tudo roda num container Podman com as versões fixadas: compilador RISC-V, QEMU e gem5.
- Um experimento é um YAML validado: a operação, a variante (`ref`, `custom` ou `rvv`), a CPU e o cenário de memória.
- O framework compila o kernel com a variante escolhida e roda no gem5 do fork, que tem as cinco instruções personalizadas.
- Só o kernel é medido (região de interesse marcada com m5ops). Cada execução guarda o binário, a configuração, os logs e a proveniência: commit, hashes, imagem.
- Uma campanha cruza os fatores. As tabelas, os gráficos e o relatório saem dela. A campanha final, com 620 simulações, está publicada com DOI.

### Cena 3: o experimento (1 min)

**Na tela:** `experiments/conv3x3_im2col_s.yaml` e `campaigns/demo.yaml` no editor, depois:

```bash
make campaign-plan MATRIX=campaigns/demo.yaml
```

```text
Campanha demo: 6 execução(ões) únicas
Pasta: results/demo/pre-gerado
  grupo variantes: 6 combinação(ões), 6 nova(s)

NOME                                          GRUPOS
conv3x3_im2col_s__ref__o3-edge__l1-l2         variantes
conv3x3_im2col_s__ref__o3-edge__sem-cache     variantes
...
```

- A operação: entrada 16×16 com 8 canais e 16 filtros 3×3, 294.912 MACs. A im2col monta um buffer e faz a convolução como um produto de matrizes.
- As três variantes fazem a mesma conta e dão o mesmo checksum: a referência escalar, a personalizada com o `cnn.dot8` e a RVV com intrínsecos (VLEN 256).
- A CPU `o3-edge` é uma fora de ordem estreita, de borda. O `l1-l2` tem L1 de 32 KiB e L2 de 256 KiB, e os dados cabem na L1. No `sem-cache`, cada instrução e cada dado vêm da DDR4 ([scenarios.md](scenarios.md)).
- 3 variantes × 2 cenários = 6 simulações.

### Cena 4: rodar (1 min 30 s; pode ser cortada)

**Na tela:**

```bash
make demo
```

Saída de 29/10/2026 (sem as linhas do `uv`):

```text
Campanha demo em build/demo/202610292001
6 combinação(ões): 0 já concluída(s), 6 a executar com 4 tarefa(s) em paralelo.
[1/6] conv3x3_im2col_s__custom__o3-edge__l1-l2: concluída — 489465 instruções, 301859 ciclos, IPC 1.622
[2/6] conv3x3_im2col_s__ref__o3-edge__l1-l2: concluída — 2324694 instruções, 1694565 ciclos, IPC 1.372
[3/6] conv3x3_im2col_s__rvv__o3-edge__l1-l2: concluída — 460777 instruções, 350942 ciclos, IPC 1.313
[4/6] conv3x3_im2col_s__custom__o3-edge__sem-cache: concluída — 489465 instruções, 7223536 ciclos, IPC 0.068
[5/6] conv3x3_im2col_s__rvv__o3-edge__sem-cache: concluída — 460777 instruções, 6587546 ciclos, IPC 0.070
[6/6] conv3x3_im2col_s__ref__o3-edge__sem-cache: concluída — 2324694 instruções, 37931504 ciclos, IPC 0.061

Sessão: 0 já concluída(s), 6 executada(s), 6 concluída(s), 0 com problema.
Gravado em build/demo/202610292001/report:
  runs.csv: 6 execução(ões), 6 válida(s), 6 valendo (current), 0 com checksum divergente
  pairs.csv: 6 par(es), 0 rejeitado(s)
...
Relatório gravado em build/demo/202610292001/relatorio.html
...
Pasta da demonstração: build/demo/202610292001
```

- Cada linha é uma simulação completa: compilou o kernel, rodou no gem5 e leu o `stats.txt`. A ordem das linhas é a de término.
- As 6 são válidas e têm o mesmo checksum: as três variantes calcularam o mesmo resultado.
- Depois das simulações, o mesmo comando gera as tabelas, os gráficos e o relatório.

A pasta padrão é `build/demo/` mais a data e a hora (`AAAAMMDDhhmm`), nova a cada minuto. Duas chamadas no mesmo minuto usam a mesma pasta, e a segunda só regrava as tabelas (`6 já concluída(s)`). `DIR=<pasta>` escolhe outra. O caminho padrão tem o mesmo comprimento que `results/campaigns/final`: o caminho do binário entra na pilha do programa simulado, e, com outro comprimento, os ciclos mudam um pouco ([reproducibility.md](reproducibility.md#o-que-se-reproduz)). Com o mesmo comprimento, a cena 6 dá 0 diferenças.

### Cena 5: os resultados (2 min)

**Na tela:** as figuras em `build/demo/<data>/figures/`, depois o `relatorio.html` da mesma pasta no navegador.

1. `variantes_S_o3-edge_l1-l2.png`: instruções por MAC, ciclos por MAC e IPC das três variantes.
   - A referência executa 7,88 instruções por MAC, a personalizada 1,66 e a RVV 1,56. A redução de instruções (R_I) é de 4,75× na personalizada e de 5,05× na RVV.
   - Em ciclos, com as caches, a personalizada vence: 1,02 ciclo por MAC, contra 1,19 da RVV, porque executa com IPC maior (1,62 contra 1,31).
2. `speedup_S_custom-rvv.png`: o speedup da RVV sobre a personalizada nos dois cenários. A linha tracejada em 1 é o empate.
   - Com as caches (`l1-l2`), 0,86: a RVV leva 16% mais ciclos que a personalizada.
   - Sem caches, 1,10: a RVV passa a ser a mais rápida, e a personalizada é que leva 10% mais ciclos. Cada instrução também é buscada na DDR4, e a RVV executa 6% menos instruções e faz 20% menos leituras da DRAM (199.610 contra 250.705).
   - **A conclusão sobre qual variante é melhor depende da memória.** É o que a campanha final mostra em escala ([analysis.md](analysis.md#onde-a-memória-limita-o-ganho)).
3. `relatorio.html`:
   - **Visão geral:** 6 execuções válidas, 6 pares.
   - **Resultados:** no seletor "Par", troque `ref→custom` por `custom→rvv` para ver o mesmo gráfico.
   - **Comparar configurações:** marque as duas, escolha `o3-edge · l1-l2` como base (o círculo) e a métrica Ciclos. Sem caches, a referência leva 22,4 vezes mais ciclos, a personalizada 23,9 e a RVV 18,8.

| Combinação | Instruções | Ciclos | IPC |
| --- | --- | --- | --- |
| ref, `l1-l2` | 2.324.694 | 1.694.565 | 1,37 |
| custom, `l1-l2` | 489.465 | 301.859 | 1,62 |
| rvv, `l1-l2` | 460.777 | 350.942 | 1,31 |
| ref, `sem-cache` | 2.324.694 | 37.931.504 | 0,06 |
| custom, `sem-cache` | 489.465 | 7.223.536 | 0,07 |
| rvv, `sem-cache` | 460.777 | 6.587.546 | 0,07 |

| Speedup em ciclos (S_C) | `l1-l2` | `sem-cache` |
| --- | --- | --- |
| ref → custom | 5,61 | 5,25 |
| ref → rvv | 4,83 | 5,76 |
| custom → rvv | 0,86 | 1,10 |

As mesmas tabelas estão em `analysis/tables.md` e na seção "Análise" do relatório.

### Cena 6: é reprodutível (45 s)

**Na tela:**

```bash
make campaign-diff DIR=build/demo/<data>
```

```text
Campanha demo (build/demo/202610292001) × final (results/campaigns/final)
NOME                                          SITUAÇÃO  ESTATÍSTICAS  DIFERENÇAS
conv3x3_im2col_s__ref__o3-edge__l1-l2         igual     3328          0
conv3x3_im2col_s__ref__o3-edge__sem-cache     igual     2648          0
conv3x3_im2col_s__custom__o3-edge__l1-l2      igual     3328          0
conv3x3_im2col_s__custom__o3-edge__sem-cache  igual     2651          0
conv3x3_im2col_s__rvv__o3-edge__l1-l2         igual     3332          0
conv3x3_im2col_s__rvv__o3-edge__sem-cache     igual     2656          0

6 combinação(ões): igual: 6.
```

- Cada combinação foi comparada com a de mesma configuração na campanha final: o binário (hash), o executável do gem5, a linha `RESULT` e o `stats.txt` inteiro, menos as estatísticas do host.
- 17.943 estatísticas, nenhuma diferença. A campanha final foi rodada dois dias antes, e os dados dela estão no Zenodo ([data.md](data.md)).
- Quem baixar o pacote pode fazer a mesma conferência com a pasta `campanhas/final` dele ([reproducibility.md](reproducibility.md#conferir-com-os-dados-publicados)).

### Cena 7: encerramento (30 s)

**Na tela:** o README, seção "Documentação".

- A campanha final cruza as sete operações, em dois tamanhos, nas três variantes, em três CPUs e quatro cenários de memória: 620 simulações, todas válidas ([analysis.md](analysis.md)).
- Limites: a avaliação é por operação, com dados sintéticos, em simulação no modo SE. Não há rede completa, área nem energia ([future.md](future.md)).
- O código está sob a licença MIT, e os dados sob a CC BY 4.0, com DOI.

## Plano B

`results/demo/pre-gerado/` tem a demonstração já rodada: as 6 simulações, `report/`, `figures/`, `analysis/` e `relatorio.html`. É a pasta padrão de `campaigns/demo.yaml`, e o caminho dela também tem o comprimento de `results/campaigns/final`. Os números dela são os mesmos da [cena 5](#cena-5-os-resultados-2-min).

| Item | Valor |
| --- | --- |
| Gerada em | 29/10/2026, em 1 min 21 s com 4 tarefas |
| Commit do projeto | `63605c3` (`main`, árvore limpa; os arquivos da RCB-29 não mudam nada da simulação) |
| gem5 | fork em `ce03244`, o mesmo executável da campanha final |
| Imagem | `localhost/riscv-cnn-bench:dev` (`308bf637ff88`, a da campanha final) |
| Auditoria | `6 de 6 concluída(s)`, sem problemas; a única observação é a falta de validação de equivalência, que a matriz da demonstração não pede |
| Conferência | `campaign diff results/demo/pre-gerado results/campaigns/final`: 6 iguais |

Ela fica fora do Git, como as outras pastas de `results/`.

**Quando usar:** se a simulação demorar, travar ou falhar durante a gravação. Corte o vídeo e continue com a pasta pré-gerada no lugar de `build/demo/<data>`. Como os números são os mesmos, a fala não muda.

| Cena | Com o plano B |
| --- | --- |
| 4 | `make campaign-status MATRIX=campaigns/demo.yaml` mostra as 6 combinações concluídas, com instruções, ciclos e IPC |
| 5 | Figuras em `results/demo/pre-gerado/figures/`; relatório em `results/demo/pre-gerado/relatorio.html` |
| 6 | `make campaign-diff DIR=results/demo/pre-gerado` |

**Se a pasta se perder:** com a árvore limpa, `make demo DIR=results/demo/pre-gerado` a refaz em cerca de 1 min 30 s.

**Sem a máquina de sempre:** as 6 combinações estão na campanha final, em `results/campaigns/final/runs/conv3x3_im2col_s__*__o3-edge__{l1-l2,sem-cache}/`, e no pacote publicado ([data.md](data.md)), em `campanhas/final/runs/`. No `relatorio.html` da final, os filtros (operação conv 3×3 im2col, tamanho S, CPU o3-edge, cenários `l1-l2` e `sem-cache`) mostram os mesmos números.

## Testes

| Teste | O que confere |
| --- | --- |
| `tests/test_matrix.py` | A demonstração tem as 6 combinações, todas na matriz final, e a pasta padrão tem o comprimento da final |
| `tests/test_package.py` | `campaign diff`: iguais, diferenças no `stats.txt` e no `RESULT`, combinação sem correspondente ou não concluída, aviso de caminho de outro comprimento e a saída da CLI |

O `make demo` e o `make campaign-diff` foram rodados de verdade em 29/10/2026, com as saídas acima. Não há teste automático do alvo `make demo`: as simulações dele são as mesmas da campanha final, e o e2e da campanha (`tests/test_campaign_e2e.py`) já roda `campaign run`, `report`, `plot`, `analyze` e `relatorio` em sequência.
