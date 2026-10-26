# riscv-cnn-bench

O **riscv-cnn-bench** é um framework em desenvolvimento (Pre-Alpha) para avaliar, no simulador **gem5**, operações de Redes Neurais Convolucionais (CNNs) quantizadas em int8 na arquitetura RISC-V.

O objetivo é um ambiente padronizado, isolado e reprodutível para medir como instruções RISC-V personalizadas e as configurações de microarquitetura (hierarquia de cache e memória, modelo de CPU) afetam a quantidade de instruções executadas, o número de ciclos e o IPC de cada operação. As instruções personalizadas são comparadas com uma implementação de referência e com a extensão vetorial V. As flags de compilação também são configuráveis por experimento. A avaliação é por operação, com dados sintéticos; não há rede completa nem dataset (ver [docs/scope.md](docs/scope.md)).

## Principais Recursos

Disponíveis:

- **Ambiente Containerizado:** Ubuntu 24.04 com imagem base fixada por digest, toolchain RISC-V e `uv` com versões fixadas, automatizado via Podman.
- **Dependências Python travadas:** `uv` e `uv.lock` fixam as versões das dependências Python.
- **gem5 para RISC-V:** compilação do simulador e configuração em modo Syscall Emulation (SE) com `AtomicSimpleCPU`, usada para validação funcional.
- **Benchmarks de teste `hello_riscv` e `hello_riscv_param`:** validam a compilação cruzada e a execução no QEMU e no gem5; o segundo tem tamanho de vetor e repetições configuráveis. Não são CNNs.
- **Formato de experimentos:** YAML com benchmark, flags, CPU (`atomic`/`timing`/`minor`/`o3`/`o3-edge`), caches L1/L2, memória e saída, validado por `riscvcnnbench validate` (ver [docs/experiments.md](docs/experiments.md)).
- **Configuração gem5 configurável:** `configs/gem5/se_riscv_configurable.py` monta CPU, caches e memória por argumentos.
- **Campanhas (execução em lote):** uma matriz em `campaigns/*.yaml`, com grupos de produtos cartesianos sobre os experimentos de `experiments/`, vira execuções normais agrupadas numa pasta; `riscvcnnbench campaign plan|run|status` mostra o plano, executa em paralelo num só container, retoma sem repetir o que terminou e mostra o estado com o diagnóstico de cada falha, com validação de equivalência opcional antes (ver [docs/campaigns.md](docs/campaigns.md)).
- **Cenários de CPU e memória:** quatro cenários de memória nomeados (`sem-cache`, `l1`, `l1-l2`, `reduzido`, em `configs/scenarios.yaml`, escolhidos por `scenario` no YAML), uma O3 estreita de borda (`o3-edge`), latência configurável das instruções personalizadas (`cpu.custom_latency`, classe `CnnMult` no fork do gem5) e caches aquecidas ou esvaziadas no início da região de interesse (`benchmark.cache_state`), com a tabela do que cabe em cada nível (ver [docs/scenarios.md](docs/scenarios.md)).
- **Execução de experimentos:** `riscvcnnbench run <yaml>` (ou `make run EXPERIMENT=...`) compila o benchmark com as flags do YAML, executa no gem5 e salva YAML, configuração resolvida e comando de build na pasta da execução. Em caso de falha, a CLI explica a causa (build, benchmark, instrução desconhecida, gem5) e aponta o log; `riscvcnnbench runs` lista as execuções.
- **Especificação das instruções personalizadas:** cinco instruções em `custom-0`/`custom-1` para operações de CNN int8 (ver [docs/custom_instructions.md](docs/custom_instructions.md)), com header `.insn`, modelo em C e o benchmark `cnn_insn_semantics`, que confere os casos de teste no QEMU e no gem5.
- **Instruções personalizadas no gem5:** o submódulo `third_party/gem5` aponta para o fork [YuriMZ-Nunes/gem5](https://github.com/YuriMZ-Nunes/gem5), branch `riscv-cnn-bench`, que tem código próprio: as cinco instruções no decodificador RISC-V. Um binário compilado com `-DCNN_INSN_HW` roda nas CPUs atomic, timing, minor e o3.
- **Base comum dos kernels int8:** headers em `benchmarks/common/` com parâmetros por argumento, dados determinísticos, requantização de referência, comparação com oráculo, checksum e região de interesse marcada com m5ops (o `stats.txt` separa o kernel do resto do programa); o mesmo binário roda no QEMU. Exemplo em `int8_base_example` (ver [docs/kernel_base.md](docs/kernel_base.md)).
- **Kernels das operações de CNN em três variantes:** convolução 3×3 direta e por im2col + GEMM, depthwise 3×3, pointwise 1×1, max pooling 2×2, requantização com ReLU e totalmente conectada, em int8, com YAMLs para os tamanhos S e L. Cada operação tem a referência escalar, a variante com as instruções personalizadas e a variante RVV (intrínsecos, VLEN configurável), escolhidas por `benchmark.variant` no YAML. As três dão o mesmo resultado, conferido por `make validate`, inclusive com dados extremos (ver [docs/kernels.md](docs/kernels.md)).
- **Métricas por região de interesse:** `riscvcnnbench stats <pasta>` lê o `stats.txt` de uma execução, escolhe o bloco da região de interesse e extrai instruções, micro-ops, ciclos, IPC, acessos e faltas nas caches, tráfego da memória e desvios mal previstos, deixando ausente, com o motivo, o que não se aplica (cache não configurada, ciclos na CPU atomic). O `run` termina com um resumo e o `runs` mostra instruções, ciclos e IPC de cada execução (ver [docs/results.md](docs/results.md#métricas)).
- **Métricas derivadas e comparações:** CPI, faltas por mil instruções, instruções e ciclos por MAC e por repetição; `riscvcnnbench compare` forma os pares ref × custom, ref × rvv e custom × rvv no mesmo cenário, e `-O2` × `-O3`, com redução de instruções, speedup em ciclos e razão de IPC, rejeitando pares com checksum diferente (ver [docs/results.md](docs/results.md#métricas-derivadas-e-comparações)).
- **Resultados por execução:** cada simulação gem5 gera uma pasta própria com logs, comando, cópias dos inputs e metadados de proveniência (ver [Resultados e reprodutibilidade](#resultados-e-reprodutibilidade)).

Planejados (ainda não implementados):

- Matriz final da campanha e estimativa de tempo (RCB-22).
- Exportação dos resultados em tabela (CSV) e gráficos.

---

## Estrutura do Repositório

```text
riscv-cnn-bench/
├── Containerfile             # Definição do container de desenvolvimento (Ubuntu 24.04)
├── Makefile                  # Orquestração de comandos e automação de tarefas
├── pyproject.toml            # Configuração do pacote Python e linters (Ruff/Mypy)
├── uv.lock                   # Trava de versões de dependências Python
├── configs/                  # Arquivos de configuração do simulador e experimentos
│   ├── defaults.yaml         # Placeholder (vazio)
│   ├── scenarios.yaml        # Cenários de memória nomeados (campo scenario do YAML)
│   └── gem5/
│       ├── se_riscv.py              # Configuração baseline do gem5 (SysCall Emulation)
│       └── se_riscv_configurable.py # CPU, caches e memória configuráveis
├── docs/                     # Documentação técnica de suporte
├── experiments/              # Experimentos em YAML (formato em docs/experiments.md)
├── campaigns/                # Matrizes de campanha (formato em docs/campaigns.md)
├── benchmarks/
│   ├── hello_riscv/          # Benchmark funcional RISC-V em C
│   ├── hello_riscv_param/    # Variante com tamanho e repetições configuráveis
│   ├── cnn_insn_semantics/   # Casos de teste das instruções personalizadas
│   ├── int8_base_example/    # Exemplo da base comum dos kernels
│   ├── conv3x3_direct/ ...   # Sete operações de CNN int8 (ver docs/kernels.md)
│   └── common/               # Base comum (rcb_*.h, kernel.mk), oráculos (rcb_ops.h), instruções (cnn_insn.h)
├── scripts/
│   ├── run-gem5.py           # Executa o gem5 e preserva cada execução em results/
│   ├── record-gem5-build.py  # Registra commit e hash do gem5 compilado
│   └── provenance.py         # Funções de hash, Git e versões usadas pelos scripts
├── src/riscvcnnbench/        # Código-fonte do framework de automação em Python
│   ├── cli.py                # Interface de Linha de Comando (CLI)
│   ├── config.py             # Formato e validação dos experimentos (Pydantic)
│   ├── parser.py             # Leitura do stats.txt: blocos, região de interesse e métricas
│   ├── runner.py             # Execução de um experimento: build e gem5 pelo wrapper
│   ├── runs.py               # Pastas de execução: listagem, diagnóstico e métricas
│   ├── metric.py             # Métricas derivadas e comparação entre variantes
│   └── report.py             # Planejado: relatórios e consolidação (vazio)
├── tests/                    # Testes Python
├── third_party/gem5/         # Código-fonte do simulador gem5 (submódulo Git)
├── build/                    # Gerado; ignorado pelo Git
└── results/                  # Resultados das execuções; ignorado pelo Git
```

---

## Requisitos do Sistema

- **Podman** (o Makefile usa execução rootless com `--userns=keep-id`).
- **GNU Make** (utilizado para automação de tarefas).
- **Git** (necessário para o gerenciamento de submódulos).

---

## Guia de Instalação e Execução

### 1. Clonar o Repositório e Submódulos

```bash
git clone https://github.com/YuriMZ-Nunes/riscv-cnn-bench.git
cd riscv-cnn-bench

# Inicializa e atualiza o gem5 e suas dependências internas
git submodule update --init --recursive
```

### 2. Construir a Imagem do Container

```bash
make image
```

### 3. Sincronizar o Ambiente Virtual Python

Este comando cria e configura o ambiente Python local (`.venv`) dentro do container:

```bash
make sync
```

### 4. Compilar o Simulador gem5

Compile o gem5 para simulação RISC-V dentro do container:

```bash
# Compilação padrão (4 jobs paralelos)
make gem5-build

# Para alterar o número de threads paralelas (ex: 8)
make gem5-build JOBS=8
```
*Nota: A compilação é um processo longo e pode demorar de 15 a 45 minutos dependendo do hardware.*

Ao final, `make gem5-build` grava `gem5.opt.build-info.json` ao lado do executável, com o commit, a branch e a URL do fork do gem5 e o hash do binário. Compile sempre por esse alvo para que as execuções possam conferir de qual revisão o gem5 veio.

### 5. Executar a Verificação Geral (Smoke Test)

```bash
make smoke-test
```
Este comando executa a sincronização do ambiente, a CLI, testes com Pytest, checagem do linter e formatação estática. Ele não compila o gem5 nem executa benchmarks.

### 6. Executar o hello_riscv

```bash
make hello-build      # Compila o benchmark
make hello-run        # Executa no QEMU
make hello-run-gem5   # Executa no gem5 e salva a execução em results/hello_riscv/<run_id>/
make e2e-test         # Teste de ponta a ponta: compila, executa no gem5 e verifica log, retorno e stats
make validate         # e2e + equivalência das variantes (S/L, dados extremos, CPUs com tempo) antes da campanha
```

O `make e2e-test` requer o gem5 compilado (`make gem5-build`). Ele usa pastas temporárias e não altera `build/` nem `results/`.

Detalhes em [docs/hello_riscv.md](docs/hello_riscv.md).

### 7. Validar e executar um experimento

```bash
make shell
uv run riscvcnnbench validate experiments/hello_param_cache.yaml
uv run riscvcnnbench run experiments/hello_param_cache.yaml
uv run riscvcnnbench runs                 # lista as execuções, o status, instruções, ciclos e IPC
uv run riscvcnnbench stats results/hello_param_cache/<run_id>   # todas as métricas de uma execução
uv run riscvcnnbench compare results      # pares de variantes no mesmo cenário
uv run riscvcnnbench campaign run campaigns/exemplo.yaml --jobs 4   # matriz em lote
```

Fora do container, `make run EXPERIMENT=experiments/hello_param_cache.yaml`, `make runs`, `make stats RUN=<pasta>` e `make compare`. O formato, os campos e a execução estão em [docs/experiments.md](docs/experiments.md).

---

## Comandos do Makefile

| Comando | Descrição |
|:---|:---|
| `make help` | Exibe a lista de comandos disponíveis. |
| `make image` | Constrói a imagem local do container de desenvolvimento. |
| `make image-clean` | Remove a imagem local do projeto. |
| `make shell` | Abre Bash no container, na raiz do repositório. |
| `make check` | Exibe versões de ferramentas instaladas no container. |
| `make lock` | Resolve dependências e atualiza `uv.lock`. |
| `make sync` | Cria ou sincroniza `.venv` com dependências de desenvolvimento. |
| `make test` | Executa os testes Python rápidos (exclui o teste de ponta a ponta). |
| `make e2e-test` | Testes de ponta a ponta no gem5: `hello_riscv`, o exemplo `hello_param_cache.yaml`, `riscvcnnbench run` (sucesso, falha de build e de simulação), instruções personalizadas, as sete operações nas três variantes e a leitura das métricas do `stats.txt` nas quatro CPUs, com e sem cache, com DDR4 e com memória `simple`, as comparações entre variantes, os cenários (latência das instruções personalizadas, os quatro cenários de memória, caches frias e a `o3-edge`) e uma campanha pequena com falha proposital e retomada. |
| `make validate` | Validação antes da campanha: e2e mais a equivalência das três variantes em S e L e com dados extremos, no QEMU e no gem5, e as três variantes em S nas CPUs timing, minor e o3-edge (`RCB_JOBS=N` para o paralelismo). |
| `make lint` | Executa Ruff somente em `src/` e `tests/`. |
| `make format-check` | Verifica a formatação sem modificar arquivos. |
| `make format` | Formata apenas o código próprio em `src/` e `tests/`. |
| `make gem5-status` | Mostra o estado Git do submódulo gem5. |
| `make gem5-build` | Compila `build/RISCV/gem5.opt` e registra commit/hash do build; use `JOBS=N` para ajustar paralelismo. |
| `make gem5-clean` | Remove artefatos de build do gem5 sem alterar fontes. |
| `make toolchain-check` | Exibe caminhos e versões da toolchain RISC-V, quando configurado. |
| `make hello-build` | Compila o benchmark `hello_riscv`. |
| `make hello-run` | Executa o `hello_riscv` no QEMU (não compila antes). |
| `make hello-run-gem5` | Compila e executa o `hello_riscv` no gem5, criando uma pasta por execução. |
| `make run EXPERIMENT=<yaml>` | Compila e executa um experimento YAML no gem5, criando uma pasta por execução. |
| `make runs [DIR=results/<name>]` | Lista as execuções existentes, o status e instruções, ciclos e IPC da região de interesse (padrão: `results/`). |
| `make stats RUN=<pasta>` | Mostra as métricas da região de interesse de uma execução, brutas e derivadas, com o motivo das ausentes. |
| `make campaign-plan MATRIX=<yaml>` | Mostra as combinações de uma campanha, sem executar. |
| `make campaign MATRIX=<yaml> [JOBS=N] [VALIDATE=1]` | Executa ou retoma uma campanha num só container, `JOBS` simulações em paralelo. |
| `make campaign-status MATRIX=<yaml>` | Estado de cada combinação, com o diagnóstico das falhas e instruções/ciclos/IPC. |
| `make compare [DIR=results/<name>]` | Compara as execuções aos pares (variantes e `-O2` × `-O3`): redução de instruções, speedup em ciclos e razão de IPC. |
| `make smoke-test` | Sincroniza ambiente, testa CLI, executa Pytest e Ruff. |
| `make clean-results` | Remove resultados gerados sob `results/`. |
| `make clean` | Remove `.venv`, caches e artefatos gerados pelo framework. |
| `make status` | Exibe o status Git do projeto e do submódulo gem5. |

## Desenvolvimento

### Código próprio versus gem5

O gem5 fica em `third_party/gem5/`, um submódulo que aponta para o fork [YuriMZ-Nunes/gem5](https://github.com/YuriMZ-Nunes/gem5), branch `riscv-cnn-bench`, construído sobre o gem5 oficial. Variar CPU, cache, memória ou workload não exige alterar o gem5: as configurações próprias ficam em `configs/gem5/`, e os scripts Python, YAMLs, benchmarks e o parser de estatísticas ficam fora do submódulo.

O fork tem código próprio só para as instruções personalizadas: `src/arch/riscv/insts/cnn.{hh,cc}`, `src/arch/riscv/isa/formats/cnn.isa`, o decodificador e a classe de operação `CnnMult` em `src/cpu/` (ver [docs/custom_instructions.md](docs/custom_instructions.md#implementação-no-gem5)). Uma mudança no gem5 segue este fluxo:

1. commit na branch `riscv-cnn-bench` do fork;
2. `make gem5-build`, que recompila e registra o commit, a branch e a URL do build;
3. atualização do ponteiro do submódulo no projeto.

Cada execução registra em `metadata.json` o commit, a branch e a URL do fork usados.

### Qualidade de código

Use os comandos abaixo antes de criar commits:

```bash
make test
make e2e-test   # Se a mudança afeta toolchain, gem5, configs ou scripts
make lint
make format-check
make status
```

Para aplicar formatação ao código próprio:

```bash
make format
```

O Ruff verifica apenas `src/` e `tests/`; os scripts em `scripts/` e o submódulo gem5 não são verificados.

## Resultados e reprodutibilidade

Cada `make hello-run-gem5` cria `results/hello_riscv/<run_id>/`, e cada `riscvcnnbench run` cria `<output.dir>/<run_id>/`, sem sobrescrever execuções anteriores. A pasta guarda `metadata.json`, `command.txt`, `stdout.log`, `stderr.log`, cópias do binário e da configuração em `inputs/` e os arquivos do gem5 em `gem5/`. O significado de cada arquivo e campo está em [docs/results.md](docs/results.md).

O `metadata.json` registra:

- status, código de saída e datas;
- commit e estado Git do projeto e do gem5, com diffs em `inputs/` quando há alterações locais rastreadas;
- hashes SHA-256 do binário, da configuração e do executável gem5;
- versão do gem5 e o registro de build, indicando se o executável ainda é o mesmo compilado por `make gem5-build`;
- imagem do container, Python e versões do compilador RISC-V.

Limitações: o executável do gem5 não é copiado (apenas identificado por hash); os caminhos são absolutos e documentam a execução original, não permitem replay automático; arquivos não rastreados não entram nos diffs; pacotes apt fixados podem deixar de existir no repositório do Ubuntu, exigindo atualização do Containerfile. O objetivo é rastreabilidade, não reprodução bit a bit.

### Limpeza

```bash
make clean-results   # Remove todo o conteúdo de results/
make clean           # Remove .venv, caches, build/ e results/
```

Faça backup das execuções que deseja manter antes de utilizá-los. A criação de uma pasta por execução evita sobrescritas entre simulações, mas não protege contra limpeza manual ou perda do ambiente.

## Documentação

- [Formato dos experimentos](docs/experiments.md)
- [Execução e resultados do hello_riscv](docs/hello_riscv.md)
- [Resultados de uma execução](docs/results.md)
- [Escopo experimental: operações, quantização, dimensões e métricas](docs/scope.md)
- [Instruções personalizadas: especificação e casos de teste](docs/custom_instructions.md)
- [Base comum dos kernels int8 e região de interesse](docs/kernel_base.md)
- [Kernels das operações: formas, referência, oráculos e instruções medidas](docs/kernels.md)
- [Cenários de CPU e memória, latência das instruções e estado das caches](docs/scenarios.md)
- [Campanhas: execução em lote de uma matriz](docs/campaigns.md)
- [Toolchain RISC-V](docs/toolchain.md)
- [Ambiente gem5](docs/environment.md)
