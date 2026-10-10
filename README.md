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
| `make shell` | Abre Bash no container, na raiz do repositório. |
| `make check` | Exibe versões de ferramentas instaladas no container. |
| `make lock` | Resolve dependências e atualiza `uv.lock`. |
| `make sync` | Cria ou sincroniza `.venv` com dependências de desenvolvimento. |
| `make test` | Executa os testes Python. |
| `make lint` | Executa Ruff somente em `src/` e `tests/`. |
| `make format-check` | Verifica a formatação sem modificar arquivos. |
| `make format` | Formata apenas o código próprio em `src/` e `tests/`. |
| `make gem5-status` | Mostra o estado Git do submódulo gem5. |
| `make gem5-build` | Compila `build/RISCV/gem5.opt`; use `JOBS=N` para ajustar paralelismo. |
| `make gem5-clean` | Remove artefatos de build do gem5 sem alterar fontes. |
| `make toolchain-check` | Exibe caminhos e versões da toolchain RISC-V, quando configurado. |
| `make hello-build` | Compila o benchmark mínimo RISC-V, quando configurado. |
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
make lint
make format-check
make status
```

Para aplicar formatação ao código próprio:

```bash
make clean-results
make clean
```

Faça backup das execuções que deseja manter antes de utilizá-los.

A criação de uma pasta por execução evita sobrescritas entre simulações, mas não protege contra limpeza manual ou perda do ambiente.

## Documentação

- [Execução e resultados do hello_riscv](docs/hello_riscv.md)
- [Toolchain RISC-V](docs/toolchain.md)
- [Ambiente gem5](docs/environment.md)
