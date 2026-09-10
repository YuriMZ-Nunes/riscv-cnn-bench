# riscv-cnn-bench

> Framework reprodutível, orientado a linha de comando, para executar e analisar benchmarks de CNNs quantizadas em sistemas RISC-V simulados com gem5.

O **riscv-cnn-bench** é o projeto de uma ferramenta de benchmark para avaliação de inferência de Redes Neurais Convolucionais (CNNs) quantizadas na arquitetura RISC-V. A ferramenta automatiza a compilação de workloads, a execução de simulações no **gem5**, a coleta de estatísticas arquiteturais e a consolidação de resultados em artefatos rastreáveis.

O projeto é desenvolvido como parte de um Trabalho de Conclusão de Curso (TCC). Seu foco não é implementar um processador completo em HDL, mas disponibilizar uma infraestrutura experimental que permita investigar, de maneira controlada e reproduzível, como escolhas de ISA e microarquitetura afetam o desempenho de kernels de CNN quantizados.

## Objetivo

O objetivo é desenvolver um framework CLI capaz de receber experimentos declarados em YAML, criar os cenários de simulação correspondentes e executar benchmarks RISC-V no gem5. Cada execução deve preservar os parâmetros usados, a configuração efetiva do simulador, os logs e as métricas produzidas, permitindo repetir ou auditar os resultados posteriormente.

A ferramenta foi pensada para apoiar perguntas como:

- Qual é o impacto do tamanho e da associatividade de caches L1/L2 sobre um kernel Conv2D int8?
- Em quais cenários um workload é limitado por computação e em quais é limitado por cache ou memória?
- Como diferentes modelos de CPU do gem5 alteram ciclos, CPI, IPC e comportamento de cache?
- Uma instrução RISC-V personalizada, por exemplo para produto escalar int8 ou requantização, reduz ciclos de forma consistente?
- O ganho de uma extensão de ISA permanece quando se modificam CPU, cache, memória ou dimensões do tensor?

O framework busca responder a essas perguntas sem exigir que cada experimento seja configurado manualmente em múltiplos scripts do gem5.

## Escopo experimental

A arquitetura geral do projeto é:

```text
Arquivo YAML de experimento
            │
            ▼
CLI riscvcnnbench
            │
            ├── valida parâmetros e arquivos
            ├── resolve configurações e varreduras
            ├── compila ou seleciona benchmark RISC-V
            ├── invoca o gem5 em modo SE
            ├── coleta config.ini, config.json e stats.txt
            ├── valida a saída do benchmark por checksum/referência
            ├── calcula métricas derivadas
            └── gera CSV, JSON, gráficos e manifestos
            │
            ▼
Resultados reproduzíveis por experimento
```

O fluxo inicial usa o modo **SE (Syscall Emulation)** do gem5. Nesse modo, o gem5 executa um binário da ISA simulada sem exigir uma imagem de disco, kernel Linux e sequência de boot completos. Isso reduz a complexidade do ambiente e permite concentrar a avaliação em CPU, cache, memória e workload.

O conjunto de benchmarks deve evoluir de programas mínimos de validação para microkernels representativos de CNNs quantizadas, tais como:

- Produto escalar int8 e multiply-accumulate (MAC)
- Requantização de acumuladores int32 para ativações int8
- Fully connected int8
- Conv2D int8
- Depthwise Conv2D int8
- Max pooling e operações de saturação/clamp

A saída de cada benchmark deve ser verificável, por exemplo por checksum ou comparação com um vetor de referência. Resultados de desempenho só são considerados válidos quando a corretude funcional também for confirmada.

## Métricas analisadas

O gem5 produz arquivos de configuração e estatísticas após cada execução. O framework deve extrair e organizar métricas como:

| Categoria | Métricas iniciais | Finalidade |
|---|---|---|
| Execução | `simInsts`, `numCycles`, `simSeconds` | Quantificar o custo da execução simulada |
| CPU | CPI, IPC | Avaliar eficiência da execução de instruções |
| Cache | Acessos, hits, misses e miss rate de L1I, L1D e L2 | Identificar pressão na hierarquia de memória |
| Memória | Bytes lidos/escritos, largura de banda e latência, quando disponíveis | Avaliar gargalos de memória |
| Correção | Checksum, tensor de referência e código de saída | Garantir equivalência funcional entre variantes |
| Custo de simulação | `hostSeconds`, `hostInstRate` | Registrar o custo de executar o simulador no computador host |

As métricas derivadas mais importantes são:

\[
CPI = \frac{\text{numCycles}}{\text{simInsts}}
\]

\[
IPC = \frac{\text{simInsts}}{\text{numCycles}}
\]

