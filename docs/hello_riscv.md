# Executar o hello_riscv

O `hello_riscv` soma os inteiros de 0 a 999 e verifica se o resultado é `499500`. O exemplo pode ser executado com QEMU ou com gem5 em modo Syscall Emulation (SE).

## Preparação

Siga o [guia de instalação](../README.md#guia-de-instalação-e-execução) até construir a imagem com `make image`. Execute os comandos abaixo na raiz do repositório, em um terminal interativo.

Não é necessário executar `make sync` para este exemplo. O wrapper de execução do gem5 utiliza apenas a biblioteca padrão do Python.

Para o caminho com gem5, inicialize os submódulos e compile o simulador conforme o README.

## Executar com QEMU

Compile e execute:

```bash
make hello-build
make hello-run
printf 'exit_code=%s\n' "$?"
```

Além dos comandos exibidos pelo Make, a saída esperada é:

```text
RESULT sum=499500
exit_code=0
```

`hello-build` gera `build/benchmarks/hello_riscv`. `hello-run` executa esse binário com `qemu-riscv64`; ele não compila o programa automaticamente.

O fluxo QEMU descrito aqui não utiliza o wrapper de resultados do gem5 e não cria uma pasta de execução.

## Executar com gem5

Com o simulador compilado:

```bash
make hello-run-gem5
printf 'exit_code=%s\n' "$?"
```

O alvo compila o benchmark e chama `scripts/run-gem5.py`, que organiza os arquivos da execução e inicia `third_party/gem5/build/RISCV/gem5.opt`.

O alvo não compila o simulador automaticamente. Execute `make gem5-build` antes da primeira simulação ou quando precisar recompilar o gem5.

O wrapper preserva cópias do benchmark e de `configs/gem5/se_riscv.py` na pasta da execução. O gem5 utiliza essas cópias, evitando que alterações posteriores nos arquivos originais modifiquem os arquivos de entrada guardados.

O terminal informa a pasta criada e o status da execução. Exemplo ilustrativo:

```text
Resultado da execução: /workspace/results/hello_riscv/<run_id>
Status: completed
Logs: /workspace/results/hello_riscv/<run_id>
exit_code=0
```

A saída detalhada do gem5 e do programa fica em `stdout.log` e `stderr.log`, não é reproduzida integralmente no terminal.

Em uma execução bem-sucedida, `stdout.log` deve incluir:

```text
RESULT sum=499500
```

O script de configuração também registra nesse log o tick final, a causa de encerramento e o código do evento. As mensagens do gem5 e a quantidade de ticks podem variar conforme sua revisão.

### Configuração simulada

A configuração usa:

- CPU `AtomicSimpleCPU`.
- Frequência de 1 GHz.
- 512 MiB de memória simples.
- Modo de memória `atomic`.
- Nenhuma cache explícita.
- Modo Syscall Emulation, sem inicializar um sistema operacional completo.

Esse fluxo é um teste funcional, não uma avaliação detalhada de desempenho de microarquitetura.

## Organização dos resultados

Cada execução pelo wrapper cria uma pasta exclusiva em:

```text
results/hello_riscv/<run_id>/
```

O identificador combina data e horário em UTC com um sufixo aleatório. Exemplo:

```text
20261008T000507.815006Z-fd6cf822
```

Execuções anteriores não são sobrescritas.

A estrutura de uma execução é:

```text
results/hello_riscv/<run_id>/
├── metadata.json
├── command.txt
├── stdout.log
├── stderr.log
├── inputs/
│   ├── hello_riscv
│   └── se_riscv.py
└── gem5/
    ├── stats.txt
    ├── config.ini
    ├── config.json
    └── ...
```

Os arquivos efetivamente gerados em `gem5/` dependem da revisão do simulador, das ferramentas disponíveis e de até onde a execução chegou. Em caso de falha, alguns arquivos podem estar ausentes ou incompletos.

### Metadados e logs

| Arquivo | Conteúdo |
| --- | --- |
| `metadata.json` | Identificador, datas, status, código de saída do gem5 quando disponível, comando, diretório de trabalho, revisões Git, alterações locais e hashes SHA-256. |
| `command.txt` | Comando utilizado para iniciar o gem5. |
| `stdout.log` | Saída padrão do simulador e do programa executado. |
| `stderr.log` | Mensagens enviadas à saída de erro, incluindo avisos e falhas. |

O `stderr.log` pode estar vazio em uma execução sem mensagens de erro.

Os estados registrados pelo wrapper são:

- `preparing`: preparação dos arquivos.
- `running`: início da execução do simulador.
- `completed`: o simulador retornou código zero.
- `failed`: falha na preparação, inicialização ou execução.
- `interrupted`: interrupção pelo usuário tratada pelo wrapper.

Um encerramento abrupto do container ou do computador pode impedir a atualização final dos metadados. Nesse caso, a pasta pode permanecer com status `preparing` ou `running`.

### Arquivos de entrada

| Arquivo | Conteúdo |
| --- | --- |
| `inputs/hello_riscv` | Cópia do executável RISC-V utilizado na simulação. |
| `inputs/se_riscv.py` | Cópia do script de configuração utilizado na simulação. |

O wrapper registra os hashes SHA-256 dessas cópias para identificar seu conteúdo.

O executável do gem5 não é copiado para a pasta. Seu caminho e hash são registrados nos metadados. Portanto, a pasta documenta a execução, mas não constitui, sozinha, um ambiente completo e independente para reproduzi-la.

### Arquivos gerados pelo gem5

| Arquivo | Finalidade |
| --- | --- |
| `gem5/stats.txt` | Estatísticas e contadores produzidos durante a simulação. |
| `gem5/config.ini` | Configuração efetivamente instanciada, em formato INI. |
| `gem5/config.json` | Configuração efetivamente instanciada, em formato JSON. |
| `gem5/config.dot` | Descrição do grafo de componentes e conexões. |
| `gem5/config.dot.pdf` | Visualização do grafo em PDF, quando gerada. |
| `gem5/config.dot.svg` | Visualização do grafo em SVG, quando gerada. |
| `gem5/citations.bib` | Referências bibliográficas registradas pelo gem5 e seus componentes. |

`config.ini` e `config.json` descrevem a máquina simulada. `stats.txt` contém estatísticas da execução.

Os arquivos de diagrama e referências podem variar conforme o ambiente e os componentes utilizados.

## Inspecionar uma execução

Substitua `<run_id>` pelo identificador informado pelo wrapper:

```bash
RUN_DIR="results/hello_riscv/<run_id>"
```

Consulte os metadados e o comando:

```bash
python3 -m json.tool "$RUN_DIR/metadata.json"
cat "$RUN_DIR/command.txt"
```

Confira a saída do programa e as mensagens de erro:

```bash
grep -F "RESULT sum=499500" "$RUN_DIR/stdout.log"
cat "$RUN_DIR/stderr.log"
```

Verifique os principais arquivos do gem5:

```bash
test -s "$RUN_DIR/gem5/stats.txt"
test -s "$RUN_DIR/gem5/config.ini"
```

Para considerar o exemplo validado, confira em conjunto:

1. `RESULT sum=499500` em `stdout.log`.
2. Status `completed` e `exit_code` igual a `0` em `metadata.json`.
3. Código zero do alvo Make.
4. Presença dos arquivos esperados do gem5.

A presença de `stats.txt` ou `config.ini`, isoladamente, não prova que o programa terminou corretamente.

### Verificar o isolamento entre execuções

Execute duas vezes:

```bash
make hello-run-gem5
make hello-run-gem5
```

Liste as pastas:

```bash
find results/hello_riscv \
  -mindepth 1 -maxdepth 1 -type d
```

Devem existir duas novas pastas com identificadores diferentes. Cada uma deve manter seus próprios arquivos de entrada, logs, metadados e arquivos do gem5.

## Ferramentas utilizadas

A imagem padrão é `localhost/riscv-cnn-bench:dev`. O benchmark usa `riscv64-linux-gnu-gcc` com as flags:

```text
-O2 -static -march=rv64gc -mabi=lp64d -Wall -Wextra -Werror
```

Versões de pacotes observadas na imagem de desenvolvimento:

| Pacote | Versão |
| --- | --- |
| `gcc-riscv64-linux-gnu` | `4:13.2.0-7ubuntu1` |
| `g++-riscv64-linux-gnu` | `4:13.2.0-7ubuntu1` |
| `binutils-riscv64-linux-gnu` | `2.42-4ubuntu2.10` |
| `libc6-dev-riscv64-cross` | `2.39-0ubuntu8cross1` |
| `qemu-user` | `1:8.2.2+ds-0ubuntu1.18` |

A tabela registra a imagem consultada, não garante as versões de outras imagens ou reconstruções. Confira a versão efetiva do compilador e do emulador com:

```bash
make toolchain-check
podman run --rm --pull=never localhost/riscv-cnn-bench:dev \
  bash -lc 'qemu-riscv64 --version'
```

O gem5 utilizado é o checkout em `third_party/gem5`, compilado para RISC-V. Identifique sua revisão e eventuais alterações locais com:

```bash
git -C third_party/gem5 rev-parse HEAD
git -C third_party/gem5 describe --tags --always --dirty
make gem5-status
```

O wrapper registra em `metadata.json` o commit e o estado Git do repositório principal e do checkout em `third_party/gem5`. Se essas informações não puderem ser consultadas, os campos correspondentes podem ficar sem valor.

A revisão do checkout e o hash do executável são informações distintas: alterações no código-fonte não significam que o gem5 tenha sido recompilado.

Registre também as versões efetivas das ferramentas ao documentar os experimentos. O wrapper atual não coleta automaticamente as versões do compilador, do QEMU ou a identificação completa da imagem do container.

Nenhum hash específico do gem5 é estabelecido neste guia.

## Verificação e problemas

Execute cada `printf` imediatamente após o comando anterior: ele mostra o código de saída do Make.

O programa retorna `1` se a soma estiver incorreta. O Make pode reportar outro código não zero quando uma receita falha. Para a execução gem5, consulte também o código registrado em `metadata.json`, quando disponível.

Em caso de falha após a criação da pasta, o wrapper preserva os arquivos disponíveis para diagnóstico. Erros de validação anteriores à criação da pasta, como um caminho de entrada inexistente, não geram uma pasta de execução.

| Problema | Ação |
| --- | --- |
| Imagem não encontrada | Execute `make image`. |
| Benchmark não encontrado no QEMU | Execute `make hello-build`. |
| `gem5.opt` não encontrado | Execute `make gem5-build` e verifique se terminou sem erro. |
| `RESULT sum=499500` não aparece no terminal com gem5 | Consulte `stdout.log` na pasta informada pelo wrapper. |
| Status `failed` | Consulte `metadata.json`, `stderr.log` e `stdout.log`. |
| Status permanece `preparing` ou `running` após encerramento | Verifique se houve encerramento abrupto e consulte os logs disponíveis. |
| `stats.txt` ausente ou vazio | Verifique se o gem5 iniciou e até onde a simulação chegou. |
| Erro de execução no gem5 | Confira a revisão usada e preserve a pasta completa para diagnóstico. |

Uma execução bem-sucedida no QEMU não substitui a validação no gem5.

## Limpeza e preservação

As pastas são mantidas entre execuções, mas continuam sujeitas aos comandos de limpeza:

```bash
make clean-results
make clean
```

`make clean-results` remove o conteúdo de `results/`. `make clean` também remove os resultados, além de outros artefatos locais.

Copie as execuções que deseja preservar para um local de backup antes de utilizar esses comandos. A organização por execução evita sobrescritas entre simulações, mas não substitui backup.