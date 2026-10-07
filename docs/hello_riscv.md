# Executar o hello_riscv

O `hello_riscv` soma os inteiros de 0 a 999 e verifica se o resultado é `499500`. O exemplo pode ser executado com QEMU ou com gem5 em modo Syscall Emulation (SE).

## Preparação

Siga o [guia de instalação](../README.md#guia-de-instalação-e-execução) até construir a imagem com `make image`. Execute os comandos abaixo na raiz do repositório, em um terminal interativo.

Não é necessário executar `make sync` para este exemplo. Para o caminho com gem5, inicialize os submódulos e compile o simulador conforme o README.

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

## Executar com gem5

Com o simulador compilado:

```bash
make hello-run-gem5
printf 'exit_code=%s\n' "$?"
```

O alvo compila o benchmark e executa `third_party/gem5/build/RISCV/gem5.opt` com a configuração `configs/gem5/se_riscv.py`. Ele não compila o simulador automaticamente.

A saída deve incluir:

```text
RESULT sum=499500
```

O script também informa o tick final, a causa de encerramento e o código do evento. A execução bem-sucedida encerra normalmente o programa com código zero e termina com `exit_code=0`. As mensagens do gem5 e a quantidade de ticks podem variar conforme sua revisão.

Os arquivos da simulação são gravados em `results/hello_riscv/`, incluindo as estatísticas em `stats.txt` e a configuração em `config.ini`.

A configuração usa uma CPU `AtomicSimpleCPU` a 1 GHz, 512 MiB de memória simples e nenhuma cache. O modo SE executa o programa sem inicializar um sistema operacional completo. Esse fluxo é um teste funcional, não uma avaliação detalhada de desempenho de microarquitetura.

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

Registre essas saídas junto com os resultados; nenhum hash específico do gem5 é estabelecido neste guia.

## Verificação e problemas

Execute cada `printf` imediatamente após o comando anterior: ele mostra o código de saída do Make. O critério de sucesso é obter `RESULT sum=499500` e `exit_code=0`. O programa retorna `1` se a soma estiver incorreta; o Make pode reportar outro código não zero quando uma receita falha.

| Problema | Ação |
| --- | --- |
| Imagem não encontrada | Execute `make image`. |
| Benchmark não encontrado no QEMU | Execute `make hello-build`. |
| `gem5.opt` não encontrado | Execute `make gem5-build` e verifique se terminou sem erro. |
| Erro de execução no gem5 | Confira a revisão usada e preserve o log completo para diagnóstico. |

Uma execução bem-sucedida no QEMU não substitui a validação no gem5.