\[
Speedup = \frac{\text{ciclos da baseline}}{\text{ciclos da variante}}
\]

> `hostSeconds` mede o tempo que o gem5 gastou no computador anfitrião; ele não deve ser interpretado como o tempo de execução do processador RISC-V simulado.

## Reprodutibilidade

A reprodutibilidade é parte central da ferramenta. Um resultado não deve depender de bibliotecas instaladas manualmente no computador do usuário nem de alterações não documentadas no gem5.

O projeto utiliza as seguintes camadas de controle:

| Camada | Mecanismo | Informação preservada |
|---|---|---|
| Ambiente Linux | `Containerfile` e Podman/Docker | Sistema base e dependências de compilação/simulação |
| Dependências Python | `pyproject.toml` | Dependências diretas e configuração do pacote |
| Versões Python | `uv.lock` | Resolução exata de dependências transitivas |
| gem5 | Submódulo Git em commit fixo | Versão específica do simulador |
| Toolchain RISC-V | Pacotes/versionamento documentado | Compilador, linker e binutils usados nos benchmarks |
| Experimentos | Arquivos YAML | CPU, cache, memória, benchmark e parâmetros de execução |
| Execuções | Logs, configuração e manifesto | Comando, hashes, saída, métricas e status de validação |

Para cada simulação bem-sucedida, a estrutura final esperada é semelhante a:

```text
results/<experimento>/<run_id>/
├── command.txt                 # Comando exato usado para invocar gem5
├── experiment.original.yaml    # Arquivo de experimento fornecido pelo usuário
├── experiment.resolved.yaml    # Configuração após aplicação de defaults/varreduras
├── manifest.json               # Metadados, versões, hashes e status da execução
├── stdout.txt                  # Saída padrão do gem5 e/ou benchmark
├── stderr.txt                  # Erros e avisos
├── config.ini                  # Configuração efetivamente instanciada pelo gem5
├── config.json                 # Representação JSON da configuração do gem5
├── stats.txt                   # Estatísticas produzidas pelo gem5
└── result.json                 # Métricas extraídas e validação funcional
```

Essa rastreabilidade permite conferir não apenas o resultado final, mas também **como** ele foi produzido.

## Principais recursos

- **Simulação arquitetural com gem5:** execução de binários RISC-V e coleta de ciclos, instruções, CPI, IPC, estatísticas de cache e métricas de memória.
- **Experimentos declarativos:** definição de CPU, clock, cache, memória, benchmark e parâmetros por arquivos YAML versionáveis.
- **Automação por CLI:** comando `riscvcnnbench` para validar configurações, planejar cenários, executar experimentos, coletar métricas e gerar relatórios.
- **Varredura de espaço de projeto:** expansão de parâmetros para comparar, por exemplo, diferentes tamanhos de L1D, associatividades, L2, modelos de CPU ou variantes de benchmark.
- **Validação funcional:** verificação de checksum ou saída de referência antes de aceitar estatísticas de desempenho.
- **Resultados estruturados:** preservação de `stats.txt`, `config.ini`, logs, manifestos, CSVs e relatórios por execução.
- **Ambiente containerizado:** uso de Podman ou Docker para isolar gem5, SCons, compiladores, QEMU e dependências de desenvolvimento do sistema host.
- **Dependências Python determinísticas:** uso de `uv`, `pyproject.toml` e `uv.lock` para recriar o mesmo ambiente Python.
- **Base para extensões customizadas:** suporte planejado para comparar uma baseline RISC-V com variantes que empreguem uma instrução customizada modelada de forma controlada.

## Estrutura do repositório

