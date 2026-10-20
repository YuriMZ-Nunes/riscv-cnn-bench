# Resultados de uma execução

Cada execução no gem5, por `riscvcnnbench run` ou `make hello-run-gem5`, cria uma pasta própria que nunca é reaproveitada nem sobrescrita. Este guia explica o que há na pasta e como interpretar cada arquivo.

## Onde fica

| Origem | Pasta |
| --- | --- |
| `riscvcnnbench run <yaml>` / `make run EXPERIMENT=<yaml>` | `<output.dir>/<run_id>/`, padrão `results/<name>/<run_id>/` |
| `make hello-run-gem5` | `results/hello_riscv/<run_id>/` |

O `run_id` combina data e hora em UTC com um sufixo aleatório, por exemplo `20261020T005249.889088Z-194128aa`. Ordenar as pastas pelo nome as ordena por horário.

O terminal informa a pasta e o status ao final:

```text
Resultado da execução: /workspace/results/hello_param_cache/<run_id>
Status: completed
Logs: /workspace/results/hello_param_cache/<run_id>
```

Os caminhos começam com `/workspace` porque a execução acontece dentro do container, onde a raiz do projeto é montada nesse ponto.

## Estrutura

```text
<run_id>/
├── metadata.json                 # Ficha da execução: status, o que rodou, com o quê
├── command.txt                   # Comandos de build e do gem5, prontos para copiar
├── stdout.log                    # Saída do gem5 e do programa simulado
├── stderr.log                    # Avisos e erros
├── build.log                     # Saída do make (somente riscvcnnbench run)
├── inputs/
│   ├── <benchmark>               # Binário RISC-V simulado
│   ├── <config gem5>.py          # se_riscv_configurable.py ou se_riscv.py
│   ├── experiment.yaml           # YAML como escrito (somente riscvcnnbench run)
│   ├── experiment.resolved.json  # YAML com padrões preenchidos (somente riscvcnnbench run)
│   ├── project.diff              # Somente se o projeto tinha alterações não commitadas
│   └── gem5_repository.diff      # Somente se o gem5 tinha alterações não commitadas
└── gem5/
    ├── stats.txt                 # Estatísticas da simulação
    ├── config.ini, config.json   # Máquina efetivamente montada
    ├── config.dot*               # Diagrama da máquina
    └── citations.bib             # Referências do gem5
```

Em caso de falha, alguns arquivos podem faltar ou estar incompletos: por exemplo, uma falha de build não gera nada em `gem5/`.

## Por onde começar

