# Campanhas: execução em lote

Uma campanha executa uma matriz de experimentos sem montar cada YAML à mão (RCB-19). A matriz cruza operações, variantes, CPUs, cenários de memória ([scenarios.md](scenarios.md)), latências e flags. Cada combinação continua sendo uma execução normal de `riscvcnnbench run`, com a própria pasta e os próprios metadados, e todas ficam agrupadas na pasta da campanha.

| Parte | Situação |
| --- | --- |
| Formato da matriz (`campaigns/*.yaml`), plano, execução em paralelo, retomada, estado e validação antes de começar | Existente (`src/riscvcnnbench/campaign.py`, `riscvcnnbench campaign`) |
| Matriz de exemplo [`campaigns/exemplo.yaml`](../campaigns/exemplo.yaml) | Existente |
| Matriz final da campanha [`campaigns/final.yaml`](../campaigns/final.yaml) | Existente (RCB-22, [matrix.md](matrix.md)); executada em 27/10/2026 (RCB-24, [data.md](data.md)) |
| Estimativa de tempo por combinação: `riscvcnnbench campaign estimate` | Existente (RCB-22, [matrix.md](matrix.md#como-a-estimativa-é-feita)); refeita com o piloto (RCB-23) e conferida com a campanha final |
| Auditoria (`riscvcnnbench campaign audit`) e pacote de dados para publicação (`riscvcnnbench campaign package`) | Existente (RCB-24, [data.md](data.md)) |
| Comparação com outra campanha, como a publicada (`riscvcnnbench campaign diff`) | Existente (RCB-29, [reproducibility.md](reproducibility.md#conferir-com-os-dados-publicados)) |
| Matriz da demonstração [`campaigns/demo.yaml`](../campaigns/demo.yaml) e `make demo` | Existente (RCB-29, [demo.md](demo.md)) |
| Exportação em CSV: `riscvcnnbench report <pasta da campanha>` | Existente (RCB-20, [report.md](report.md)); com colunas `campaign` e `groups` |
| Gráficos: `riscvcnnbench plot <pasta da campanha>` | Existente (RCB-21, [plots.md](plots.md)); lê o `report/` da campanha e grava em `figures/` |

## Comandos

```bash
uv run riscvcnnbench campaign plan campaigns/exemplo.yaml            # combinações, sem executar
uv run riscvcnnbench campaign run campaigns/exemplo.yaml --jobs 4     # executa ou retoma
uv run riscvcnnbench campaign status campaigns/exemplo.yaml          # estado de cada combinação
uv run riscvcnnbench campaign estimate campaigns/final.yaml -m results/campaigns/medicao   # tempo estimado
uv run riscvcnnbench campaign audit results/campaigns/final          # vale como resultado?
uv run riscvcnnbench campaign diff results/demo/pre-gerado results/campaigns/final   # iguais às da final?
uv run riscvcnnbench campaign package results/campaigns/final -o results/pacotes/dados.tar.gz
```

Fora do container, `make campaign-plan MATRIX=...`, `make campaign MATRIX=... [JOBS=N] [VALIDATE=1]`, `make campaign-status MATRIX=...`, `make campaign-estimate MATRIX=... MEASURED="<pastas>" [JOBS=N] [CSV=<arquivo>]`, `make campaign-audit DIR=...`, `make campaign-diff DIR=... [REF=results/campaigns/final]` e `make campaign-package DIRS="<pastas>" OUT=<arquivo>`. O `campaign diff` compara cada combinação da primeira pasta com a de mesma chave na segunda: binário, executável do gem5, linha `RESULT` e `stats.txt` sem as estatísticas do host ([reproducibility.md](reproducibility.md#conferir-com-os-dados-publicados)). O `make campaign` roda a campanha inteira dentro de **um** container e passa a identificação da imagem (`RCB_IMAGE`, `RCB_IMAGE_ID`) para o `metadata.json` de cada execução. A auditoria e o pacote estão em [data.md](data.md).

| Opção | Comandos | Efeito |
| --- | --- | --- |
| `--jobs N`, `-j N` | `run`, `estimate` | Simulações em paralelo. Padrão: número de CPUs (no `make campaign`, `JOBS`, padrão 4); no `estimate`, as tarefas da estimativa (padrão 4) |
| `--measured <pasta>`, `-m` | `estimate` | Pasta com execuções medidas; repita para várias |
| `--csv <arquivo>` | `estimate` | Grava a tabela das combinações, com o tempo de cada uma |
| `--validate` | `run` | Roda `pytest -m validation` antes, como `validate: true` na matriz |
| `--update` | `run` | Aceita uma matriz diferente da já usada na pasta |
| `--gem5 <arquivo>` | `run`, `status` | Executável do gem5. Padrão: `$GEM5_BIN` ou o build do submódulo |
| `--output <pasta>` | `plan`, `run`, `status`, `estimate` | Pasta da campanha. Padrão: `output.dir` da matriz ou `results/campaigns/<name>` |
| `--json` | `plan`, `status` | Saída em JSON |

`campaign status` e `campaign estimate` aceitam a matriz ou a pasta da campanha. `riscvcnnbench runs <pasta>`, `stats`, `compare <pasta>`, `report <pasta>` ([report.md](report.md)) e `plot <pasta>` ([plots.md](plots.md)) também funcionam sobre a pasta de uma campanha, porque ela só contém execuções normais.

## Matriz

[`campaigns/exemplo.yaml`](../campaigns/exemplo.yaml):

```yaml
name: exemplo
description: fc S nas três variantes, timing e minor, cenário l1-l2.
validate: false
set:
  scenario: l1-l2
groups:
  - name: variantes
    experiments: [fc_s]
    vary:
      benchmark.variant: [ref, custom, rvv]
      cpu.model: [timing, minor]
      cpu.custom_latency: [3, 6]
  - name: compilador
    experiments: [fc_s]
    set:
      cpu.model: minor
    vary:
      benchmark.variant: [ref, custom]
      compiler.flags: [[-O2], [-O3]]
```

| Campo | Padrão | Significado |
| --- | --- | --- |
| `name` | obrigatório | Letras, números, `_` e `-`. Nome da campanha e da pasta padrão |
| `description` | vazio | Texto livre |
| `validate` | `false` | Roda a validação de equivalência antes de começar ([Validação](#validação-antes-de-começar)) |
| `set` | `{}` | Campos fixos de todas as combinações |
| `groups[].name` | obrigatório | Nome do grupo, único na matriz |
| `groups[].description` | vazio | Texto livre |
| `groups[].experiments` | obrigatório | Experimentos base: nome em `experiments/` (`fc_s`) ou caminho de um YAML. Definem a operação e os argumentos |
| `groups[].set` | `{}` | Campos fixos do grupo |
| `groups[].vary` | `{}` | Campos que variam, cada um com a lista de valores. O grupo é o produto cartesiano dos experimentos base com essas listas |
| `output.dir` | `results/campaigns/<name>` | Pasta da campanha; caminho relativo parte da raiz do projeto |

Os campos de `set` e `vary` usam os nomes do YAML de experimento ([experiments.md](experiments.md#campos)) com pontos: `cpu.model`, `scenario`, `benchmark.variant`, `benchmark.cache_state`, `cpu.custom_latency`, `compiler.flags`, `cache.l1d.size`... Cada combinação parte do experimento base e aplica, nesta ordem, o `set` da campanha, o `set` do grupo e um valor de cada campo de `vary`. Ficam de fora os campos que a campanha controla: `name`, `description`, `output`, `benchmark.name` e `benchmark.args`. Para variar a operação ou o tamanho, liste outros experimentos base, como `[fc_s, fc_l]`.

A matriz é validada como um experimento: todos os problemas de uma vez, com a linha e uma sugestão.

```text
Erro: campaigns/x.yaml tem 2 problemas:
  linha 4: groups.0.experiments.0: experimento 'fc_ss' não encontrado; você quis dizer 'fc_s'?
  linha 6: groups.0.vary.cpu.modle: campo 'cpu.modle' não existe no experimento; você quis dizer 'cpu.model'?
```

## Como as combinações viram execuções

1. **Produto.** Cada grupo gera `experimentos × valores de cada campo de vary` combinações. A campanha é a união dos grupos.
2. **Campos que não afetam a combinação saem**, com a mesma tabela que o `compare` usa ([results.md](results.md#comparações)): a VLEN só vale para a `rvv`, e `cpu.custom_latency` só vale para a `custom` nas CPUs `minor`, `o3` e `o3-edge`. Uma `ref` com latência 6 é a mesma execução que a `ref` com 3.
3. **Repetidas rodam uma vez.** Combinações com a mesma configuração resolvida (tudo menos nome, descrição e pasta), dentro de um grupo ou entre grupos, viram uma execução só. Ela registra todos os grupos a que pertence.
4. **Inválidas ficam de fora**, com o motivo: cada combinação passa pelas mesmas regras de um YAML de experimento. Por exemplo, `benchmark.cache_state: cold` com o cenário `sem-cache`, ou uma variante que o benchmark não tem.
5. **Nome.** Cada execução recebe um nome legível: experimento base, variante, CPU e cenário (o nome do `scenario` ou os tamanhos das caches), e, quando fogem do padrão, `latN` (latência da custom), `vlenN` (VLEN da rvv), o clock e as flags. Exemplo: `fc_s__custom__minor__l1-l2__lat6`. Se duas configurações diferentes caírem no mesmo nome, por exemplo variando só a associatividade, as duas ganham o começo da chave: `...__3f9a2c`.

Na matriz de exemplo, o grupo `variantes` gera 12 combinações: 7 únicas, porque a latência some da ref, da rvv e da timing. O grupo `compilador` gera 4, das quais as 2 com `-O2` já existem no primeiro grupo. São 9 execuções:

```text
$ uv run riscvcnnbench campaign plan campaigns/exemplo.yaml
Campanha exemplo: 9 execução(ões) únicas
Pasta: results/campaigns/exemplo
  grupo variantes: 12 combinação(ões), 7 nova(s)
  grupo compilador: 4 combinação(ões), 2 nova(s)

NOME                              GRUPOS
fc_s__ref__timing__l1-l2          variantes
fc_s__ref__minor__l1-l2           variantes,compilador
fc_s__custom__timing__l1-l2       variantes
fc_s__custom__minor__l1-l2        variantes,compilador
fc_s__custom__minor__l1-l2__lat6  variantes
fc_s__rvv__timing__l1-l2          variantes
fc_s__rvv__minor__l1-l2           variantes
fc_s__ref__minor__l1-l2__O3       compilador
fc_s__custom__minor__l1-l2__O3    compilador

7 combinação(ões) repetida(s), iguais a outra depois de ignorar os campos que não as afetam (rodam uma vez).
```

## Pasta da campanha

```text
results/campaigns/<name>/
├── campaign.yaml          # cópia da matriz usada
├── plan.json              # execuções (nome, chave, base, grupos, valores), repetidas e inválidas
├── experiments/<nome>.yaml  # o experimento gerado para cada execução
├── runs/<nome>/<run_id>/  # pastas de execução normais (docs/results.md)
├── campaign.json          # histórico: sessões de `campaign run` e validações
└── validation.log         # saída da última validação, se houve
```

Os experimentos gerados são YAMLs comuns: `riscvcnnbench run results/campaigns/<name>/experiments/<nome>.yaml` executa uma combinação avulsa, na mesma pasta `runs/<nome>/`. Cada `metadata.json` guarda a configuração resolvida, como em qualquer execução.

O estado de cada combinação vem das pastas em `runs/`, e não de um arquivo de estado: o `campaign.json` é só o histórico. Cada sessão registra início e fim, número de tarefas, o gem5 e o hash dele, o commit do projeto e se havia mudanças não commitadas, quantas foram puladas, executadas e concluídas, as que falharam e se foi interrompida.

## Estado e retomada

| Estado | Quando |
| --- | --- |
| `concluída` | Há uma execução com `status: completed` da mesma configuração e com o mesmo executável do gem5 (`gem5_sha256`) |
| `falhou` | A mais recente falhou. O diagnóstico da RCB-08 aparece entre parênteses, como `falhou (benchmark)` |
| `interrompida` | A mais recente foi interrompida (Ctrl+C), pelo wrapper ou só no gem5 |
| `incompleta` | A mais recente ficou em `preparing`, `building` ou `running`: em andamento ou encerrada abruptamente |
| `desatualizada` | Só há execuções concluídas com outro executável do gem5 |
| `pendente` | Nenhuma execução desta configuração |

`campaign run` executa tudo o que não está `concluída` e pula o resto. Rodar o mesmo comando de novo retoma a campanha: nada que terminou é repetido, e o que falhou, foi interrompido ou nunca rodou é refeito. Nenhuma pasta é apagada, e as tentativas antigas ficam ao lado (coluna `TENTATIVAS` do `status`). Uma pasta em `runs/<nome>/` só conta se a configuração resolvida dela bate com a da combinação.

Se a matriz mudou desde a última sessão, `campaign run` recusa até receber `--update`. Com ele, as combinações que continuam no plano aproveitam as execuções já feitas, e as novas rodam.

```text
$ uv run riscvcnnbench campaign status campaigns/exemplo.yaml
Campanha exemplo em results/campaigns/exemplo
NOME                              STATUS     INSTS   CICLOS  IPC    TENTATIVAS
fc_s__ref__timing__l1-l2          concluída  115270  329558  0.350  1
fc_s__ref__minor__l1-l2           concluída  115270  148403  0.777  1
...
fc_s__custom__minor__l1-l2__O3    concluída  12645   13451   0.940  1

9 combinação(ões): concluída: 9.
```

Saída real de 26/10/2026, rodada com `--output` numa pasta de `build/` (aqui com o caminho padrão e linhas omitidas). INSTS, CICLOS e IPC são da região de interesse, como no `riscvcnnbench runs`. As combinações sem conclusão aparecem depois da tabela, com a mensagem do diagnóstico e a pasta.

### Árvore suja

Uma combinação `concluída` pode não valer como resultado. Cada execução grava, no início, o estado do Git do projeto e do submódulo do gem5 (`git status --porcelain`, que inclui arquivos não rastreados), e também se o executável do gem5 é o do build registrado. Com mudanças não commitadas, ela sai com `dirty: true`, e a [`campaign audit`](data.md#auditoria) a recusa. Foi o que aconteceu com 8 execuções do piloto, editadas no meio da campanha ([pilot.md](pilot.md#problemas-encontrados)). Desde a RCB-30, a campanha avisa em três momentos:

| Quando | O que aparece |
| --- | --- |
| Início do `campaign run`, antes da validação | `Aviso: o projeto tem N mudança(s) não commitada(s) (M src/x.py, ?? novo.txt...)`, e o mesmo para o submódulo do gem5 (`third_party/gem5`), com o campo que vai sair `true`. Com a árvore limpa, nada aparece. A campanha roda mesmo assim |
| Linha de progresso de cada combinação | A linha termina com `(project.dirty: true)`, `(gem5_repository.dirty: true)` ou `(gem5_build.matches_executable: false)` quando a execução sai assim. Isso pega uma edição feita no meio da campanha |
| Fim da sessão (stderr) | `Aviso: N concluída(s) nesta sessão com a árvore suja ou outro executável do gem5` |

O `campaign status` lista essas concluídas depois da tabela. No `--json`, o campo `provenance` de cada combinação traz a lista, vazia quando ela vale. Saída real de 27/10/2026, da campanha de exemplo rodada numa pasta de `build/` com as mudanças desta issue ainda não commitadas (linhas omitidas):

```text
$ uv run riscvcnnbench campaign run campaigns/exemplo.yaml --output build/rcb30/exemplo -j 4
Campanha exemplo em build/rcb30/exemplo
Aviso: o projeto tem 4 mudança(s) não commitada(s) (M docs/campaigns.md, M src/riscvcnnbench/campaign.py, M src/riscvcnnbench/cli.py e mais 1). As execuções vão sair com project.dirty: true e não valem como resultado (campaign audit). Faça o commit antes e não altere a árvore durante a campanha; rascunhos ficam em build/.
9 combinação(ões): 0 já concluída(s), 9 a executar com 4 tarefa(s) em paralelo.
[1/9] fc_s__ref__timing__l1-l2: concluída — 115270 instruções, 329558 ciclos, IPC 0.350 (project.dirty: true)
...
Sessão: 0 já concluída(s), 9 executada(s), 9 concluída(s), 0 com problema.
Aviso: 9 concluída(s) nesta sessão com a árvore suja ou outro executável do gem5; elas não valem como resultado. Veja `riscvcnnbench campaign status build/rcb30/exemplo`.

$ uv run riscvcnnbench campaign status build/rcb30/exemplo
...
Concluídas que não valem como resultado: 9
  fc_s__ref__timing__l1-l2: project.dirty: true (build/rcb30/exemplo/runs/fc_s__ref__timing__l1-l2/20261027T185641.365784Z-f7736f8f)
  ...
Para refazer com a árvore limpa: riscvcnnbench run build/rcb30/exemplo/experiments/<nome>.yaml (a mais recente passa a valer).
```

No piloto e na campanha final, o `status` não lista nenhuma: as execuções que valem estão limpas (as 8 sujas do piloto foram substituídas).

O `campaign run` não as refaz sozinho, porque elas estão concluídas. Para refazer, rode o experimento gerado da combinação com a árvore limpa: a execução nova fica na mesma pasta e passa a ser a que vale no `status`, no `report` e na `audit`.

### Execução, falhas e interrupção

- **Paralelismo.** `--jobs N` roda até N simulações ao mesmo tempo, em threads dentro do mesmo processo e, portanto, do mesmo container. Não rode vários `podman run` ao mesmo tempo sobre a pasta do projeto: o volume `:Z` é reetiquetado pelo SELinux e os containers anteriores perdem acesso. Cada combinação compila o benchmark na própria pasta, então compilações simultâneas da mesma operação não se atrapalham.
- **Falhas.** Uma combinação que falha não interrompe as outras. O progresso mostra `falhou (<diagnóstico>)`, e `campaign status` mostra a causa.
- **Ctrl+C.** As combinações que ainda não começaram são canceladas, e as em andamento terminam como `interrompida` e entram no histórico. Para retomar, rode o mesmo comando.
- **Código de saída** do `campaign run`: `0` se todas as combinações estão concluídas, `1` se alguma falhou (ou a matriz ou o ambiente têm problema) e `130` se foi interrompido.

Interrupção do gem5 sozinho: até a RCB-19, se o SIGINT chegasse só ao gem5, a configuração saía com `0` e a execução passava por `completed` com o `stats.txt` truncado. Agora ela imprime `Simulação interrompida no tick N` e sai com `130`, e a execução fica `failed` com diagnóstico `interrupted` ([results.md](results.md#diagnóstico)). Assim, a retomada não pula uma execução cortada.

## Validação antes de começar

Com `validate: true` na matriz ou `--validate`, a campanha roda `pytest -m validation` (a validação de equivalência da RCB-15 e as variantes nas CPUs com tempo da RCB-18, [kernels.md](kernels.md#validação-de-equivalência)) antes da primeira simulação, com `RCB_JOBS` igual a `--jobs`. A saída vai para `validation.log`. Se falhar, a campanha não começa e o comando sai com 1.

O resultado fica em `campaign.json`, com o hash do gem5, o commit do projeto e se havia mudanças não commitadas. Numa retomada, uma validação anterior que passou é reaproveitada se o gem5 e o commit forem os mesmos e não houver mudanças não commitadas, nem antes nem agora. Senão, roda de novo. A validação leva mais de 10 minutos.

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_campaign.py` | Aviso de árvore suja num repositório Git temporário (limpo, arquivo modificado e não rastreado, mais de três mudanças, só o submódulo do gem5, pasta fora do Git), execuções sujas na linha de progresso, no fim da sessão, no `status` e no `--json`. Matriz de exemplo, mensagens de erro da matriz com linha, campos irrelevantes e repetidas, inválidas, nomes que colidem, pasta da campanha e `--update`, estados (concluída, falhou, interrompida, incompleta, desatualizada, pendente, outra configuração com o mesmo nome), retomada, paralelismo, validação reaproveitada, histórico, CLI. A execução é trocada por um executor falso | `make test` |
| `tests/test_package.py` | `campaign audit`, `campaign package` e `campaign diff` sobre campanhas com o executor falso ([data.md](data.md#testes), [demo.md](demo.md#testes)) | `make test` |
| `tests/test_campaign_e2e.py` | Matriz pequena executada de verdade (fc S, ref e custom, atomic e timing) com um grupo que falha de propósito: estado e diagnóstico, nome e configuração de cada execução, retomada sem repetir as concluídas, histórico e pares do `compare` sobre a pasta | `make e2e-test` |

## Limitações

- **A retomada confere o executável do gem5, não o código do projeto.** Se um benchmark ou a configuração gem5 mudarem entre duas sessões, as combinações já concluídas não são refeitas. Cada `metadata.json` registra o commit do projeto e o hash do binário, e cada sessão registra o commit no `campaign.json`. Para refazer tudo depois de mudar o código, use outra pasta (`--output`) ou outro `name`.
- **Sem ordenação pelas mais longas.** O `run` segue a ordem do plano; a estimativa por combinação existe (`campaign estimate`, RCB-22), mas não muda a ordem.
- **Não edite a árvore durante uma campanha.** Cada execução grava `git status --porcelain` no início; uma edição no meio deixa as seguintes com `project.dirty: true`, e a `campaign audit` as aponta como problema (foi o que aconteceu no piloto, [pilot.md](pilot.md#problemas-encontrados)). A campanha avisa, mas não impede ([Árvore suja](#árvore-suja)).
- **Uma máquina só.** O paralelismo é em threads dentro de um processo; não há execução distribuída.
- **Memória.** Cada simulação é um processo do gem5; com muitas tarefas em paralelo nas CPUs detalhadas, confira a memória livre.
- **Campos com `scenario`.** Um experimento base com `cache` ou `memory` não combina com `scenario` no `set` ou no `vary`; essas combinações saem como inválidas.
