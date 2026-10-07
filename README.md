# riscv-cnn-bench

O **riscv-cnn-bench** é um framework para simulação e benchmark de Redes Neurais Convolucionais (CNNs) quantizadas na arquitetura RISC-V, utilizando o simulador **gem5**. 

O objetivo do projeto é fornecer um ambiente padronizado, isolado e reprodutível para analisar o impacto de diferentes níveis de quantização, otimizações de compilador e configurações de microarquitetura (hierarquias de cache, modelos de CPU, etc.) no desempenho de inferência.

## Principais Recursos

- **Simulação com gem5:** Coleta de métricas ciclo-a-ciclo (ciclos de CPU, acessos à cache, IPC) para simulações baseadas em RISC-V.
- **Ambiente Containerizado:** Uso de Podman ou Docker para consistência de compiladores (Scons, GCC, CMake) e bibliotecas, eliminando conflitos locais.
- **Gerenciador Python (CLI):** Executável `riscvcnnbench` para validar arquivos de configuração (YAML), automatizar simulações e consolidar métricas.
- **Instalação Determinística:** Uso do gerenciador `uv` para assegurar o versionamento exato de todas as dependências Python.

---

## Estrutura do Repositório

```text
riscv-cnn-bench/
├── Containerfile             # Definição do container de desenvolvimento (Ubuntu 24.04)
├── Makefile                  # Orquestração de comandos e automação de tarefas
├── pyproject.toml            # Configuração do pacote Python e linters (Ruff/Mypy)
├── uv.lock                   # Trava de versões de dependências Python
├── configs/                  # Arquivos de configuração do simulador e experimentos
│   ├── defaults.yaml         # Configuração padrão de parâmetros do framework
│   └── gem5/
│       └── se_riscv.py       # Script de configuração do gem5 (SysCall Emulation)
├── docs/                     # Documentação técnica de suporte
├── experiments/              # Definições de experimentos em formato YAML
├── scripts/                  # Scripts para compilação e execução de benchmarks
├── src/riscvcnnbench/        # Código-fonte do framework de automação em Python
│   ├── cli.py                # Interface de Linha de Comando (CLI)
│   ├── config.py             # Parser e validador de configurações (Pydantic/YAML)
│   ├── metric.py             # Extrator de estatísticas do gem5
│   ├── parser.py             # Processamento do binário/dados de entrada
│   ├── runner.py             # Interface de execução do simulador
│   └── report.py             # Geração de relatórios e consolidação de dados
├── tests/                    # Testes unitários e de integração
└── third_party/gem5/         # Código-fonte do simulador gem5 (submódulo Git)
```

---

## Requisitos do Sistema

- **Podman** (recomendado para execução rootless com `--userns=keep-id`) ou **Docker**.
- **GNU Make** (utilizado para automação de tarefas).
- **Git** (necessário para o gerenciamento de submódulos).

---

## Guia de Instalação e Execução

### 1. Clonar o Repositório e Submódulos

```bash
git clone https://github.com/SEU-USUARIO/riscv-cnn-bench.git
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

### 5. Executar a Verificação Geral (Smoke Test)

```bash
make smoke-test
```
Este comando executa a sincronização do ambiente, testes com Pytest, checagem do linter e formatação estática.

---

## Comandos do Makefile

| Comando | Descrição |
|:---|:---|
| `make help` | Exibe a lista de comandos disponíveis. |
| `make image` | Constrói a imagem local do container de desenvolvimento. |
| `make image-clean` | Remove a imagem local do projeto, preservando código e resultados. |
| `make shell` | Abre um terminal Bash dentro do container, na raiz do projeto. |
| `make check` | Exibe a arquitetura e as versões de Python, uv, SCons e Git no container. |
| `make toolchain-check` | Exibe os caminhos e as versões do GCC, G++ e objdump da toolchain RISC-V Linux. |
| `make lock` | Resolve as dependências Python e atualiza o `uv.lock`. |
| `make sync` | Cria ou sincroniza o diretório `.venv` com as dependências de desenvolvimento. |
| `make test` | Executa os testes Python com Pytest. |
| `make lint` | Executa a análise estática com Ruff em `src/` e `tests/`. |
| `make format-check` | Verifica a formatação de `src/` e `tests/` sem alterar arquivos. |
| `make format` | Formata `src/` e `tests/` e aplica as correções automáticas do Ruff. |
| `make gem5-status` | Exibe as alterações locais no submódulo gem5. |
| `make gem5-build` | Compila o gem5 para RISC-V em `third_party/gem5/build/RISCV/gem5.opt`. Aceita `JOBS=N` para ajustar o paralelismo. |
| `make gem5-clean` | Remove os artefatos de compilação do gem5, preservando seu código-fonte. |
| `make benchmark-build` | Placeholder para futura compilação de benchmarks; atualmente apenas exibe uma mensagem. |
| `make hello-build` | Compila o exemplo RISC-V `hello_riscv` em `build/benchmarks/hello_riscv`. |
| `make hello-run` | Executa o `hello_riscv` com QEMU. Requer compilação prévia com `make hello-build`. |
| `make hello-run-gem5` | Compila o `hello_riscv` e o executa no gem5 em modo SE. Requer o simulador previamente compilado. |
| `make smoke-test` | Sincroniza as dependências e executa a CLI, os testes, o lint e a verificação de formatação. |
| `make clean-results` | Remove o conteúdo de `results/`. |
| `make clean` | Remove ambientes virtuais, caches, artefatos do framework e resultados, preservando as fontes do gem5. |
| `make status` | Exibe as alterações locais no repositório principal e no submódulo gem5. |

Para compilar e executar o exemplo teste com QEMU ou gem5, consulte o [guia do hello_riscv](docs/hello_riscv.md).

---

## Execução via CLI

Dentro do container (ou via wrapper `uv run`), utilize a ferramenta `riscvcnnbench`:

- **Exibir versão instalada:**
  ```bash
  uv run riscvcnnbench version
  ```
- **Validar arquivo de experimento:**
  ```bash
  uv run riscvcnnbench validate experiments/smoke_test.yaml
  ```
- **Executar experimento:**
  ```bash
  uv run riscvcnnbench run experiments/smoke_test.yaml
  ```
