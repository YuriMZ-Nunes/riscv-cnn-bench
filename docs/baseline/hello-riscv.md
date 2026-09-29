# Baseline: hello_riscv

Este guia documenta o baseline executável atual do projeto: a compilação cruzada e a execução do programa `hello_riscv` para RISC-V Linux usando QEMU em modo usuário.

> O baseline atual valida toolchain, container e execução de binário RISC-V. Ele ainda não executa o `hello_riscv` dentro do gem5.

## Objetivo

Confirmar que uma máquina limpa consegue:

1. Construir o ambiente de desenvolvimento do projeto.
2. Localizar a toolchain RISC-V Linux.
3. Compilar o benchmark `hello_riscv`.
4. Executar o binário RISC-V com `qemu-riscv64`.

## Pré-requisitos

- Git
- Podman
- GNU Make
- Espaço em disco para a imagem do contêiner e as fontes do gem5

Verifique a instalação local:

```bash
git --version
podman --version
make --version
```

## Clonar o projeto

Clone o repositório incluindo o submódulo do gem5:

```bash
git clone --recurse-submodules https://github.com/YuriMZ-Nunes/riscv-cnn-bench.git
cd riscv-cnn-bench
```

Se o repositório já estiver clonado, inicialize ou atualize os submódulos:

```bash
git submodule update --init --recursive
```

Confirme o estado do projeto e do submódulo:

```bash
make status
```

## Construir o ambiente

O projeto usa um contêiner baseado em Ubuntu 24.04. Ele inclui:

- GCC e G++ cruzados para RISC-V Linux
- Binutils RISC-V
- QEMU em modo usuário
- SCons
- Python e uv
- Dependências necessárias para construir o gem5

Construa a imagem:

```bash
make image
```

Por padrão, a imagem criada é:

```text
localhost/riscv-cnn-bench:dev
```

Para usar outro nome ou tag:

```bash
make image IMAGE=localhost/riscv-cnn-bench:local
```

## Verificar o ambiente

Execute a verificação geral do contêiner:

```bash
make check
```

A saída deve mostrar a arquitetura do contêiner e as versões de Python, uv, SCons e Git.

Depois, valide a toolchain RISC-V:

```bash
make toolchain-check
```

A saída deve incluir caminhos e versões para:

```text
riscv64-linux-gnu-gcc
riscv64-linux-gnu-g++
riscv64-linux-gnu-objdump
```

## Compilar o benchmark

Compile o programa `hello_riscv`:

```bash
make hello-build
```

O comando executa o Makefile localizado em `benchmarks/hello_riscv`. O artefato esperado é:

```text
build/benchmarks/hello_riscv
```

Opcionalmente, confirme que o binário é um executável RISC-V:

```bash
file build/benchmarks/hello_riscv
```

A saída deve identificar um executável ELF para RISC-V.

## Executar com QEMU

Execute o benchmark:

```bash
make hello-run
```

Internamente, o projeto executa:

```bash
qemu-riscv64 build/benchmarks/hello_riscv
```

## Resultado esperado

A saída esperada é:

```text
RESULT sum=499500
```

A execução deve encerrar com código de saída `0`. O programa soma os inteiros de `0` a `999` e valida internamente se o resultado é `499500`. Caso a verificação falhe, ele retorna código `1`.

## Limite do baseline atual

Este baseline comprova que:

- O contêiner funciona
- A toolchain cruzada está disponível
- Um programa RISC-V pode ser compilado
- O QEMU consegue executar o binário gerado

Ele ainda não comprova execução no gem5 nem produz métricas de microarquitetura, como ciclos, IPC ou misses de cache.

## Preparação para gem5

O gem5 pode ser compilado com:

```bash
make gem5-build
```

O binário gerado é:

```text
third_party/gem5/build/RISCV/gem5.opt
```

A integração para executar benchmarks com gem5 será documentada quando o runner e os cenários base estiverem disponíveis.

## Problemas comuns

| Sintoma | Causa provável | Ação recomendada |
| --- | --- | --- |
| `podman: command not found` | Podman não está instalado | Instale Podman e valide com `podman --version` |
| Erro ao criar imagem | Falta de espaço, rede ou permissão do runtime | Rode `podman info`, confira o armazenamento e tente novamente |
| Toolchain não encontrada | A imagem não foi construída corretamente | Execute `make image` novamente e rode `make toolchain-check` |
| `build/benchmarks/hello_riscv` não existe | A compilação ainda não ocorreu ou falhou | Rode `make hello-build` e leia a saída de erro |
| QEMU não executa o binário | Binário incompatível ou erro de build | Rode `file build/benchmarks/hello_riscv` e refaça o build |
| Submódulo gem5 vazio | Submódulos não foram inicializados | Rode `git submodule update --init --recursive` |