1. **`metadata.json` → `status`.** Se não for `completed`, veja `failed_step` e `error` (seção [Status e falhas](#status-e-falhas)).
2. **`stdout.log`.** Confira a linha `RESULT` do benchmark e a linha `Simulação encerrada ... (code=0)`.
3. **`gem5/stats.txt`.** Só depois que os dois passos anteriores estão corretos os números fazem sentido.

## Arquivos

### `metadata.json`

Ficha da execução, em JSON. Leia com `python3 -m json.tool metadata.json`. Os campos se agrupam assim:

| Pergunta | Campos |
| --- | --- |
| Deu certo? | `status`, `failed_step`, `exit_code`, `error` (só em falha) |
| Quando? | `run_id`, `started_at`, `finished_at` (UTC) |
| O que foi pedido? | `experiment.resolved` (configuração completa), `experiment.source` (YAML original), `experiment.sha256` |
| Como foi compilado? | `build.command`, `build.exit_code`, `build.log` |
| Como o gem5 foi chamado? | `command` (lista), `cwd`, `original_config`, `original_binary` |
| Quais arquivos exatamente? | `binary_sha256`, `config_sha256`, `gem5_sha256` |
| Qual versão do código? | `project` e `gem5_repository` (`commit`, `dirty`, `status`), `diffs` |
| Qual gem5? | `gem5_executable`, `gem5_version`, `gem5_build` |
| Qual ambiente? | `environment` (imagem do container, plataforma, Python, compilador) |

Detalhes de alguns campos:

- **`exit_code`** é o código de saída do gem5. As configurações em `configs/gem5/` terminam com o código do programa simulado, então `0` significa que o gem5 rodou e o programa retornou `0`. Fica `null` se o gem5 nem chegou a rodar (por exemplo, falha de build).
- **`experiment.resolved`** é o que permite comparar execuções: duas pastas que diferem em um só parâmetro diferem só nesse campo do `resolved`. `experiment` fica `null` quando o wrapper é chamado sem YAML (`make hello-run-gem5`).
- **`project.dirty` / `gem5_repository.dirty`** indicam alterações não commitadas no momento da execução. Nesse caso `diffs` aponta para os arquivos `inputs/*.diff`. Arquivos não rastreados não entram no diff; aparecem apenas em `status`.
- **`gem5_build`** é o registro gravado por `make gem5-build` ao lado do executável (`gem5.opt.build-info.json`): commit do gem5 no momento do build e hash do executável. `matches_executable: true` confirma que o executável usado é o mesmo daquele build. `false` ou `gem5_build: null` significa que o gem5 foi compilado fora de `make gem5-build`, e então o commit do checkout não garante de qual código o executável veio.
- **`environment`**: `container_image` e `container_image_id` são preenchidos pelos alvos do Makefile (`make run`, `make hello-run-gem5`) e ficam `null` quando se chama a CLI direto no `make shell`. `binary_compiler` é o compilador gravado dentro do próprio binário, que vale mesmo se a toolchain mudar depois.

### `stdout.log`

Saída do gem5 misturada com a do programa simulado. Exemplo real (`hello_param_cache.yaml`), sem o cabeçalho do gem5:

```text
Executando: .../inputs/hello_riscv_param 65536 2
Sistema: cpu=timing clock=2GHz l1i=32KiB l1d=32KiB l2=256KiB memória=ddr4/512MiB
RESULT n=65536 repeat=2 sum=4294901760
Simulação encerrada no tick 1865429000: exiting with last active thread context (code=0)
```

| Linha | Origem | Significado |
| --- | --- | --- |
| Cabeçalho (`gem5 version`, `command line`...) | gem5 | Versão e comando efetivo. |
| `Executando:` | config gem5 | Binário e argumentos passados ao programa. |
| `Sistema:` | `se_riscv_configurable.py` | Máquina montada; confira se bate com o YAML. Não aparece com `se_riscv.py`. |
| `RESULT ...` | programa simulado | Resultado calculado pelo benchmark. |
| `Simulação encerrada no tick N: <causa> (code=C)` | config gem5 | `C` é o código de saída do programa. A causa normal é `exiting with last active thread context`. |

O tick é a unidade de tempo do gem5 (aqui, 10¹² ticks por segundo, ver `Global frequency`), **não** um ciclo da CPU. Ciclos ficam em `stats.txt`.

### `stderr.log`

Avisos e erros do gem5. Avisos (`warn:`) e informações (`info:`) são comuns e, em geral, inofensivos. Exemplos que aparecem normalmente:

- `DRAM device capacity (16384 Mbytes) does not match the address range assigned (512 Mbytes)`: o modelo DDR4 descreve um chip maior que a memória simulada; esperado com `memory.type: ddr4`.
- `ignoring syscall set_robust_list(...)`: chamada de sistema que o modo SE não implementa e que não afeta os benchmarks.
- `system.remote_gdb: Listening for connections on port 7000`: o gem5 abre uma porta de depuração; não é usada.

Linhas com `fatal:` ou `panic:` indicam erro do gem5. Em uma falha de preparação ou build, o wrapper grava aqui também o `error` do `metadata.json`.

### `build.log`

Saída completa do `make` do benchmark (somente com `riscvcnnbench run`). A linha do compilador mostra as flags efetivas: as do YAML (`compiler.flags`) seguidas das obrigatórias do Makefile. Se `failed_step` for `build`, a mensagem do compilador está aqui.

### `command.txt`

Os comandos exatos, um por linha, prontos para copiar e repetir dentro do container. Com `riscvcnnbench run` há dois, marcados com `# build` e `# gem5`; com `make hello-run-gem5`, só o do gem5. É o que o YAML virou: o mesmo conteúdo está em `build.command` e `command` no `metadata.json`.

### `inputs/`

Cópias do que entrou na simulação, para que alterações posteriores nos originais não mudem o que ficou registrado. O gem5 usa as cópias, não os originais.

| Arquivo | Conteúdo |
| --- | --- |
| `<benchmark>` | Binário RISC-V simulado. Com `riscvcnnbench run`, é compilado direto aqui; com `make hello-run-gem5`, é copiado de `build/`. Hash em `binary_sha256`. |
| `se_riscv_configurable.py` ou `se_riscv.py` | Configuração gem5 usada. Hash em `config_sha256`. |
| `experiment.yaml` | YAML exatamente como escrito, inclusive comentários. |
| `experiment.resolved.json` | Configuração com todos os padrões preenchidos e `output.dir` absoluto. Igual a `experiment.resolved` no `metadata.json`. |
| `project.diff`, `gem5_repository.diff` | Alterações rastreadas em relação ao commit registrado. Só existem se havia alterações. |

O executável do gem5 não é copiado (é grande); ele é identificado por caminho, hash e `gem5_build`. A pasta documenta a execução, mas não é, sozinha, um ambiente completo para reproduzi-la.

### `gem5/`

Arquivos gerados pelo próprio gem5 (`--outdir`).

| Arquivo | Conteúdo |
| --- | --- |
| `stats.txt` | Estatísticas da simulação: uma por linha, `nome valor # descrição`. |
| `config.ini` / `config.json` | Todos os objetos que o gem5 instanciou e seus parâmetros. Use para confirmar que a máquina pedida é a simulada, por exemplo `grep -A3 '\[system.cpu.dcache\]' config.ini`. |
| `config.dot`, `.pdf`, `.svg` | Diagrama dos componentes e conexões; útil para visualizar a hierarquia de cache. Gerados quando o ambiente permite. |
| `citations.bib` | Referências bibliográficas dos componentes do gem5 usados. |

Algumas estatísticas de `stats.txt` úteis para conferir uma execução:

| Estatística | Significado |
| --- | --- |
| `simInsts` | Instruções executadas (inclui inicialização do programa, não só o kernel). |
| `simTicks` | Tempo simulado, em ticks. |
| `system.cpu.numCycles` | Ciclos da CPU. |
| `system.cpu.dcache.overallMisses::total` | Faltas na L1 de dados (só com `cache.l1d`). |
| `system.l2cache.overallMisses::total` | Faltas na L2 (só com `cache.l2`). |

Os números cobrem a execução inteira do programa, incluindo a inicialização. Medir apenas a região de interesse e definir as métricas do TCC (IPC por operação etc.) está planejado (RCB-09, RCB-11 e RCB-16) e ainda não existe.

## Status e falhas

| `status` | Significado |
| --- | --- |
| `preparing` | Preparando arquivos. |
| `building` | Compilando o benchmark (somente `riscvcnnbench run`). |
| `running` | gem5 em execução. |
| `completed` | gem5 retornou `0`. |
| `failed` | Algo falhou; veja `failed_step` e `error`. |
| `interrupted` | Interrompido pelo usuário (Ctrl+C). |

Se a pasta ficar em `preparing`, `building` ou `running` depois que tudo terminou, a execução foi encerrada abruptamente (container ou computador desligado) antes de atualizar os metadados.

| `failed_step` | Onde olhar |
| --- | --- |
| `preparation` | `error` no `metadata.json` e `stderr.log`. |
| `build` | `build.log`; `build.exit_code` é o código do `make` e `exit_code` fica `null`. |
| `simulation` | `stderr.log` e o final de `stdout.log`; `exit_code` é o código do gem5. |

Em `simulation`, um `exit_code` diferente de zero pode ter duas causas: o **programa** retornou erro (por exemplo, o benchmark detectou resultado incorreto; a linha `Simulação encerrada ... (code=N)` aparece no `stdout.log`) ou o **gem5** falhou (`fatal:`/`panic:` no `stderr.log`, sem a linha `Simulação encerrada`). Distinguir os dois automaticamente está planejado (RCB-08).

Erros detectados antes de criar a pasta, como YAML inválido ou gem5 inexistente, não geram pasta; aparecem só no terminal.

### Quando considerar uma execução válida

Confira em conjunto:

1. `status: completed` e `exit_code: 0` no `metadata.json`;
2. a linha `RESULT` esperada no `stdout.log`;
3. `code=0` na linha `Simulação encerrada` do `stdout.log`;
4. para resultados que serão comparados, `project.dirty: false` e `gem5_build.matches_executable: true`.

`stats.txt` existir, isoladamente, não prova que o programa terminou corretamente.

## Versões do formato (`schema_version`)

| Versão | Mudança |
| --- | --- |
| `3` | `failed_step`, `experiment` (YAML original e configuração resolvida) e `build` (comando, código e log do build); estado `building`. Usado por `riscvcnnbench run`. |
| `2` | Proveniência: commits, diffs, hashes, versão e build-info do gem5, ambiente. |

Pastas antigas mantêm a versão com que foram criadas.

## Comandos úteis

```bash
RUN=results/hello_param_cache/<run_id>

python3 -m json.tool $RUN/metadata.json | less
python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["status"], m["failed_step"], m["exit_code"])' $RUN/metadata.json
cat $RUN/command.txt
grep -E '^(Sistema|RESULT|Simulação)' $RUN/stdout.log
grep -E 'fatal|panic' $RUN/stderr.log
grep -E '^(simInsts|simTicks|system.cpu.numCycles) ' $RUN/gem5/stats.txt

# O que mudou entre duas execuções
diff $RUN_A/inputs/experiment.resolved.json $RUN_B/inputs/experiment.resolved.json
```
