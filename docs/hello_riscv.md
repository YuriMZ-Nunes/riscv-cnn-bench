# Executar o hello_riscv

O `hello_riscv` é um exemplo mínimo que soma os inteiros de 0 a 999 e verifica o resultado. O fluxo atual compila um executável RISC-V Linux e o executa com QEMU, não com gem5.

## Preparação

Siga o [guia de instalação do projeto](../README.md#guia-de-instalação-e-execução) até a construção da imagem com `make image`.

Para este exemplo, não é necessário inicializar os submódulos, executar `make sync` ou compilar o gem5. Execute os comandos abaixo na raiz do repositório, em um terminal interativo.

## Compilar e executar

Compile:

```bash
make hello-build
```

O alvo usa `riscv64-linux-gnu-gcc` para compilar `benchmarks/hello_riscv/main.c` e gerar:

```text
build/benchmarks/hello_riscv
```

Flags utilizadas:

```text
-O2 -static -march=rv64gc -mabi=lp64d -Wall -Wextra -Werror
```

Execute após a compilação:

```bash
make hello-run
```

Além do comando exibido pelo Make, a saída esperada é:

```text
RESULT sum=499500
exit_code=0
```

`hello-run` executa `qemu-riscv64 build/benchmarks/hello_riscv` e não compila o binário automaticamente. Sempre execute `hello-build` antes da primeira execução.

## Toolchain e emulador

O Makefile usa a imagem `localhost/riscv-cnn-bench:dev`. As versões de pacotes utilizadas nessa imagem foram:

| Pacote | Versão |
| --- | --- |
| `gcc-riscv64-linux-gnu` | `4:13.2.0-7ubuntu1` |
| `g++-riscv64-linux-gnu` | `4:13.2.0-7ubuntu1` |
| `binutils-riscv64-linux-gnu` | `2.42-4ubuntu2.10` |
| `libc6-dev-riscv64-cross` | `2.39-0ubuntu8cross1` |
| `qemu-user` | `1:8.2.2+ds-0ubuntu1.18` |

Essas versões foram consultadas na imagem existente. O Containerfile fornecido originalmente não as fixa; reconstruções podem instalar versões diferentes. A versão do pacote `gcc-riscv64-linux-gnu` não substitui a versão efetiva do compilador.

Para identificar as ferramentas da sua execução:

```bash
make toolchain-check

podman run --rm --pull=never localhost/riscv-cnn-bench:dev \
  bash -lc 'qemu-riscv64 --version'
```

## Problemas comuns

| Problema | Ação |
| --- | --- |
| Imagem não encontrada | Execute `make image`. |
| Binário não encontrado | Execute `make hello-build` antes de `make hello-run`. |
| Compilador ou QEMU não encontrado | Confira se a construção da imagem terminou sem erro e se está usando a imagem correta. |

Se precisar forçar uma recompilação, use:

```bash
podman run --rm --pull=never --userns=keep-id \
  -v "$PWD:/workspace:Z" -w /workspace \
  localhost/riscv-cnn-bench:dev \
  bash -lc 'make -C benchmarks/hello_riscv clean && make -C benchmarks/hello_riscv'
```
