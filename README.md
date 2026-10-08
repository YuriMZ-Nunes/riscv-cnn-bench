Sim. Eu atualizaria o README para refletir a organização por execução e, principalmente, separar o que já funciona do que ainda está planejado.

Hoje, a seção “Principais Recursos” apresenta validação YAML, automação pela CLI e consolidação de métricas como funcionalidades prontas. Pelo contexto que analisamos, elas ainda não estão implementadas. Também vale corrigir a URL de clone e esclarecer que o smoke test não executa o benchmark no gem5.

Segue uma versão **atualizada**, considerando a adoção do wrapper `scripts/run-gem5.py` e a alteração do alvo `hello-run-gem5` que montamos:

````markdown
# riscv-cnn-bench

O `riscv-cnn-bench` é um projeto em desenvolvimento para simulação e benchmark de Redes Neurais Convolucionais (CNNs) quantizadas na arquitetura RISC-V, utilizando o simulador gem5.

O objetivo é fornecer um ambiente padronizado, isolado e reprodutível para analisar o impacto de níveis de quantização, otimizações de compilador e configurações de microarquitetura no desempenho de inferência.

## Estado atual

O projeto está em estágio inicial. Atualmente, oferece:

- Ambiente de desenvolvimento containerizado com Ubuntu 24.04 e automação via Podman.
- Gerenciamento das dependências Python com `uv` e `uv.lock`.
- Compilação do gem5 para RISC-V.
- Toolchain de compilação cruzada para RISC-V 64-bit Linux.
- Benchmark funcional `hello_riscv`, executável com QEMU e gem5 em modo Syscall Emulation (SE).
- Organização dos resultados do gem5 em uma pasta exclusiva por execução.
- Preservação de logs, comando, binário, configuração e metadados da execução.
- CLI Python inicial com os comandos `version`, `validate` e `run`.
- Testes Python e verificações de código com Pytest e Ruff.

O `hello_riscv` valida o caminho de compilação e execução. Ele não é uma CNN nem um benchmark de inferência.

### Funcionalidades planejadas

- Validação semântica de configurações YAML.
- Automação de experimentos pela CLI.
- Benchmarks de CNNs e kernels quantizados.
- Exploração de modelos de CPU e hierarquias de cache.
- Extração e consolidação de métricas.
- Geração de relatórios e comparação de experimentos.

A presença de arquivos reservados para essas funcionalidades não significa que elas estejam implementadas.

## Estrutura do repositório

```text
riscv-cnn-bench/
├── Containerfile                # Ambiente de desenvolvimento Ubuntu 24.04
├── Makefile                     # Automação de tarefas via Podman
├── pyproject.toml               # Pacote Python, dependências e ferramentas
├── uv.lock                      # Lock das dependências Python
├── benchmarks/
│   └── hello_riscv/
│       ├── main.c               # Benchmark funcional de soma
│       └── Makefile             # Compilação cruzada para RISC-V
├── configs/
│   ├── defaults.yaml            # Arquivo reservado para configurações padrão
│   └── gem5/
│       └── se_riscv.py           # Configuração gem5 em modo SE
├── docs/                        # Documentação técnica
│   ├── hello_riscv.md            # Execução, resultados e diagnóstico
│   ├── toolchain.md              # Alvo de compilação e validação do binário
│   └── environment.md            # Informações do ambiente gem5
├── experiments/                 # Arquivos reservados para experimentos YAML
├── scripts/
│   ├── run-gem5.py               # Execução gem5 com preservação de resultados
│   └── ...                      # Outros scripts reservados
├── src/riscvcnnbench/
│   ├── __init__.py               # Versão do pacote
│   ├── cli.py                    # CLI inicial
│   ├── config.py                 # Reservado para validação de configurações
│   ├── metric.py                 # Reservado para tratamento de métricas
│   ├── parser.py                 # Reservado para processamento de dados
│   ├── runner.py                 # Reservado para execução pelo framework
│   └── report.py                 # Reservado para relatórios
├── tests/                       # Testes Python
├── third_party/gem5/            # Simulador gem5 como submódulo Git
├── build/                       # Artefatos de compilação, gerados localmente
└── results/                     # Resultados de execução, gerados localmente
```

Os diretórios `build/` e `results/` são gerados durante o uso e ignorados pelo Git.

## Requisitos do sistema

Para utilizar os comandos fornecidos pelo Makefile:

