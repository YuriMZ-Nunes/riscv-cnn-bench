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

Cada execução cria uma pasta exclusiva em `results/hello_riscv/<run_id>/`, com `metadata.json`, `command.txt`, `stdout.log`, `stderr.log`, cópias do binário e da configuração em `inputs/` e os arquivos do gem5 em `gem5/`. Execuções anteriores não são sobrescritas.

O que é cada arquivo, os campos do `metadata.json`, os estados e como interpretar uma falha estão em [docs/results.md](results.md).

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

Versões de pacotes fixadas no `Containerfile`, que também fixa a imagem base `ubuntu:24.04` por digest e o `uv` na versão 0.12.23:

| Pacote | Versão |
| --- | --- |
| `gcc-riscv64-linux-gnu` | `4:13.2.0-7ubuntu1` |
| `g++-riscv64-linux-gnu` | `4:13.2.0-7ubuntu1` |
| `binutils-riscv64-linux-gnu` | `2.42-4ubuntu2.10` |
| `libc6-dev-riscv64-cross` | `2.39-0ubuntu8cross1` |
| `qemu-user` | `1:8.2.2+ds-0ubuntu1.18` |

`gcc-riscv64-linux-gnu` é um metapacote: o compilador efetivamente instalado é o GCC 13.3.0 (`13.3.0-6ubuntu2~24.04.1`), que não é fixado diretamente. Por isso, cada execução no gem5 registra em `metadata.json` a versão do compilador do ambiente e a gravada no próprio binário. Versões fixadas podem ser removidas dos repositórios do Ubuntu; nesse caso, `make image` falha e o `Containerfile` precisa ser atualizado.

Confira a versão efetiva do compilador e do emulador com:

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

O wrapper registra em `metadata.json` o commit, a branch, a URL do remoto `origin` e o estado Git do repositório principal e do checkout em `third_party/gem5`. Se essas informações não puderem ser consultadas, os campos correspondentes podem ficar sem valor.

A revisão do checkout e o hash do executável são informações distintas: alterações no código-fonte não significam que o gem5 tenha sido recompilado. Por isso, `make gem5-build` grava `gem5.opt.build-info.json` ao lado do executável, com o commit, a branch, a URL do fork, o estado do checkout e o hash do executável no momento do build. O wrapper copia esse registro para `gem5_build` em `metadata.json`, e `matches_executable` indica se o executável usado ainda é o mesmo do registro. `false` significa que o gem5 foi recompilado sem passar por `make gem5-build`; ausência do campo significa que não há registro.

O campo `environment` registra a imagem do container (nome e ID, preenchidos por `make hello-run-gem5`), a plataforma, o Python, a versão de `riscv64-linux-gnu-gcc` e o compilador gravado na seção `.comment` do próprio binário. A versão do QEMU não é registrada, pois o QEMU não participa da execução no gem5.

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
| `gem5_build` nulo ou `matches_executable` igual a `false` | O gem5 foi compilado fora de `make gem5-build`. Recompile com `make gem5-build` para registrar commit e hash do build. |

Uma execução bem-sucedida no QEMU não substitui a validação no gem5.

## Teste de ponta a ponta

```bash
make e2e-test
```

O teste [tests/test_hello_e2e.py](../tests/test_hello_e2e.py) compila o `hello_riscv` em uma pasta temporária, executa-o no gem5 pelo wrapper e verifica:

- código de saída zero do wrapper e `status: completed` com `exit_code: 0` em `metadata.json`;
- `RESULT sum=499500` e `(code=0)` em `stdout.log`;
- `simInsts`, `simTicks` e `system.cpu.numCycles` maiores que zero em `stats.txt`.

O mesmo arquivo tem um segundo teste, que roda no gem5 o exemplo [`experiments/hello_param_cache.yaml`](../experiments/hello_param_cache.yaml) (ver [formato dos experimentos](experiments.md)) e confere a soma do `hello_riscv_param` e as faltas nas caches L1d e L2.

[tests/test_run_e2e.py](../tests/test_run_e2e.py) executa `riscvcnnbench run` sobre YAMLs gerados em pasta temporária e verifica a pasta resultante (YAML, configuração resolvida, comando de build, `schema_version` 4), um build que falha (`failed_step: build`, código não zero, sem `stats.txt`), uma simulação que falha, com um gem5 falso que retorna `3` (`failed_step: simulation`), um benchmark que rejeita o argumento (`program_exit_code: 2`, diagnóstico `benchmark`) e um binário com uma instrução em `custom-0`, que o gem5 atual não reconhece (diagnóstico `instruction`).

[tests/test_parser_e2e.py](../tests/test_parser_e2e.py) executa a `fc` S (com região de interesse) e o `hello_riscv_param` (sem) nas CPUs atomic, timing, minor e o3, com e sem cache, com DDR4 e com memória `simple`, e confere as métricas lidas pelo parser com a configuração (o que deve ficar ausente) e com as linhas do próprio `stats.txt` ([results.md](results.md#métricas)). [tests/test_metric_e2e.py](../tests/test_metric_e2e.py) roda a `fc` S nas três variantes na minor, a referência com `-O3` e o par ref × custom na atomic, e confere os pares do `compare` com as métricas de cada execução, inclusive que a redução de instruções é a mesma na minor e na atomic. [tests/test_scenarios_e2e.py](../tests/test_scenarios_e2e.py) confere os cenários da RCB-18 ([scenarios.md](scenarios.md)): a latência das instruções personalizadas muda os ciclos de uma cadeia de `cnn.dot8` e não os de uma cadeia de `mul` (minor, o3 e o3-edge), a `fc` S passa nos quatro cenários de memória, as caches frias esvaziam a L1d e a L2 antes da ROI (timing e o3-edge) e a `o3-edge` tem os parâmetros configurados e IPC menor que a O3 padrão. [tests/test_campaign_e2e.py](../tests/test_campaign_e2e.py) roda uma campanha pequena pela CLI, com um grupo que falha de propósito, e confere o estado, a retomada, os pares do `compare`, os CSVs do `report` e as figuras do `plot` ([campaigns.md](campaigns.md), [report.md](report.md), [plots.md](plots.md)).

Os testes usam pastas temporárias, portanto não alteram `build/` nem `results/`. Requer o gem5 compilado; o caminho pode ser alterado com a variável `GEM5_BIN`. Fica fora de `make test` e `make smoke-test` (marcador `e2e`) por depender do gem5. Os valores das estatísticas não são comparados com referências fixas, apenas verificados como positivos.

## Limpeza e preservação

As pastas são mantidas entre execuções, mas continuam sujeitas aos comandos de limpeza:

```bash
make clean-results
make clean
```

`make clean-results` remove o conteúdo de `results/`. `make clean` também remove os resultados, além de outros artefatos locais.

Copie as execuções que deseja preservar para um local de backup antes de utilizar esses comandos. A organização por execução evita sobrescritas entre simulações, mas não substitui backup.