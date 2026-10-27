# Resultados de uma execução

Cada execução no gem5, por `riscvcnnbench run` ou `make hello-run-gem5`, cria uma pasta própria que nunca é reaproveitada nem sobrescrita. Este guia explica o que há na pasta e como interpretar cada arquivo.

## Onde fica

| Origem | Pasta |
| --- | --- |
| `riscvcnnbench run <yaml>` / `make run EXPERIMENT=<yaml>` | `<output.dir>/<run_id>/`, padrão `results/<name>/<run_id>/` |
| `make hello-run-gem5` | `results/hello_riscv/<run_id>/` |
| `riscvcnnbench campaign run <matriz>` / `make campaign MATRIX=<matriz>` | `results/campaigns/<name>/runs/<combinação>/<run_id>/`, uma por combinação, mais os arquivos da campanha ([campaigns.md](campaigns.md#pasta-da-campanha)) |

O `run_id` combina data e hora em UTC com um sufixo aleatório, por exemplo `20261020T005249.889088Z-194128aa`. Ordenar as pastas pelo nome as ordena por horário.

O `riscvcnnbench run` informa a pasta no início e, ao final, a pasta, o status e, se falhou, a causa (ver [Diagnóstico](#diagnóstico)); se concluiu, um resumo das [métricas](#métricas):

```text
Executando hello_param_cache em results/hello_param_cache/<run_id>
Pasta:  results/hello_param_cache/<run_id>
Status: completed
Métricas: programa inteiro, 822504 instruções, 3730858 ciclos, IPC 0.220
```

O `hello_riscv_param` não marca região de interesse, então o resumo é do programa inteiro; nos benchmarks de operação ele começa com `ROI`.

O `make hello-run-gem5` chama o wrapper direto e imprime `Resultado da execução: ...`, `Status: ...` e `Logs: ...`, com caminhos que começam em `/workspace`, onde o container monta a raiz do projeto.

Para listar as execuções existentes, veja [Listar execuções](#listar-execuções).

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
3. **`gem5/stats.txt`.** Só depois que os dois passos anteriores estão corretos os números fazem sentido. `riscvcnnbench stats <pasta>` lê o bloco certo e mostra as métricas (seção [Métricas](#métricas)).

## Arquivos

### `metadata.json`

Ficha da execução, em JSON. Leia com `python3 -m json.tool metadata.json`. Os campos se agrupam assim:

| Pergunta | Campos |
| --- | --- |
| Deu certo? | `status`, `failed_step`, `exit_code`, `program_exit_code`, `exit_cause`, `error` (só em falha) |
| Quando? | `run_id`, `started_at`, `finished_at` (UTC) |
| O que foi pedido? | `experiment.resolved` (configuração completa), `experiment.source` (YAML original), `experiment.sha256` |
| Como foi compilado? | `build.command`, `build.exit_code`, `build.log` |
| Como o gem5 foi chamado? | `command` (lista), `cwd`, `original_config`, `original_binary` |
| Quais arquivos exatamente? | `binary_sha256`, `config_sha256`, `gem5_sha256` |
| Qual versão do código? | `project` e `gem5_repository` (`commit`, `branch`, `remote_url`, `dirty`, `status`), `diffs` |
| Qual gem5? | `gem5_executable`, `gem5_version`, `gem5_build` |
| Qual ambiente? | `environment` (imagem do container, plataforma, Python, compilador) |

Detalhes de alguns campos:

- **`exit_code`** é o código de saída do gem5. As configurações em `configs/gem5/` terminam com o código do programa simulado, então `0` significa que o gem5 rodou e o programa retornou `0`. Fica `null` se o gem5 nem chegou a rodar (por exemplo, falha de build).
- **`program_exit_code`** e **`exit_cause`** vêm da linha `Simulação encerrada ... : <causa> (code=N)` do `stdout.log`: o código com que o **programa** terminou e a causa informada pelo gem5. Ficam `null` quando a linha não aparece, isto é, quando o gem5 parou antes de a simulação terminar (erro do gem5). Assim, `exit_code` ≠ 0 com `program_exit_code` preenchido é falha do benchmark; com `program_exit_code: null`, é falha do gem5.
- **`experiment.resolved`** é o que permite comparar execuções: duas pastas que diferem em um só parâmetro diferem só nesse campo do `resolved`. `experiment` fica `null` quando o wrapper é chamado sem YAML (`make hello-run-gem5`).
- **`branch` / `remote_url`** dizem de onde veio o código: a branch do checkout e a URL do remoto `origin`, sem usuário nem token. No gem5, identificam o fork e a branch com as instruções personalizadas. `branch` fica `null` com HEAD destacado, que é o estado comum de um submódulo depois de `git submodule update`; o `commit` continua identificando o código.
- **`project.dirty` / `gem5_repository.dirty`** indicam alterações não commitadas no momento da execução. Nesse caso `diffs` aponta para os arquivos `inputs/*.diff`. Arquivos não rastreados não entram no diff; aparecem apenas em `status`.
- **`gem5_build`** é o registro gravado por `make gem5-build` ao lado do executável (`gem5.opt.build-info.json`): commit, branch e URL do gem5 no momento do build e hash do executável. `matches_executable: true` confirma que o executável usado é o mesmo daquele build. `false` ou `gem5_build: null` significa que o gem5 foi compilado fora de `make gem5-build`, e então o commit do checkout não garante de qual código o executável veio.
- **`environment`**: `container_image` e `container_image_id` são preenchidos pelos alvos do Makefile (`make run`, `make hello-run-gem5` e, desde a RCB-24, `make campaign`) e ficam `null` quando se chama a CLI direto no `make shell`. `binary_compiler` é o compilador gravado dentro do próprio binário, que vale mesmo se a toolchain mudar depois.

### `stdout.log`

Saída do gem5 misturada com a do programa simulado. Exemplo real (`hello_param_cache.yaml`), sem o cabeçalho do gem5:

```text
Executando: .../inputs/hello_riscv_param 65536 2
Sistema: cpu=timing clock=2GHz vlen=256 custom_latency=3 l1i=32KiB l1d=32KiB l2=256KiB memória=ddr4/512MiB caches_roi=warm
RESULT n=65536 repeat=2 sum=4294901760
Simulação encerrada no tick 1865429000: exiting with last active thread context (code=0)
```

| Linha | Origem | Significado |
| --- | --- | --- |
| Cabeçalho (`gem5 version`, `command line`...) | gem5 | Versão e comando efetivo. |
| `Executando:` | config gem5 | Binário e argumentos passados ao programa. |
| `Sistema:` | `se_riscv_configurable.py` | Máquina montada; confira se bate com o YAML. Não aparece com `se_riscv.py`. |
| `Caches esvaziadas antes da ROI no tick N` | `se_riscv_configurable.py` | Só com `benchmark.cache_state: cold`: o gem5 esvaziou as caches no início da ROI ([scenarios.md](scenarios.md#estado-das-caches-no-início-da-roi)). |
| `RESULT ...` | programa simulado | Resultado calculado pelo benchmark. |
| `Simulação encerrada no tick N: <causa> (code=C)` | config gem5 | `C` é o código de saída do programa. A causa normal é `exiting with last active thread context`. |
| `Simulação interrompida no tick N: user interrupt received` | config gem5 | O gem5 recebeu SIGINT (Ctrl+C) antes do fim do programa. A configuração sai com `130`, a execução fica `failed` sem `program_exit_code`, e o diagnóstico é `interrupted`: as estatísticas estão incompletas. Até a RCB-19, esse caso saía com `0` e passava por `completed` |

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
| `simInsts` | Instruções executadas no bloco: o programa inteiro, ou só a região de interesse no primeiro bloco dos benchmarks que a marcam. |
| `simTicks` | Tempo simulado, em ticks. |
| `system.cpu.numCycles` | Ciclos da CPU. Na atomic, é só `simTicks` dividido pelo período do clock. |
| `system.cpu.dcache.overallMisses::total` | Faltas na L1 de dados (só com `cache.l1d`). |
| `system.l2cache.overallMisses::total` | Faltas na L2 (só com `cache.l2`). |

Nos benchmarks sem região de interesse (`hello_riscv`, `hello_riscv_param`, `cnn_insn_semantics`), o `stats.txt` tem um bloco só, com a execução inteira, incluindo a inicialização.

Os benchmarks que usam a base comum marcam a região de interesse (ROI) com m5ops, e o `stats.txt` fica com dois blocos. Cada um começa com `---------- Begin Simulation Statistics ----------`:

| Bloco | Cobre |
| --- | --- |
| 1 | Só a ROI, isto é, o kernel com as suas repetições |
| 2 | Do fim da ROI ao fim do programa: verificação, impressão e saída |

A inicialização antes da ROI não aparece em nenhum bloco. Isso vale para o `int8_base_example` e para os sete benchmarks de operação ([kernels.md](kernels.md)). Os detalhes estão em [kernel_base.md](kernel_base.md#região-de-interesse). O framework escolhe o bloco e extrai as métricas sozinho; veja [Métricas](#métricas).

## Métricas

O framework lê o `gem5/stats.txt` de uma execução e extrai, do bloco da região de interesse, as métricas definidas em [scope.md](scope.md#métricas), sem alterar nenhum arquivo da pasta. O código está em `src/riscvcnnbench/parser.py`. Há três formas de ver as métricas:

| Onde | O que mostra |
| --- | --- |
| Fim do `riscvcnnbench run` | Linha `Métricas: ROI, <N> instruções, <C> ciclos, IPC <x>`, só se a execução foi concluída |
| `riscvcnnbench runs` | Colunas `INSTS`, `CICLOS` e `IPC` ([Listar execuções](#listar-execuções)) |
| `riscvcnnbench stats <pasta>` ou `make stats RUN=<pasta>` | Todas as métricas, brutas e [derivadas](#métricas-derivadas-e-comparações), com unidade, origem e motivo das ausentes; `--json` para scripts |
| `riscvcnnbench compare <pasta>` ou `make compare DIR=<pasta>` | Pares de execuções: redução de instruções, speedup em ciclos e razão de IPC ([Comparações](#comparações)) |

Nada é gravado na pasta: o `stats.txt` e o `stdout.log` continuam sendo a fonte, e tudo funciona também com pastas antigas e com as de `make hello-run-gem5`.

### Qual bloco é lido

| Benchmark | Blocos esperados | Bloco lido |
| --- | --- | --- |
| Marca a ROI, isto é, chama `rcb_roi_begin` em algum `.c` da pasta: as sete operações e o `int8_base_example` | 2 | O 1º, a ROI |
| Não marca ROI: `hello_riscv`, `hello_riscv_param`, `cnn_insn_semantics` | 1 | O único, com o programa inteiro |

Se o número de blocos for outro, o parser recusa o arquivo com uma mensagem como `1 bloco, mas o benchmark marca a região de interesse e deveria ter 2 (a ROI e o resto do programa)`, em vez de ler o bloco errado. Isso acontece, por exemplo, se o programa terminar dentro da ROI. Se o benchmark não existe mais em `benchmarks/`, um bloco é lido como programa inteiro e dois como ROI. Um bloco sem a linha `End Simulation Statistics`, de uma simulação interrompida, também é recusado.

### Métricas extraídas

Os nomes das estatísticas ficam num só lugar, a tabela `METRICS` de `parser.py`. A chave é o nome que o framework usa, por exemplo no JSON do `stats`.

| Chave | Estatística do gem5 | Unidade | Ausente quando |
| --- | --- | --- | --- |
| `insts` | `system.cpu.commitStats0.numInsts` | instruções | Nunca |
| `ops` | `system.cpu.commitStats0.numOps` | micro-ops | Nunca |
| `cycles` | `system.cpu.numCycles` | ciclos | CPU atomic |
| `ipc` | `system.cpu.ipc` | instruções/ciclo | CPU atomic |
| `sim_ticks` | `simTicks` | ticks | CPU atomic |
| `loads`, `stores`, `mem_refs` | `system.cpu.commitStats0.numLoadInsts`, `numStoreInsts`, `numMemRefs` | instruções | Nunca |
| `branch_mispredicts` | `system.cpu.branchPred.condIncorrect` | desvios | CPUs atomic e timing, que não têm preditor |
| `l1i_accesses`, `l1d_accesses`, `l2_accesses` | `system.cpu.icache.`, `system.cpu.dcache.`, `system.l2cache.` + `overallAccesses::total` | acessos | Nível de cache não configurado |
| `l1i_misses`, `l1d_misses`, `l2_misses` | (mesmos prefixos) + `overallMisses::total` | faltas | Nível não configurado |
| `l1i_miss_rate`, `l1d_miss_rate`, `l2_miss_rate` | (mesmos prefixos) + `overallMissRate::total` | razão | Nível não configurado; nenhum acesso (0/0) |
| `l1i_avg_miss_latency`, `l1d_avg_miss_latency`, `l2_avg_miss_latency` | (mesmos prefixos) + `demandAvgMissLatency::total` | ticks | Nível não configurado; nenhuma falta; CPU atomic |
| `dram_reads`, `dram_writes` | `system.mem_ctrl.readReqs`, `system.mem_ctrl.writeReqs` | requisições | Memória `simple` |
| `dram_bandwidth` | `system.mem_ctrl.dram.bwTotal::total` | bytes/s | Memória `simple`; CPU atomic |
| `dram_avg_latency` | `system.mem_ctrl.dram.avgMemAccLat` | ticks | Memória `simple`; nenhum acesso; CPU atomic |
| `simple_bytes_read`, `simple_bytes_written` | `system.memory.bytesRead::total`, `system.memory.bytesWritten::total` | bytes | Memória `ddr4` |
| `simple_reads`, `simple_writes` | `system.memory.numReads::total`, `system.memory.numWrites::total` | requisições | Memória `ddr4` |
| `host_seconds` | `hostSeconds` | s | Nunca. É o tempo do host, não do sistema simulado, e varia entre execuções |

Latências estão em ticks, como no gem5 (10¹² por segundo; com clock de 1GHz, 1000 ticks = 1 ciclo). As métricas derivadas (CPI, ciclos por MAC) e as comparações estão em [Métricas derivadas e comparações](#métricas-derivadas-e-comparações).

### Ausências e zeros omitidos

Uma métrica que não se aplica fica **ausente**: `null` no JSON, `ausente` no `stats` (com o motivo), `-` no `runs`. Nunca vira zero. Para isso, o parser distingue três situações:

- **O componente não existe.** Sem nenhuma linha `system.l2cache.*` no bloco, a configuração não tem L2, e as métricas da L2 ficam ausentes. Um objeto configurado sempre imprime algumas linhas, como `tags.*`, `replacements` e `power_state.*`, mesmo sem nenhum acesso.
- **O gem5 omite zeros.** As estatísticas de cache e da memória `simple` usam as flags `nozero` e `nonan` do gem5, então valores 0 e NaN não são impressos. Com o componente presente, a linha que falta vale 0 nos contadores e 0 nas taxas de falta com acessos. Já taxas sem acessos e médias sem eventos, como `avg_miss_latency` sem faltas, ficam ausentes por serem 0/0. Esse caso é comum: na ROI dos tamanhos S, os dados já estão na L1d, e o `stats.txt` não tem a linha `system.cpu.dcache.overallMisses::total`, que vale 0.
- **A CPU atomic não modela tempo.** O gem5 imprime `numCycles` e `ipc` na atomic, mas `numCycles` é só `simTicks` dividido pelo período. Por isso, na atomic ficam ausentes ciclos, IPC, ticks, latências e banda; as contagens de instruções e de acessos continuam valendo. O modelo da CPU vem do `gem5/config.ini` (`type=` da seção `[system.cpu]`) ou, se ele faltar, do `experiment.resolved`.

Um `nan` impresso pelo gem5, como `avgMemAccLat` sem acessos à DRAM, também fica ausente. Já a falta de uma estatística da CPU (`numInsts`, `numCycles`...) é erro, porque indica que o nome mudou na versão do gem5.

### `riscvcnnbench stats`

```bash
uv run riscvcnnbench stats results/fc_s/<run_id>
uv run riscvcnnbench stats results/fc_s/<run_id> --json
make stats RUN=results/fc_s/<run_id>        # fora do container
```

Trecho de uma saída real (fc S, referência, CPU atomic com L1, L2 e DDR4):

```text
Execução:  results/fc_s/<run_id>
Benchmark: fc, CPU atomic, status completed
Região:    ROI, bloco 1 de 2

Centrais
  insts                       115270  instruções   system.cpu.commitStats0.numInsts
  ops                         115270  micro-ops    system.cpu.commitStats0.numOps
  cycles                     ausente  ciclos       system.cpu.numCycles (a CPU atomic não modela tempo)
...
Caches
  l1d_accesses                 32842  acessos      system.cpu.dcache.overallAccesses::total
  l1d_misses                       0  faltas       system.cpu.dcache.overallMisses::total
  l1d_miss_rate                    0  razão        system.cpu.dcache.overallMissRate::total
  l1d_avg_miss_latency       ausente  ticks        system.cpu.dcache.demandAvgMissLatency::total (a CPU atomic não modela tempo)
```

Depois das brutas, o `stats` mostra a linha `RESULT` do programa (`Resultado:`) e o grupo `Derivadas` (seção seguinte).

O JSON tem `run_id`, `path`, `status`, `experiment`, `benchmark`, `variant`, `cpu`, `region` (`roi` ou `program`), `blocks`, `metrics` (chave → valor ou `null`), `missing` (chave → motivo), `result` (campos da linha `RESULT`, ou `null`), `work_unit` (`MAC`, `elemento` ou `null`), `derived` e `derived_missing`. Numa execução que não terminou como `completed`, o `stats` mostra as métricas, mas avisa no stderr que elas não valem como resultado. Sem `stats.txt`, ou com um número inesperado de blocos, sai com 1 e explica o problema.

## Métricas derivadas e comparações

O código está em `src/riscvcnnbench/metric.py`. Ele parte das métricas brutas da ROI (seção anterior) e da linha `RESULT` que os benchmarks da base comum imprimem no `stdout.log`:

```text
RESULT bench=fc variant=custom data=random In=512 Out=32 R=1 checksum=0xae146a7bdb7dc885 mismatches=0
```

Da linha `RESULT` saem a operação (`bench`), a variante, o conjunto de dados (`data`), os parâmetros com os valores usados de fato (inclusive os padrões, quando o YAML não passa argumentos), o `checksum` e os `mismatches`. Vale a última linha `RESULT` do arquivo.

### Trabalho de cada operação

O trabalho de uma repetição (`work`) vem dos parâmetros da linha `RESULT`. Nas convoluções e na depthwise são os MACs **nominais**, com os 9 taps de cada saída, inclusive os que caem no padding. É a mesma conta de [scope.md](scope.md#dimensões) e de [kernels.md](kernels.md#instruções-medidas); os efetivos são 91,8% dos nominais em S e 95,9% em L, e as razões entre variantes não mudam. No pooling e na requantização, o trabalho é contado em elementos, e as unidades com "MAC" viram "elemento".

| Operação | `work` por repetição | Unidade |
| --- | --- | --- |
| `conv3x3_direct`, `conv3x3_im2col` | `H · W · 9 · Cin · Cout` | MAC |
| `depthwise3x3` | `H · W · 9 · C` | MAC |
| `pointwise1x1` | `H · W · Cin · Cout` | MAC |
| `fc` | `In · Out` | MAC |
| `int8_base_example` | `K · M` | MAC |
| `maxpool2x2` | `H · W · C` (elementos de entrada) | elemento |
| `requant_relu` | `N` | elemento |

### Por execução

| Chave | Fórmula | Unidade |
| --- | --- | --- |
| `repetitions` | `R` da linha `RESULT` | repetições |
| `work` | Tabela acima | MACs |
| `work_total` | `work · repetitions`, o trabalho da ROI inteira | MACs |
| `cpi` | `cycles / insts` | ciclos/instrução |
| `l1i_mpki`, `l1d_mpki`, `l2_mpki` | `1000 · <nível>_misses / insts` | faltas por mil instruções |
| `insts_per_rep`, `ops_per_rep`, `cycles_per_rep` | `insts`, `ops`, `cycles` divididos por `repetitions` | por repetição |
| `insts_per_work` | `insts / work_total` | instruções/MAC |
| `cycles_per_work` | `cycles / work_total` | ciclos/MAC |
| `work_per_cycle` | `work_total / cycles` | MACs/ciclo |

Uma derivada fica ausente quando falta um operando, com o mesmo motivo do operando. Por exemplo, na CPU atomic, `cpi` e `cycles_per_work` ficam ausentes com "a CPU atomic não modela tempo". Também fica ausente quando o denominador é zero (`indefinida: insts = 0`). Benchmarks sem a base comum (`hello_riscv_param`, `cnn_insn_semantics`) têm `cpi` e MPKI, mas não têm trabalho nem repetições.

### Comparações

Um par compara a execução `a` (a base) com `b`:

| Chave | Fórmula | Pergunta |
| --- | --- | --- |
| `r_i` | `insts_a / insts_b` | Quantas vezes menos instruções `b` executa? (redução de instruções, `R_I`) |
| `r_i_ops` | `ops_a / ops_b` | A mesma razão em micro-operações (difere na RVV) |
| `s_c` | `cycles_a / cycles_b` | Quantas vezes menos ciclos? (speedup em ciclos, `S_C`) |
| `ipc_ratio` | `s_c / r_i` = `IPC_b / IPC_a` | O IPC de `b` subiu ou caiu? |

Como `cycles = insts / IPC`, vale a identidade **`S_C = R_I × IPC_b / IPC_a`**. Ela responde diretamente quando menos instruções viram menos ciclos (objetivo específico 4): com `ipc_ratio` < 1, `b` perde parte da economia de instruções por latência ou espera pela memória, e o speedup fica abaixo da redução. Com `ipc_ratio` > 1, o speedup supera a redução. `ipc_ratio` é calculado com `insts` e `cycles`, e não com o `ipc` arredondado que o gem5 imprime, para a identidade valer exatamente. Na atomic, `r_i` vale (as instruções da ROI são as mesmas nas quatro CPUs), mas `s_c` e `ipc_ratio` ficam ausentes.

Há dois tipos de par:

| Tipo | Rótulo | `a` × `b` |
| --- | --- | --- |
| `variante` | `ref→custom`, `ref→rvv`, `custom→rvv` | Mesmo cenário, variantes diferentes. Com outro nível de otimização, o rótulo ganha o nível, como `ref→custom(-O3)`; com VLEN diferente de 256, a RVV aparece como `rvv@vlen512`; com `cpu.custom_latency` diferente de 3, a custom aparece como `custom@lat6` |
| `compilador` | `ref(-O2→-O3)` | Mesma variante e cenário; `a` com `-O2`, a base de todos os experimentos, e `b` com outro `-O*`. As outras flags, como `-DRCB_DATA`, têm de ser iguais |

**O que precisa ser igual num par.** A operação e os parâmetros (da linha `RESULT`, incluindo `R`), o conjunto de dados, as flags de compilação, a CPU (modelo e clock), as caches, a memória e o executável do gem5 (`gem5_sha256`). Ficam de fora o nome do experimento, a pasta de saída e o campo comparado. O estado das caches no início da ROI (`benchmark.cache_state`) também precisa ser igual. Campos que não afetam uma variante ficam de fora para ela: a VLEN, que não muda a ref nem a custom, e a latência das instruções personalizadas (`cpu.custom_latency`, RCB-18), que não muda a ref nem a rvv. Uma ref pareia, assim, com a RVV de qualquer VLEN e com a custom de qualquer latência, sem precisar ser repetida.

**Execuções que não entram.** Uma execução fica fora da comparação, com o motivo, quando não está `completed`, não tem `stats.txt` legível, não imprimiu a linha `RESULT` da base comum ou tem `mismatches` > 0. Execuções repetidas, com a mesma identidade, valem pela mais recente (`run_id`), e as outras são listadas como substituídas.

**Pares rejeitados.** Se `a` e `b` têm checksums diferentes, calcularam resultados diferentes, e o par é rejeitado sem valores: `checksums diferentes: 0x… (ref -O2) × 0x… (custom -O2)`.

### `riscvcnnbench compare`

```bash
uv run riscvcnnbench compare results                # todas as execuções sob results/
uv run riscvcnnbench compare results --json
make compare DIR=results/<campanha>                  # fora do container
```

Exemplo real (fc S, L1 de 32KiB e memória simple, 6 execuções: as três variantes na minor, a ref com `-O3` na minor e ref e custom na atomic; só ilustração, não é resultado da campanha):

```text
OPERAÇÃO  PARÂMETROS         CPU          CENÁRIO                     PAR           R_I     R_I_OPS  S_C     IPC_RATIO
fc        In=512,Out=32,R=1  atomic@1GHz  l1i=32KiB,l1d=32KiB,simple  ref→custom    9.118   9.118    -       -
fc        In=512,Out=32,R=1  minor@1GHz   l1i=32KiB,l1d=32KiB,simple  custom→rvv    1.676   1.117    0.986   0.588
fc        In=512,Out=32,R=1  minor@1GHz   l1i=32KiB,l1d=32KiB,simple  ref→custom    9.118   9.118    11.294  1.239
fc        In=512,Out=32,R=1  minor@1GHz   l1i=32KiB,l1d=32KiB,simple  ref→rvv       15.286  10.183   11.138  0.729
fc        In=512,Out=32,R=1  minor@1GHz   l1i=32KiB,l1d=32KiB,simple  ref(-O2→-O3)  1.000   1.000    0.998   0.998

5 par(es) aceito(s), 0 rejeitado(s). ...
```

A coluna `CENÁRIO` mostra o nome do cenário quando o YAML usa `scenario` (por exemplo `l1-l2`), ou os tamanhos das caches e o tipo de memória, como acima; com caches frias, acrescenta `,cold`. Depois da tabela vêm, se houver, os pares rejeitados, as execuções fora da comparação e as substituídas, cada uma com o caminho e o motivo. O JSON tem `pairs` (com `kind`, `label`, `a`, `b`, `scenario`, `values`, `missing` e `problem`), `excluded` e `superseded`. Para gravar as execuções e os pares em CSV, use `riscvcnnbench report` ([report.md](report.md)); para os gráficos, `riscvcnnbench plot` ([plots.md](plots.md)).

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

Em `simulation`, um `exit_code` diferente de zero pode ter duas causas: o **programa** retornou erro (`program_exit_code` preenchido; por exemplo, o benchmark detectou resultado incorreto ou rejeitou um argumento) ou o **gem5** falhou (`program_exit_code: null`, normalmente com `fatal:`/`panic:` no `stderr.log`).

Erros detectados antes de criar a pasta (YAML inválido, gem5 inexistente, toolchain ou `make` ausentes) não geram pasta; aparecem só no terminal.

### Diagnóstico

`riscvcnnbench run` (no fim da execução) e `riscvcnnbench runs` (na coluna STATUS) classificam cada falha lendo o `metadata.json` e os logs:

| Tipo | Quando | Mensagem aponta |
| --- | --- | --- |
| `build` | `failed_step: build` | Primeira linha com `error` do `build.log`. |
| `toolchain` | `failed_step: build` e o compilador não foi encontrado no `build.log` | Usar o container (`make run` / `make shell`). |
| `benchmark` | `failed_step: simulation` e `program_exit_code` ≠ 0 | Código do programa e a última linha do `stderr.log` que não é do gem5 (normalmente a mensagem do próprio programa). |
| `instruction` | `panic: Unknown/Illegal/Unimplemented instruction` no `stderr.log` | Conferir se o gem5 foi compilado do fork com as instruções personalizadas. |
| `gem5` | Outra falha na simulação | Primeira linha `fatal:`/`panic:` do `stderr.log`, ou o código do gem5. |
| `preparation` | `failed_step: preparation` | Campo `error`. |
| `interrupted` | `status: interrupted`, ou `failed` com a linha `Simulação interrompida` no `stdout.log` (o SIGINT chegou só ao gem5) | Etapa interrompida; rodar de novo. |
| `incomplete` | Status `preparing`, `building` ou `running` | Execução em andamento ou encerrada abruptamente. |

A classificação por texto dos logs é heurística: as mensagens do gem5 podem mudar entre versões. O `metadata.json` continua sendo a fonte de verdade.

### Códigos de saída do `riscvcnnbench run`

| Código | Significado |
| --- | --- |
| `0` | gem5 e programa retornaram `0`. |
| `1` | YAML inválido, gem5/toolchain ausentes (sem pasta) ou falha de preparação. |
| código do `make` | Build falhou. |
| código do programa | O benchmark retornou erro (o gem5 repassa o código do programa). |
| código do gem5 | O gem5 falhou; `128 + sinal` quando abortou (por exemplo, `134` em um `panic`). |

### Quando considerar uma execução válida

Confira em conjunto:

1. `status: completed`, `exit_code: 0` e `program_exit_code: 0` no `metadata.json`;
2. a linha `RESULT` esperada no `stdout.log`;
3. `code=0` na linha `Simulação encerrada` do `stdout.log`;
4. para resultados que serão comparados, `project.dirty: false` e `gem5_build.matches_executable: true`.

`stats.txt` existir, isoladamente, não prova que o programa terminou corretamente.

## Versões do formato (`schema_version`)

| Versão | Mudança |
| --- | --- |
| `5` | `branch` e `remote_url` em `project` e `gem5_repository` (o gem5 passou a ser um fork com código próprio). O build-info do gem5 passou à versão 2, com os mesmos campos em `repository`. |
| `4` | `program_exit_code` e `exit_cause`, lidos da linha `Simulação encerrada` do `stdout.log`. |
| `3` | `failed_step`, `experiment` (YAML original e configuração resolvida) e `build` (comando, código e log do build); estado `building`. Usado por `riscvcnnbench run`. |
| `2` | Proveniência: commits, diffs, hashes, versão e build-info do gem5, ambiente. |

Pastas antigas mantêm a versão com que foram criadas.

## Listar execuções

```bash
uv run riscvcnnbench runs                          # tudo em results/
uv run riscvcnnbench runs results/hello_param_cache
```

Fora do container, o equivalente é `make runs` ou `make runs DIR=results/hello_param_cache`.

Exemplo ilustrativo (a primeira linha é de uma execução real):

```text
RUN_ID                            EXPERIMENTO        BENCHMARK          CPU          STATUS              INSTS   CICLOS   IPC    PASTA
20261020T005249.889088Z-194128aa  hello_param_cache  hello_riscv_param  timing@2GHz  completed           822504  3730858  0.220  results/hello_param_cache/20261020T005249.889088Z-194128aa
20261020T010519.345612Z-f9ab65c2  demo               hello_riscv_param  atomic@1GHz  failed (benchmark)  -       -        -      results/demo/20261020T010519.345612Z-f9ab65c2
```

`INSTS`, `CICLOS` e `IPC` vêm da região de interesse, ou do programa inteiro nos benchmarks sem ROI (ver [Métricas](#métricas)). Ficam `-` em execuções não concluídas e, na CPU atomic, em `CICLOS` e `IPC`; ficam `?` se o `stats.txt` não pôde ser lido, e `riscvcnnbench stats <pasta>` mostra o motivo.

As execuções aparecem das mais antigas para as mais recentes. Execuções de `make hello-run-gem5` (sem YAML) aparecem com o nome da pasta como experimento e `-` na CPU. Para a mensagem completa de uma falha, veja o `metadata.json` e os logs da pasta, conforme a tabela de [Diagnóstico](#diagnóstico).

## Comandos úteis

```bash
RUN=results/hello_param_cache/<run_id>

python3 -m json.tool $RUN/metadata.json | less
python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["status"], m["failed_step"], m["exit_code"])' $RUN/metadata.json
cat $RUN/command.txt
grep -E '^(Sistema|RESULT|Simulação)' $RUN/stdout.log
grep -E 'fatal|panic' $RUN/stderr.log
grep -E '^(simInsts|simTicks|system.cpu.numCycles) ' $RUN/gem5/stats.txt
uv run riscvcnnbench stats $RUN            # métricas do bloco da ROI
uv run riscvcnnbench compare results       # pares de variantes e de compilador

# O que mudou entre duas execuções
diff $RUN_A/inputs/experiment.resolved.json $RUN_B/inputs/experiment.resolved.json
```