- Podman.
- GNU Make.
- Git.
- Terminal interativo.

O Makefile utiliza Podman com `--userns=keep-id`, montando o repositório em `/workspace` dentro do container.

Os comandos apresentados neste guia são executados na raiz do repositório.

## Guia de instalação e execução

### 1. Clonar o repositório e inicializar os submódulos

```bash
git clone [https://github.com/YuriMZ-Nunes/riscv-cnn-bench.git](https://github.com/YuriMZ-Nunes/riscv-cnn-bench.git)
cd riscv-cnn-bench

git submodule update --init --recursive
```

### 2. Construir a imagem de desenvolvimento

```bash
make image
```

A imagem padrão é:

```text
localhost/riscv-cnn-bench:dev
```

Confira as ferramentas disponíveis:

```bash
make check
make toolchain-check
```

### 3. Sincronizar o ambiente Python

Para desenvolver e utilizar o pacote Python:

```bash
make sync
```

Esse comando cria ou sincroniza `.venv` dentro do diretório de trabalho compartilhado com o container.

A sincronização Python não é necessária para executar o `hello_riscv` pelos alvos Make. O wrapper `scripts/run-gem5.py` utiliza apenas a biblioteca padrão do Python.

### 4. Compilar o gem5 para RISC-V

```bash
make gem5-build
```

Por padrão, a compilação utiliza quatro jobs. Para ajustar o paralelismo:

```bash
make gem5-build JOBS=8
```

O executável esperado é:

```text
third_party/gem5/build/RISCV/gem5.opt
```

O tempo e o consumo de recursos da compilação dependem do ambiente. Ajuste `JOBS` conforme os recursos disponíveis.

### 5. Executar a verificação do framework Python

```bash
make smoke-test
```

Esse comando:

1. Sincroniza as dependências Python.
2. Executa o comando de versão da CLI.
3. Executa os testes com Pytest.
4. Executa o lint com Ruff.
5. Verifica a formatação de `src/` e `tests/`.

O smoke test não compila o gem5 e não executa o `hello_riscv` em QEMU ou gem5.

### 6. Executar o exemplo funcional

Com QEMU:

```bash
make hello-build
make hello-run
printf 'exit_code=%s\n' "$?"
```

A saída esperada inclui:

```text
RESULT sum=499500
exit_code=0
```

Com gem5 previamente compilado:

```bash
make hello-run-gem5
printf 'exit_code=%s\n' "$?"
```

O alvo compila o benchmark e executa o wrapper de resultados. A saída detalhada do simulador e do programa é gravada nos logs da execução.

Consulte o [guia do hello_riscv](docs/hello_riscv.md) para os critérios de sucesso, a configuração simulada e os procedimentos de diagnóstico.

## Resultados por execução

Cada execução de `make hello-run-gem5` cria uma pasta exclusiva:

```text
results/hello_riscv/<run_id>/
```

O identificador combina data e horário em UTC com um sufixo aleatório. Execuções anteriores não são sobrescritas.

Estrutura:

```text
results/hello_riscv/<run_id>/
├── metadata.json                # Identificação, status, revisões e hashes
├── command.txt                  # Comando utilizado
├── stdout.log                   # Saída padrão do gem5 e do programa
├── stderr.log                   # Avisos e erros
├── inputs/
│   ├── hello_riscv              # Cópia do binário executado
│   └── se_riscv.py              # Cópia da configuração utilizada
└── gem5/
    ├── stats.txt                # Estatísticas da simulação
    ├── config.ini               # Configuração efetivamente instanciada
    ├── config.json              # Configuração em JSON
    └── ...                      # Outros arquivos produzidos pelo gem5
```

O wrapper executa as cópias preservadas em `inputs/`. Alterações posteriores no binário ou na configuração original não modificam essas cópias.

O arquivo `metadata.json` registra informações como:

- Identificador e datas da execução.
- Status e código de saída do gem5, quando disponível.
- Comando e diretório de trabalho.
- Revisões Git e estado de alterações locais.
- Caminhos originais.
- Hashes SHA-256 do binário, da configuração e do executável gem5.

Os arquivos disponíveis em `gem5/` dependem da revisão do simulador e do andamento da execução. Falhas podem deixar arquivos ausentes ou incompletos.

