# riscv-cnn-bench

O **riscv-cnn-bench** é um framework em desenvolvimento (Pre-Alpha) para simulação e benchmark de Redes Neurais Convolucionais (CNNs) quantizadas na arquitetura RISC-V, utilizando o simulador **gem5**.

O objetivo do projeto é fornecer um ambiente padronizado, isolado e reprodutível para analisar o impacto de diferentes níveis de quantização, otimizações de compilador e configurações de microarquitetura (hierarquias de cache, modelos de CPU, etc.) no desempenho de inferência.

## Principais Recursos

Disponíveis:

- **Ambiente Containerizado:** Ubuntu 24.04 com imagem base fixada por digest, toolchain RISC-V e `uv` com versões fixadas, automatizado via Podman.
- **Dependências Python travadas:** `uv` e `uv.lock` fixam as versões das dependências Python.
- **gem5 para RISC-V:** compilação do simulador e configuração em modo Syscall Emulation (SE) com `AtomicSimpleCPU`, usada para validação funcional.
- **Benchmarks de teste `hello_riscv` e `hello_riscv_param`:** validam a compilação cruzada e a execução no QEMU e no gem5; o segundo tem tamanho de vetor e repetições configuráveis. Não são CNNs.
- **Formato de experimentos:** YAML com benchmark, flags, CPU (`atomic`/`timing`/`minor`/`o3`), caches L1/L2, memória e saída, validado por `riscvcnnbench validate` (ver [docs/experiments.md](docs/experiments.md)).
- **Configuração gem5 configurável:** `configs/gem5/se_riscv_configurable.py` monta CPU, caches e memória por argumentos.
- **Resultados por execução:** cada simulação gem5 gera uma pasta própria com logs, comando, cópias dos inputs e metadados de proveniência (ver [Resultados e reprodutibilidade](#resultados-e-reprodutibilidade)).

Planejados (ainda não implementados):

- Benchmarks de CNNs e kernels quantizados.
- Modelos de CPU detalhados e hierarquias de cache para coleta de métricas de microarquitetura (ciclos, IPC, acessos à cache).
- Execução de experimentos pela CLI (`riscvcnnbench run`) e consolidação de métricas. Hoje `run` apenas verifica se o arquivo existe.
- Varreduras de parâmetros (vários experimentos a partir de um arquivo).

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
│   └── gem5/
│       ├── se_riscv.py              # Configuração baseline do gem5 (SysCall Emulation)
│       └── se_riscv_configurable.py # CPU, caches e memória configuráveis
├── docs/                     # Documentação técnica de suporte
├── experiments/              # Experimentos em YAML (formato em docs/experiments.md)
├── benchmarks/
│   ├── hello_riscv/          # Benchmark funcional RISC-V em C
│   └── hello_riscv_param/    # Variante com tamanho e repetições configuráveis
├── scripts/
│   ├── run-gem5.py           # Executa o gem5 e preserva cada execução em results/
│   ├── record-gem5-build.py  # Registra commit e hash do gem5 compilado
│   └── provenance.py         # Funções de hash, Git e versões usadas pelos scripts
├── src/riscvcnnbench/        # Código-fonte do framework de automação em Python
│   ├── cli.py                # Interface de Linha de Comando (CLI)
│   ├── config.py             # Formato e validação dos experimentos (Pydantic)
│   ├── metric.py             # Planejado: extrator de estatísticas do gem5 (vazio)
│   ├── parser.py             # Planejado: processamento de dados de entrada (vazio)
│   ├── runner.py             # Planejado: interface de execução do simulador (vazio)
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

Ao final, `make gem5-build` grava `gem5.opt.build-info.json` ao lado do executável, com o commit do gem5 e o hash do binário. Compile sempre por esse alvo para que as execuções possam conferir de qual revisão o gem5 veio.

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
```

O `make e2e-test` requer o gem5 compilado (`make gem5-build`). Ele usa pastas temporárias e não altera `build/` nem `results/`.

Detalhes em [docs/hello_riscv.md](docs/hello_riscv.md).

### 7. Validar um experimento

```bash
make shell
uv run riscvcnnbench validate experiments/hello_param_cache.yaml
```

O formato, os campos e como executar um experimento manualmente estão em [docs/experiments.md](docs/experiments.md).

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
| `make e2e-test` | Testes de ponta a ponta no gem5: `hello_riscv` e o exemplo `hello_param_cache.yaml`. |
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
| `make smoke-test` | Sincroniza ambiente, testa CLI, executa Pytest e Ruff. |
| `make clean-results` | Remove resultados gerados sob `results/`. |
| `make clean` | Remove `.venv`, caches e artefatos gerados pelo framework. |
| `make status` | Exibe o status Git do projeto e do submódulo gem5. |

## Desenvolvimento

### Código próprio versus gem5

O gem5 é mantido como uma dependência externa em `third_party/gem5/`. Durante o desenvolvimento normal do framework, não é necessário alterar o código-fonte do gem5 para variar CPU, cache, memória ou workload.

As configurações próprias devem ficar em:

```text
configs/gem5/
```

Os scripts Python, YAMLs, benchmarks e parsers do projeto devem ficar fora do submódulo.

Caso o estudo de caso final exija uma instrução RISC-V não suportada pelo simulador, as alterações devem ser isoladas e rastreáveis, preferencialmente como patches em:

```text
patches/gem5/
```

A baseline deve continuar apontando para um commit limpo e fixo do gem5.

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

Cada `make hello-run-gem5` cria `results/hello_riscv/<run_id>/` sem sobrescrever execuções anteriores. A pasta guarda `metadata.json`, `command.txt`, `stdout.log`, `stderr.log`, cópias do binário e da configuração em `inputs/` e os arquivos do gem5 em `gem5/`.

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
- [Toolchain RISC-V](docs/toolchain.md)
- [Ambiente gem5](docs/environment.md)
