# Toolchain RISC-V

Compilador usado pelos benchmarks. As versões fixadas e a conferência do ambiente estão em [container.md](container.md).

## Alvo

- Host: Linux x86-64
- Container: Ubuntu 24.04
- Alvo: RISC-V 64-bit Linux
- Triplet: `riscv64-linux-gnu`
- Compilador C: `riscv64-linux-gnu-gcc`
- Compilador C++: `riscv64-linux-gnu-g++`
- Modo gem5: Syscall Emulation (SE)
- ISA: `rv64gc`; a variante RVV dos kernels usa `rv64gcv` ([kernels.md](kernels.md))
- ABI: `lp64d`
- Ligação: estática

## Verificação de versão

```bash
riscv64-linux-gnu-gcc --version
riscv64-linux-gnu-g++ --version
riscv64-linux-gnu-ld --version
```

## Flags

```text
-O2 -static -march=rv64gc -mabi=lp64d -Wall -Wextra -Werror
```

`-O2` é o padrão de `compiler.flags` no YAML. Nas sete operações, `benchmarks/common/kernel.mk` põe o `-march` da variante depois das flags do experimento: `rv64gc` na referência e na personalizada (que usa `.insn` com `-DCNN_INSN_HW`), `rv64gcv` na RVV.

## Critério de validação

O binário `build/benchmarks/hello_riscv` deve:

1. Ser identificado por `file` como um ELF RISC-V de 64 bits.
2. Ter `Machine: RISC-V` em `readelf -h`.
3. Não possuir segmento `INTERP`.
4. Imprimir `RESULT sum=499500` ao ser executado em QEMU RISC-V ou gem5 SE.