A pasta preserva informações para auditoria e diagnóstico, mas não representa, sozinha, um ambiente completo para reprodução: o executável gem5 e a imagem do container não são copiados para ela.

Para inspecionar uma execução, consulte o [guia de resultados do hello_riscv](docs/hello_riscv.md#organização-dos-resultados).

## Comandos do Makefile

| Comando | Descrição |
| --- | --- |
| `make help` | Exibe os comandos disponíveis. |
| `make image` | Constrói a imagem de desenvolvimento. |
| `make image-clean` | Remove a imagem local, preservando código e resultados. |
| `make shell` | Abre um terminal Bash no container, na raiz do projeto. |
| `make check` | Exibe a arquitetura e versões de Python, uv, SCons e Git. |
| `make toolchain-check` | Exibe caminhos e versões do GCC, G++ e objdump RISC-V. |
| `make lock` | Resolve dependências Python e atualiza `uv.lock`. |
| `make sync` | Cria ou sincroniza `.venv` com as dependências de desenvolvimento. |
| `make test` | Executa os testes Python com Pytest. |
| `make lint` | Executa Ruff em `src/` e `tests/`. |
| `make format-check` | Verifica a formatação de `src/` e `tests/` sem alterar arquivos. |
| `make format` | Formata `src/` e `tests/` e aplica correções automáticas do Ruff. |
| `make gem5-status` | Exibe alterações locais no submódulo gem5. |
| `make gem5-build` | Compila o gem5 para RISC-V. Aceita `JOBS=N`. |
| `make gem5-clean` | Remove artefatos de compilação do gem5, preservando suas fontes. |
| `make benchmark-build` | Placeholder; atualmente apenas exibe uma mensagem. |
| `make hello-build` | Compila `hello_riscv` em `build/benchmarks/hello_riscv`. |
| `make hello-run` | Executa o benchmark com QEMU. Requer compilação prévia. |
| `make hello-run-gem5` | Compila o benchmark e o executa em gem5 SE, criando uma pasta exclusiva de resultados. Requer gem5 previamente compilado. |
| `make smoke-test` | Sincroniza dependências e executa versão da CLI, testes, lint e verificação de formatação. |
| `make clean-results` | Remove o conteúdo de `results/`. |
| `make clean` | Remove ambientes virtuais, caches selecionados, artefatos locais e resultados, preservando as fontes do gem5. |
| `make status` | Exibe o estado Git do repositório principal e do submódulo gem5. |

## CLI Python

Para utilizar a CLI, sincronize o ambiente com `make sync` e abra o container:

```bash
make shell
```

Dentro dele:

### Exibir a versão

```bash
uv run riscvcnnbench version
```

### Verificar a existência de um arquivo de experimento

```bash
uv run riscvcnnbench validate experiments/smoke_test.yaml
```

Atualmente, `validate` verifica apenas se o caminho corresponde a um arquivo existente. Ele não valida o conteúdo YAML nem seus parâmetros.

### Comando reservado para execução de experimentos

```bash
uv run riscvcnnbench run experiments/smoke_test.yaml
```

Atualmente, `run` verifica a existência do arquivo e imprime uma mensagem de execução futura. Ele ainda não inicia o gem5 nem gera resultados.

Para executar o exemplo funcional, utilize `make hello-run-gem5`.

## Reprodutibilidade e limitações

O projeto utiliza containerização, lock de dependências Python e preservação de arquivos por execução para melhorar a rastreabilidade.

Esses mecanismos têm limites:

- `uv.lock` registra as versões resolvidas das dependências Python.
- Os pacotes do sistema e a instalação do uv no Containerfile não estão fixados individualmente.
- Reconstruções da imagem podem instalar versões diferentes das ferramentas.
- A revisão Git do gem5 identifica o checkout, mas não garante que seu executável tenha sido recompilado após alterações.
- Alterações locais são sinalizadas nos metadados; o wrapper não preserva automaticamente um patch completo do repositório.
- O wrapper atual não coleta automaticamente todas as versões de ferramentas nem a identificação completa da imagem do container.

Registre as versões efetivas e preserve o ambiente necessário ao documentar experimentos.

A configuração atual do `hello_riscv` utiliza `AtomicSimpleCPU`, memória simples e nenhuma cache explícita. Ela serve como validação funcional, não como avaliação detalhada de microarquitetura.

## Limpeza e preservação dos resultados

Os comandos abaixo removem resultados:

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
````