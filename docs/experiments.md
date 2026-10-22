# Formato dos experimentos

Um experimento é um arquivo YAML em `experiments/` que escolhe **o que** rodar (benchmark, variante do kernel e flags), **em qual máquina** (CPU, caches, memória) e **onde** salvar.

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
| [`conv3x3_direct_s_custom.yaml`](../experiments/conv3x3_direct_s_custom.yaml), [`conv3x3_direct_s_rvv.yaml`](../experiments/conv3x3_direct_s_rvv.yaml) | Mesma operação de `conv3x3_direct_s.yaml` nas variantes `custom` e `rvv`. |

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
| `benchmark.variant` | `ref` | Implementação do kernel: `ref` (referência escalar), `custom` (instruções personalizadas, só no gem5 do fork) ou `rvv` (extensão V). As operações de CNN têm as três; os demais benchmarks, só `ref`. Ver [Variantes](#variantes). |
| `compiler.flags` | `["-O2"]` | Flags escolhidas pelo experimento. `-static -march=<da variante> -mabi=lp64d` são sempre adicionadas pelo Makefile do benchmark, depois destas. |
| `cpu.model` | `atomic` | `atomic`, `timing`, `minor` (in-order) ou `o3` (out-of-order). |
| `cpu.clock` | `1GHz` | Número seguido de `MHz` ou `GHz`. |
| `cpu.vlen` | `256` | VLEN da extensão V, em bits: `128`, `256`, `512` ou `1024`. Só a variante `rvv` usa registradores vetoriais. O padrão é o do gem5. |
| `cache.l1i`, `cache.l1d`, `cache.l2` | sem cache | Cada nível tem `size` (`KiB`/`MiB`/`GiB`) e `assoc` (padrão 4). A L2 exige L1i e L1d. |
| `memory.type` | `simple` | `simple` (latência fixa) ou `ddr4` (DDR4-2400 com controlador). |
| `memory.size` | `512MiB` | `KiB`/`MiB`/`GiB`. |
| `output.dir` | `results/<name>` | Pasta onde cada execução cria sua subpasta `<run_id>`. Caminho relativo parte da raiz do projeto. |

### Variantes

`benchmark.variant` vira `VARIANT=` no `make`. O `Makefile` comum das operações ([`benchmarks/common/kernel.mk`](../benchmarks/common/kernel.mk)) escolhe o arquivo do kernel e as flags:

| Variante | Arquivo | Flags | Onde roda |
| --- | --- | --- | --- |
| `ref` | `kernel_ref.c` | `-march=rv64gc` | QEMU e qualquer gem5 |
| `custom` | `kernel_custom.c` | `-march=rv64gc -DCNN_INSN_HW` | Só o gem5 do fork. Fora dele: `Unknown instruction` |
| `rvv` | `kernel_rvv.c` | `-march=rv64gcv -fno-tree-vectorize` | QEMU com `-cpu rv64,v=true,vlen=256` e gem5 |

As variantes disponíveis de um benchmark são `ref` mais uma por arquivo `kernel_<variante>.c` na pasta; pedir outra é erro de validação. A linha `RESULT` traz `variant=` igual ao YAML. Para validar a lógica do kernel `custom` sem o gem5, o Makefile aceita `CNN_INSN=model`, que troca as instruções pelo modelo em C (só por `make`, não pelo YAML). Detalhes em [kernels.md](kernels.md#variantes).

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
| `conv3x3_direct`, `conv3x3_im2col` | `[H, W, Cin, Cout, R]`. S: `16 16 8 16`; L: `32 32 16 32`. Mesma camada, mesmo checksum. | `RESULT bench=<op> variant=<ref\|custom\|rvv> data=random H=.. W=.. Cin=.. Cout=.. R=.. checksum=0x... mismatches=0` |
| `depthwise3x3` | `[H, W, C, R]`. S: `16 16 32`; L: `32 32 64`. | idem, com `C=` |
| `pointwise1x1` | `[H, W, Cin, Cout, R]`. S: `16 16 32 32`; L: `32 32 64 64`. | idem |
| `maxpool2x2` | `[H, W, C, R]`, `H` e `W` pares. S: `32 32 16`; L: `64 64 32`. | idem |
| `requant_relu` | `[N, R]`. S: `4096`; L: `32768`. | idem, com `N=` |
| `fc` | `[In, Out, R]`. S: `512 32`; L: `1024 512`. | idem, com `In=` e `Out=` |
| `int8_base_example` | `[K, M, R]`: `M` produtos escalares int8 de tamanho `K` (múltiplo de 8) com requantização, repetidos `R` vezes na região de interesse. Padrão `64 16 1`. | `RESULT bench=int8_base_example variant=ref data=random K=.. M=.. R=.. checksum=0x... mismatches=0` |
| `cnn_insn_semantics` | nenhum. Com `compiler.flags: [-O2, -DCNN_INSN_HW]` usa as instruções personalizadas reais, que só existem no gem5 do fork (`third_party/gem5`). | `RESULT mode=model cases=39 failures=0` (ou `mode=hw`) |

O `hello_riscv_param` existe para testar as opções. Com `N` maior que a L1 (por exemplo, `65536` = 256KiB), as faltas de cache e o tipo de memória passam a aparecer nas estatísticas. Os dois `hello_*` são de teste, não CNNs. As sete operações de CNN são descritas em [kernels.md](kernels.md); cada uma tem `experiments/<operação>_s.yaml` e `_l.yaml` (variante `ref`; troque `benchmark.variant` para as outras), e as três variantes têm o mesmo checksum. Para os conjuntos de dados extremos da validação, acrescente `-DRCB_DATA=1` (`satpos`) ou `-DRCB_DATA=2` (`satneg`) em `compiler.flags` ([kernel_base.md](kernel_base.md#dados-determinísticos)); a linha `RESULT` mostra `data=`. O `int8_base_example` exercita a base comum dos kernels e separa a região de interesse no `stats.txt` ([kernel_base.md](kernel_base.md)). O `cnn_insn_semantics` confere os casos de teste das instruções personalizadas, descritos em [custom_instructions.md](custom_instructions.md).

## Como o YAML vira simulação

O formato corresponde a três peças:

| Seção do YAML | Peça |
| --- | --- |
| `benchmark`, `compiler` | `make -C benchmarks/<name> FLAGS="<flags>" VARIANT=<variant>` |
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

Antes de criar a pasta, o `run` confere se o gem5, o compilador RISC-V (`$RISCV_PREFIX` + `gcc`) e o `make` existem; se faltar algum, sai com `1` e uma mensagem dizendo o que fazer. No fim, mostra a pasta e o status e, se a execução falhou, explica a causa e aponta o log: build que não compila, benchmark que reporta erro, instrução que o gem5 não reconhece ou erro do próprio gem5. Os tipos de falha e os códigos de saída estão em [docs/results.md](results.md#diagnóstico). Como antes, `completed` significa retorno zero do gem5, que repassa o código do programa simulado.

Para listar as execuções existentes: `make runs` (ou `make runs DIR=results/<name>`), ou `uv run riscvcnnbench runs` dentro do container.

O gem5 padrão é `third_party/gem5/build/RISCV/gem5.opt` (ou `$GEM5_BIN`).

### Equivalente manual

O wrapper continua aceitando a chamada direta, sem build nem YAML. O equivalente de `hello_param_cache.yaml`, dentro do container, é:

```bash
make -C benchmarks/hello_riscv_param FLAGS="-O3 -funroll-loops" VARIANT=ref

python3 scripts/run-gem5.py \
  --gem5 third_party/gem5/build/RISCV/gem5.opt \
  --binary build/benchmarks/hello_riscv_param \
  --config configs/gem5/se_riscv_configurable.py \
  --results-dir results/hello_param_cache \
  -- --arg=65536 --arg=2 --cpu=timing --clock=2GHz --vlen=256 \
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
| Variante que o benchmark não tem | `o benchmark 'hello_riscv' não tem a variante 'rvv'; disponíveis: ref` |
| L2 sem L1i/L1d | `cache.l2 requer cache.l1i e cache.l1d` |

O benchmark e suas variantes só são procurados em `benchmarks/` quando o restante do arquivo está válido.

No código, `load_experiment()` levanta `ConfigError`, cujo atributo `problems` traz a lista de mensagens.

## Limitações

- Um experimento descreve **uma** execução; varreduras (vários tamanhos de cache, por exemplo) ainda não fazem parte do formato.
- Latências de cache, MSHRs e parâmetros internos de CPU usam valores fixos da configuração gem5, não configuráveis pelo YAML.
- Os YAMLs das operações (`experiments/<operação>_{s,l}.yaml`) usam a CPU atomic, para validação funcional. Os cenários de medição ficam para a RCB-18.
