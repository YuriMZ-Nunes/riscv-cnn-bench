# Formato dos experimentos

Um experimento é um arquivo YAML em `experiments/` que escolhe **o que** rodar (benchmark e flags), **em qual máquina** (CPU, caches, memória) e **onde** salvar.

Só `name` e `benchmark.name` são obrigatórios. Todo campo omitido usa um padrão que reproduz a configuração baseline de `configs/gem5/se_riscv.py`.

```bash
uv run riscvcnnbench validate experiments/hello_param_cache.yaml
```

O `validate` confere o arquivo e mostra a configuração resultante, já com os padrões aplicados. Campos desconhecidos são erro, para que um erro de digitação como `cahce:` não seja ignorado. `riscvcnnbench run` faz a mesma validação antes de qualquer outra coisa. Veja [Mensagens de erro](#mensagens-de-erro).

Para executar, veja [Executar um experimento](#executar-um-experimento).

## Exemplos

| Arquivo | Para que serve |
| --- | --- |
| [`smoke_test.yaml`](../experiments/smoke_test.yaml) | Mínimo: `hello_riscv` com todos os padrões. |
| [`hello_param_minimal.yaml`](../experiments/hello_param_minimal.yaml) | Mínimo do benchmark parametrizável. |
| [`hello_param_cache.yaml`](../experiments/hello_param_cache.yaml) | Variação com todos os campos anotados: CPU timing a 2GHz, L1/L2, DDR4 e flags próprias. |

Configuração mínima:

```yaml
name: smoke_test
benchmark:
  name: hello_riscv
```

## Campos

| Campo | Padrão | Valores |
| --- | --- | --- |
| `name` | obrigatório | Letras, números, `_` e `-`. Identifica o experimento e a pasta de saída. |
| `description` | vazio | Texto livre. |
| `benchmark.name` | obrigatório | Pasta em `benchmarks/` que contém um `Makefile`. |
| `benchmark.args` | `[]` | Lista de argumentos passados ao programa. Números são aceitos e convertidos em texto (`[65536, 2]` equivale a `["65536", "2"]`). |
| `compiler.flags` | `["-O2"]` | Flags escolhidas pelo experimento. `-static -march=rv64gc -mabi=lp64d` são sempre adicionadas pelo Makefile do benchmark. |
| `cpu.model` | `atomic` | `atomic`, `timing`, `minor` (in-order) ou `o3` (out-of-order). |
| `cpu.clock` | `1GHz` | Número seguido de `MHz` ou `GHz`. |
| `cache.l1i`, `cache.l1d`, `cache.l2` | sem cache | Cada nível tem `size` (`KiB`/`MiB`/`GiB`) e `assoc` (padrão 4). A L2 exige L1i e L1d. |
| `memory.type` | `simple` | `simple` (latência fixa) ou `ddr4` (DDR4-2400 com controlador). |
| `memory.size` | `512MiB` | `KiB`/`MiB`/`GiB`. |
| `output.dir` | `results/<name>` | Pasta onde cada execução cria sua subpasta `<run_id>`. Caminho relativo parte da raiz do projeto. |

### Escolhendo a CPU

- `atomic`: acessos instantâneos, sem modelo de tempo. É o mais rápido de simular e serve para **validação funcional**. Ticks e ciclos dessa CPU não medem desempenho real.
- `timing`: CPU simples, mas com tempo de acesso à memória e caches modelado.
- `minor`: pipeline in-order.
- `o3`: pipeline out-of-order, o mais detalhado e o mais lento de simular.

Para comparar caches ou memória, use `timing`, `minor` ou `o3`.

## Benchmarks disponíveis

| Benchmark | Argumentos | Saída esperada |
| --- | --- | --- |
| `hello_riscv` | nenhum | `RESULT sum=499500` |
| `hello_riscv_param` | `[N, R]`: soma um vetor de `N` inteiros (`N*4` bytes) `R` vezes. Padrão `1024 1`. | `RESULT n=N repeat=R sum=R*N*(N-1)/2` |

O `hello_riscv_param` existe para testar as opções. Com `N` maior que a L1 (por exemplo, `65536` = 256KiB), as faltas de cache e o tipo de memória passam a aparecer nas estatísticas. Os dois benchmarks são de teste, não CNNs.

## Como o YAML vira simulação

O formato corresponde a três peças:

| Seção do YAML | Peça |
| --- | --- |
| `benchmark`, `compiler` | `make -C benchmarks/<name> FLAGS="<flags>"` |
| `cpu`, `cache`, `memory`, `benchmark.args` | Argumentos de [`configs/gem5/se_riscv_configurable.py`](../configs/gem5/se_riscv_configurable.py), gerados por `Experiment.gem5_args()` |
| `output` | `--results-dir` de `scripts/run-gem5.py` |

A configuração baseline `se_riscv.py` continua intacta, e `make hello-run-gem5` segue usando-a.

## Executar um experimento

```bash
make run EXPERIMENT=experiments/hello_param_cache.yaml
```

ou, dentro do container (`make shell`):

```bash
uv run riscvcnnbench run experiments/hello_param_cache.yaml
uv run riscvcnnbench run experiments/hello_param_cache.yaml --gem5 caminho/gem5.opt
```

O `run` valida o YAML (um YAML inválido não cria pasta) e chama `scripts/run-gem5.py`, que cria `<output.dir>/<run_id>/` e:

1. copia o YAML para `inputs/experiment.yaml` e grava a configuração resolvida, com todos os padrões preenchidos, em `inputs/experiment.resolved.json`;
2. compila o benchmark com `compiler.flags` diretamente em `inputs/<benchmark>` (log em `build.log`);
3. executa o gem5 com `se_riscv_configurable.py` e os argumentos de `gem5_args()`.

O comando de build e o do gem5 ficam em `command.txt` e em `metadata.json` (campos `build` e `command`), junto com a configuração resolvida (`experiment.resolved`). Assim, duas execuções que diferem em um só parâmetro se distinguem comparando `experiment.resolved`. O que é cada arquivo da pasta e como interpretá-lo está em [docs/results.md](results.md).

O código de saída do `run` é o do wrapper: `0` quando o gem5 retorna zero, o código do `make` quando o build falha, o do gem5 quando a simulação falha `1` quando o YAML é inválido e `2` quando o gem5 informado não existe (esses dois casos não criam pasta). Em `metadata.json`, `status` fica `failed` e `failed_step` indica a etapa (`build`, `simulation` ou `preparation`). Como antes, `completed` significa retorno zero do gem5, não validação do resultado do programa.

O gem5 padrão é `third_party/gem5/build/RISCV/gem5.opt` (ou `$GEM5_BIN`).

### Equivalente manual

O wrapper continua aceitando a chamada direta, sem build nem YAML. O equivalente de `hello_param_cache.yaml`, dentro do container, é:

```bash
make -C benchmarks/hello_riscv_param FLAGS="-O3 -funroll-loops"

python3 scripts/run-gem5.py \
  --gem5 third_party/gem5/build/RISCV/gem5.opt \
  --binary build/benchmarks/hello_riscv_param \
  --config configs/gem5/se_riscv_configurable.py \
  --results-dir results/hello_param_cache \
  -- --arg=65536 --arg=2 --cpu=timing --clock=2GHz \
     --l1i-size=32KiB --l1i-assoc=4 --l1d-size=32KiB --l1d-assoc=4 \
     --l2-size=256KiB --l2-assoc=8 --mem-type=ddr4 --mem-size=512MiB
```

Os argumentos após `--` são repassados à configuração gem5 e ficam registrados em `command.txt` e `metadata.json`. Nesse caso, `experiment` e `build` ficam nulos em `metadata.json`.

## Mensagens de erro

A validação reúne **todos** os problemas do arquivo de uma vez, ordenados por linha. Cada um traz a linha, o campo e o que fazer:

```text
Erro: experiments/meu.yaml tem 7 problemas:
  linha 1: name: valor 'meu experimento' inválido; use apenas letras, números, _ e -
  linha 2: benchmark.name: campo obrigatório ausente
  linha 3: benchmark.args: deve ser uma lista, como ["a", "b"], mas recebeu 4096
  linha 4: cahce: campo desconhecido; você quis dizer 'cache'?
  linha 8: cpu.model: valor 'pentium' inválido; use 'atomic', 'timing', 'minor' ou 'o3'
  linha 9: cpu.clock: deve ser texto, mas recebeu 2; use uma frequência como 800MHz ou 2GHz
  linha 11: memory.size: deve ser texto, mas recebeu 512; use um tamanho como 32KiB, 512MiB ou 1GiB
```

Além disso, são detectados:

| Situação | Mensagem |
| --- | --- |
| Arquivo inexistente ou vazio | `arquivo não encontrado`, `arquivo vazio; o mínimo é name e benchmark.name` |
| Erro de sintaxe YAML | `linha L, coluna C: YAML inválido (...); confira a indentação e os ':'` |
| Arquivo que é lista ou valor solto | `o arquivo deve ser um mapeamento de campos (...)` |
| Campo repetido | `campo repetido; só o último valor seria usado` |
| Seção escrita como valor (`cpu: o3`) | `deve conter subcampos (um mapeamento YAML)` |
| Benchmark inexistente | Lista os benchmarks disponíveis em `benchmarks/` |
| L2 sem L1i/L1d | `cache.l2 requer cache.l1i e cache.l1d` |

O benchmark só é procurado em `benchmarks/` quando o restante do arquivo está válido.

No código, `load_experiment()` levanta `ConfigError`, cujo atributo `problems` traz a lista de mensagens.

## Limitações

- Um experimento descreve **uma** execução; varreduras (vários tamanhos de cache, por exemplo) ainda não fazem parte do formato.
- Latências de cache, MSHRs e parâmetros internos de CPU usam valores fixos da configuração gem5, não configuráveis pelo YAML.
- `experiments/conv2d_baseline.yaml` e `experiments/conv2d_cache_sweep.yaml` ainda são placeholders vazios e falham na validação.
