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
| `make image-clean` | Remove a imagem local do projeto. |
| `make shell` | Abre um terminal interativo Bash dentro do container. |
| `make check` | Exibe a versão das ferramentas internas instaladas no container. |
| `make lock` | Atualiza o arquivo de dependências `uv.lock`. |
| `make sync` | Cria ou sincroniza o diretório `.venv` com dependências de desenvolvimento. |
| `make test` | Executa os testes unitários do framework Python. |
| `make lint` | Executa a análise estática de código com o Ruff. |
| `make format` | Formata automaticamente o código em `src/` e `tests/`. |
| `make gem5-build` | Compila o simulador gem5 para RISC-V (`build/RISCV/gem5.opt`). |
| `make gem5-status` | Exibe o status git do submódulo `gem5`. |
| `make smoke-test` | Executa sincronização, CLI, testes e linters sequencialmente. |
| `make clean-results`| Remove os arquivos salvos em `results/`. |
| `make clean` | Limpa ambientes virtuais, caches e builds locais do framework. |

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
