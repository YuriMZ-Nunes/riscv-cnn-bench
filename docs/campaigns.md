# Campanhas: execução em lote

Uma campanha executa uma matriz de experimentos sem montar cada YAML à mão (RCB-19). A matriz cruza operações, variantes, CPUs, cenários de memória ([scenarios.md](scenarios.md)), latências e flags. Cada combinação continua sendo uma execução normal de `riscvcnnbench run`, com a própria pasta e os próprios metadados, e todas ficam agrupadas na pasta da campanha.

| Parte | Situação |
| --- | --- |
| Formato da matriz (`campaigns/*.yaml`), plano, execução em paralelo, retomada, estado e validação antes de começar | Existente (`src/riscvcnnbench/campaign.py`, `riscvcnnbench campaign`) |
| Matriz de exemplo [`campaigns/exemplo.yaml`](../campaigns/exemplo.yaml) | Existente |
| Matriz final da campanha | Planejado (RCB-22) |
| Estimativa de tempo por combinação | Planejado (RCB-22, com o piloto da RCB-23) |
| Exportação em CSV: `riscvcnnbench report <pasta da campanha>` | Existente (RCB-20, [report.md](report.md)); com colunas `campaign` e `groups` |

## Comandos

```bash
uv run riscvcnnbench campaign plan campaigns/exemplo.yaml            # combinações, sem executar
uv run riscvcnnbench campaign run campaigns/exemplo.yaml --jobs 4     # executa ou retoma
uv run riscvcnnbench campaign status campaigns/exemplo.yaml          # estado de cada combinação
```

Fora do container, `make campaign-plan MATRIX=...`, `make campaign MATRIX=... [JOBS=N] [VALIDATE=1]` e `make campaign-status MATRIX=...`. O `make campaign` roda a campanha inteira dentro de **um** container.

| Opção | Comandos | Efeito |
| --- | --- | --- |
| `--jobs N`, `-j N` | `run` | Simulações em paralelo. Padrão: número de CPUs (no `make campaign`, `JOBS`, padrão 4) |
| `--validate` | `run` | Roda `pytest -m validation` antes, como `validate: true` na matriz |
| `--update` | `run` | Aceita uma matriz diferente da já usada na pasta |
| `--gem5 <arquivo>` | `run`, `status` | Executável do gem5. Padrão: `$GEM5_BIN` ou o build do submódulo |
| `--output <pasta>` | todos | Pasta da campanha. Padrão: `output.dir` da matriz ou `results/campaigns/<name>` |
| `--json` | `plan`, `status` | Saída em JSON |

`campaign status` aceita a matriz ou a pasta da campanha. `riscvcnnbench runs <pasta>`, `stats`, `compare <pasta>` e `report <pasta>` ([report.md](report.md)) também funcionam sobre a pasta de uma campanha, porque ela só contém execuções normais.

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
| `tests/test_campaign.py` | Matriz de exemplo, mensagens de erro da matriz com linha, campos irrelevantes e repetidas, inválidas, nomes que colidem, pasta da campanha e `--update`, estados (concluída, falhou, interrompida, incompleta, desatualizada, pendente, outra configuração com o mesmo nome), retomada, paralelismo, validação reaproveitada, histórico, CLI. A execução é trocada por um executor falso | `make test` |
| `tests/test_campaign_e2e.py` | Matriz pequena executada de verdade (fc S, ref e custom, atomic e timing) com um grupo que falha de propósito: estado e diagnóstico, nome e configuração de cada execução, retomada sem repetir as concluídas, histórico e pares do `compare` sobre a pasta | `make e2e-test` |

## Limitações

- **A retomada confere o executável do gem5, não o código do projeto.** Se um benchmark ou a configuração gem5 mudarem entre duas sessões, as combinações já concluídas não são refeitas. Cada `metadata.json` registra o commit do projeto e o hash do binário, e cada sessão registra o commit no `campaign.json`. Para refazer tudo depois de mudar o código, use outra pasta (`--output`) ou outro `name`.
- **Não há estimativa de tempo** por combinação nem ordenação pelas mais longas: isso fica para a RCB-22, com as velocidades medidas no piloto (RCB-23).
- **Uma máquina só.** O paralelismo é em threads dentro de um processo; não há execução distribuída.
- **Memória.** Cada simulação é um processo do gem5; com muitas tarefas em paralelo nas CPUs detalhadas, confira a memória livre.
- **Campos com `scenario`.** Um experimento base com `cache` ou `memory` não combina com `scenario` no `set` ou no `vary`; essas combinações saem como inválidas.
