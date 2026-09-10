# Toolchain RISC-V

## Alvo inicial

- Host: Linux x86-64
- Container: Ubuntu 24.04
- Alvo: RISC-V 64-bit Linux
- Triplet: `riscv64-linux-gnu`
- Compilador C: `riscv64-linux-gnu-gcc`
- Compilador C++: `riscv64-linux-gnu-g++`
- Modo gem5: Syscall Emulation (SE)
- ISA inicial: `rv64gc`
- ABI inicial: `lp64d`
- Ligação: estática

## Verificação de versão

```bash
riscv64-linux-gnu-gcc --version
riscv64-linux-gnu-g++ --version
riscv64-linux-gnu-ld --version
```

## Flags iniciais

```text
-O2 -static -march=rv64gc -mabi=lp64d -Wall -Wextra -Werror
```

## Critério de validação

O binário `build/benchmarks/hello_riscv` deve:

1. Ser identificado por `file` como um ELF RISC-V de 64 bits.
2. Ter `Machine: RISC-V` em `readelf -h`.
3. Não possuir segmento `INTERP`.
4. Imprimir `RESULT sum=499500` ao ser executado em QEMU RISC-V ou gem5 SE.