```text
riscv-cnn-bench/
├── Containerfile             # Ambiente de desenvolvimento Ubuntu 24.04
├── Makefile                  # Atalhos para container, Python, toolchain e gem5
├── pyproject.toml            # Metadados do pacote e dependências Python
├── uv.lock                   # Versões exatas das dependências Python
├── README.md                 # Visão geral e instruções de uso
├── .gitmodules               # Referência ao submódulo gem5
├── configs/
│   ├── defaults.yaml         # Valores-padrão do framework
│   └── gem5/
│       └── se_riscv.py       # Script próprio de configuração gem5 para SE
├── experiments/              # Definições versionáveis de experimentos em YAML
│   ├── smoke_test.yaml
│   └── ...
├── benchmarks/               # Código-fonte C/C++/assembly dos workloads RISC-V
│   ├── hello_riscv/          # Benchmark mínimo de validação da toolchain
│   ├── common/               # Utilitários compartilhados e rotinas de verificação
│   └── ...
├── build/                    # Binários gerados; não versionado
├── results/                  # Saídas de simulação e relatórios; não versionado
├── docs/                     # Documentação técnica e decisões de projeto
├── patches/
│   └── gem5/                 # Patches opcionais para extensões customizadas
├── scripts/                  # Scripts auxiliares de build e reprodução
├── src/
│   └── riscvcnnbench/        # Código-fonte Python do framework
│       ├── __init__.py       # Versão do pacote
│       ├── cli.py            # Interface de linha de comando
│       ├── config.py         # Leitura e validação de YAML/Pydantic
│       ├── planner.py        # Expansão de varreduras de parâmetros
│       ├── runner.py         # Execução e monitoramento do gem5
│       ├── parser.py         # Leitura de stats.txt e arquivos de saída
│       ├── metrics.py        # Cálculo de CPI, IPC, speedup e miss rate
│       ├── manifest.py       # Registro de versões, hashes e metadados
│       └── report.py         # Consolidação CSV/JSON e gráficos
├── tests/                    # Testes unitários e de integração
│   ├── fixtures/             # Pequenos exemplos de stats/config para testes
│   └── ...
└── third_party/
    └── gem5/                 # Código-fonte do gem5 como submódulo Git
```

> Os nomes de módulos descritos acima representam a arquitetura pretendida. Alguns arquivos podem ser adicionados gradualmente durante o desenvolvimento.

## Requisitos do sistema

O projeto foi projetado para rodar em Linux com uma camada de container compatível com OCI.

### Requisitos obrigatórios no host

- Sistema Linux x86-64/AMD64 recomendado para os resultados experimentais iniciais
- [Podman](https://podman.io/) ou Docker
- GNU Make
- Git
- Espaço em disco para imagem, fontes, build do gem5 e resultados
- Memória RAM suficiente para compilar o gem5; 16 GB é recomendado

### Ferramentas fornecidas pelo container

O `Containerfile` instala, entre outras dependências:

- Ubuntu 24.04 como ambiente de referência
- Compiladores C/C++ e ferramentas de build
- SCons, CMake e Ninja
- Dependências do gem5, como zlib, Protobuf, Boost, HDF5, Capstone, PNG e ELF
- Python 3, `uv`, Pytest e Ruff
- Toolchain cruzada `riscv64-linux-gnu-*`
- Binutils RISC-V, incluindo `readelf` e `objdump`
- QEMU user-mode para validação funcional rápida de binários RISC-V

O Fedora ou outra distribuição host não precisa ter gem5, toolchain RISC-V, bibliotecas de build ou pacotes Python do projeto instalados diretamente.

## Instalação

### 1. Clonar o repositório

```bash
git clone --recurse-submodules https://github.com/SEU-USUARIO/riscv-cnn-bench.git
cd riscv-cnn-bench
```

Se o repositório já foi clonado sem submódulos:

```bash
git submodule update --init --recursive
```

### 2. Construir a imagem

```bash
make image
```

Esse comando cria a imagem local:

```text
localhost/riscv-cnn-bench:dev
```

A construção pode demorar na primeira execução, pois baixa a imagem base e instala compiladores e dependências.

### 3. Verificar o ambiente

```bash
make check
```

O comando deve mostrar a arquitetura do container e versões de ferramentas como Python, `uv`, SCons e Git.

### 4. Criar o ambiente Python

```bash
make sync
```

Esse comando usa `uv` para criar ou sincronizar o ambiente virtual `.venv/` de acordo com `pyproject.toml` e `uv.lock`.

O diretório `.venv/` é gerado localmente e não deve ser enviado ao Git.

### 5. Compilar gem5 para RISC-V

```bash
make gem5-build
```

Por padrão, o Makefile utiliza quatro jobs de compilação. Para ajustar de acordo com o hardware disponível:

```bash
make gem5-build JOBS=8
```

Ou, em máquinas com menos memória:

```bash
make gem5-build JOBS=2
```

Ao final, o binário esperado é:

```text
third_party/gem5/build/RISCV/gem5.opt
```

> A compilação inicial do gem5 pode levar vários minutos e consumir memória significativa. Os arquivos gerados sob `third_party/gem5/build/` não devem ser versionados.

### 6. Verificar a toolchain RISC-V

Quando o alvo correspondente estiver disponível no Makefile:

```bash
make toolchain-check
```

A toolchain inicial usa o triplet:

```text
riscv64-linux-gnu
```

Ela gera binários ELF RISC-V 64-bit para execução em modo SE. Para programas simples, é recomendado usar linkagem estática, reduzindo dependências de loader e bibliotecas dinâmicas no ambiente simulado.

### 7. Executar verificações do projeto

```bash
make smoke-test
```

Esse alvo sincroniza dependências, testa a CLI, executa Pytest e aplica verificações de lint/formatação apenas em `src/` e `tests/`. O submódulo gem5 não é formatado por esses comandos.

## Fluxo de uso

### Trabalhar dentro do container

Para abrir um shell no ambiente de desenvolvimento:

```bash
make shell
```

O diretório atual do repositório é montado como `/workspace` no container. No Fedora, a montagem usa o sufixo `:Z` para permitir acesso sob SELinux e `--userns=keep-id` para evitar que arquivos gerados pertençam ao usuário root.

Dentro do container, comandos úteis são:

```bash
uv run riscvcnnbench version
uv run pytest -q
uv run ruff check src tests
```

### Compilar e conferir um benchmark RISC-V

Um benchmark mínimo pode ser compilado para validar a toolchain. O fluxo planejado é:

```bash
make hello-build
file build/benchmarks/hello_riscv
riscv64-linux-gnu-readelf -h build/benchmarks/hello_riscv
qemu-riscv64 build/benchmarks/hello_riscv
```

A inspeção deve indicar um ELF RISC-V; a execução em QEMU é apenas uma validação funcional rápida e não deve ser usada para medir ciclos, cache, CPI ou IPC.

### Executar a CLI

Dentro do container, ou usando `uv run`, a interface inicial é:

```bash
# Exibe a versão instalada
uv run riscvcnnbench version

# Valida um arquivo YAML de experimento
uv run riscvcnnbench validate experiments/smoke_test.yaml

# Executa um experimento
uv run riscvcnnbench run experiments/smoke_test.yaml
```

A CLI evoluirá para incluir comandos como:

```bash
riscvcnnbench plan experiments/conv2d_cache_sweep.yaml
riscvcnnbench collect results/conv2d_cache_sweep
riscvcnnbench report results/conv2d_cache_sweep
riscvcnnbench compare results/conv2d_baseline results/conv2d_custom
```

## Exemplo de experimento

O formato YAML permite definir um experimento sem editar manualmente vários arquivos internos do gem5.

```yaml
experiment:
  name: conv2d_int8_l1d_sweep
  description: Avalia Conv2D quantizada com variação de L1D.

gem5:
  binary: third_party/gem5/build/RISCV/gem5.opt
  config_script: configs/gem5/se_riscv.py
  mode: se

benchmark:
  name: conv2d_int8
  executable: build/benchmarks/conv2d_int8
  arguments: []
  expected_checksum: "1837462910"

architecture:
  cpu:
    type: timing
    cores: 1
    clock: 1GHz

  cache:
    l1i_size: 16KiB
    l1i_assoc: 2
    l1d_size:
      - 8KiB
      - 16KiB
      - 32KiB
      - 64KiB
    l1d_assoc: 2
    l2_size: 256KiB
    l2_assoc: 8

  memory:
    type: DDR3_1600_8x8
    size: 256MiB

output:
  root_dir: results
```

Nesse exemplo, a ferramenta deve expandir `l1d_size` em quatro cenários independentes, manter uma pasta por execução e gerar uma tabela consolidada para comparação.

## Comandos do Makefile

| Comando | Descrição |
|---|---|
| `make help` | Exibe os alvos e suas descrições. |
| `make image` | Constrói a imagem do container de desenvolvimento. |
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
make format
```

Evite executar formatters no diretório inteiro do repositório. Em particular, não use `ruff format .` enquanto `third_party/gem5/` estiver no workspace, pois isso pode modificar arquivos Python rastreados pelo submódulo.

## Estado do projeto

O projeto está em desenvolvimento inicial. A infraestrutura de container, ambiente Python reproduzível, automação por Makefile, compilação do gem5 e toolchain RISC-V constituem a base para as próximas etapas:

1. Compilar e validar um binário RISC-V mínimo.
2. Criar um script próprio de configuração do gem5 para SE.
3. Implementar schema YAML e comando `validate` com Pydantic.
4. Executar um único caso pelo comando `riscvcnnbench run`.
5. Extrair `simInsts`, `numCycles`, CPI e IPC de `stats.txt`.
6. Implementar varredura de parâmetros arquiteturais.
7. Adicionar microkernels CNN int8 com validação de checksum.
8. Consolidar resultados em CSV/JSON e gerar gráficos.
9. Avaliar uma instrução customizada como estudo de caso, se estiver no escopo final.

## Licença

A licença do projeto será definida antes da publicação final do repositório.

## Citação

Informações de citação acadêmica serão adicionadas em `CITATION.cff` quando o projeto alcançar uma versão publicável.