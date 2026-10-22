# Instruções personalizadas

Referência técnica das instruções RISC-V personalizadas do framework: codificação, semântica, uso em C, testes e implementação no gem5. As operações, a quantização e as dimensões que motivam o conjunto estão em [scope.md](scope.md).

| Parte | Situação |
| --- | --- |
| Especificação (este documento) | Existente |
| Header [benchmarks/common/cnn_insn.h](../benchmarks/common/cnn_insn.h): macros `.insn` e modelo em C | Existente |
| Benchmark [cnn_insn_semantics](../benchmarks/cnn_insn_semantics/main.c) com os casos de teste | Existente; o modo modelo roda no QEMU e em qualquer gem5, o modo `hw` no gem5 do fork |
| Instruções no decodificador do gem5 (fork `YuriMZ-Nunes/gem5`, branch `riscv-cnn-bench`) | Existente (RCB-13), nas CPUs atomic, timing, minor e o3. Ver [Implementação no gem5](#implementação-no-gem5) |
| Latência própria e configurável das instruções | Planejado. Hoje usam as unidades `IntMult` e `IntAlu` de cada CPU |
| Kernels que usam as instruções (`kernel_custom.c` das sete operações) | Existente (RCB-14), ver [kernels.md](kernels.md#instruções-personalizadas-kernel_customc) |

## Resumo

| Instrução | Faz | Operações | Classe no gem5 |
| --- | --- | --- | --- |
| `cnn.dot8 rd, rs1, rs2` | Produto escalar de 8 pares int8, acumulado no int32 de `rd` | Conv 3×3 direta, im2col+GEMM, pointwise, FC | `IntMult` |
| `cnn.dwmac rd, rs1, rs2, p` | 2 MACs int8 faixa a faixa em 2 acumuladores int32 de `rd`; `p` escolhe o par de bytes | Depthwise 3×3 | `IntMult` |
| `cnn.max8 rd, rs1, rs2` | Máximo com sinal de 8 int8, byte a byte | Max pooling 2×2 | `IntAlu` |
| `cnn.rqnt rd, rs1, rs2` | Requantização int32 → int8 com saturação | Requantização e fim das convoluções e da FC | `IntMult` |
| `cnn.rqnt.relu rd, rs1, rs2` | Idem, com ReLU | Idem | `IntMult` |

Regras comuns:

- **Só registradores.** Nenhuma instrução acessa a memória. As cargas e os stores continuam sendo `ld`, `lw`, `sb` e `sd` padrão, e a referência e a variante personalizada fazem os mesmos acessos.
- **Operandos empacotados.** Um registrador de 64 bits guarda 8 int8 com o byte 0 nos bits 7:0. É o que um `ld` de 8 bytes contíguos produz.
- **Sem traps.** Bits não usados são ignorados, e cada instrução é uma função total dos operandos.
- **O prefixo `cnn.` é só o nome no projeto.** O montador não conhece esses mnemônicos, e o código usa `.insn`.

## Codificação

Todas usam o formato R:

```
 31        25 24    20 19    15 14  12 11     7 6        0
+------------+--------+--------+------+--------+----------+
|   funct7   |  rs2   |  rs1   |funct3|   rd   |  opcode  |
+------------+--------+--------+------+--------+----------+
```

| Instrução | opcode | funct3 | funct7 | Lê `rd` | Diretiva |
| --- | --- | --- | --- | --- | --- |
| `cnn.dot8` | `0x0B` (custom-0) | `0` | `0x00` | sim | `.insn r CUSTOM_0, 0, 0x00, rd, rs1, rs2` |
| `cnn.max8` | `0x0B` (custom-0) | `1` | `0x00` | não | `.insn r CUSTOM_0, 1, 0x00, rd, rs1, rs2` |
| `cnn.dwmac p` | `0x0B` (custom-0) | `p` (0 a 3) | `0x01` | sim | `.insn r CUSTOM_0, p, 0x01, rd, rs1, rs2` |
| `cnn.rqnt` | `0x2B` (custom-1) | `0` | `0x00` | não | `.insn r CUSTOM_1, 0, 0x00, rd, rs1, rs2` |
| `cnn.rqnt.relu` | `0x2B` (custom-1) | `0` | `0x01` | não | `.insn r CUSTOM_1, 0, 0x01, rd, rs1, rs2` |

As demais combinações de `funct3` e `funct7` em custom-0 e custom-1 ficam reservadas, e o gem5 as trata como instrução desconhecida. As instruções só existem em RV64: com `riscv_type = RV32`, custom-0 e custom-1 continuam desconhecidas.

| Opcode | Espaço | Uso |
| --- | --- | --- |
| `0x0B` | custom-0 | Instruções de multiplicação e comparação |
| `0x2B` | custom-1 | Requantização |
| `0x5B` | custom-2 | Não usar: reservado ao RV128 pela especificação |
| `0x7B` | custom-3 | Não usar: m5ops do gem5 (`util/m5/src/abi/riscv/m5op.S`), usadas para marcar a região de interesse |

O teste e2e confere que um binário compilado com `-DCNN_INSN_HW` contém exatamente estas 8 codificações, e que 6 combinações reservadas continuam gerando `Unknown instruction` no gem5. O `objdump` com `rv64gc` mostra todas como `.insn`, ou seja, não as confunde com instruções padrão. Extensões de fabricante que também usam custom-0, como as da T-Head, só existem com `-march=..._xthead*`.

## Semântica

Notação:

- `R[a:b]` são os bits de `a` a `b` de `R`;
- `sext8` e `sext32` estendem o sinal;
- as faixas de byte são `x_i = sext8(rs1[8i+7:8i])` e `w_i = sext8(rs2[8i+7:8i])`.

Nas tabelas de casos, os valores são registradores de 64 bits, com o byte 0 à direita. Nas instruções que não leem `rd`, a coluna mostra "—". As tabelas são conferidas contra a tabela `CASES` do benchmark por [tests/test_custom_insn.py](../tests/test_custom_insn.py) (ver [Como alterar uma instrução](#como-alterar-uma-instrução)).

### `cnn.dot8 rd, rs1, rs2`

```
soma ← rd[31:0]
para i de 0 a 7:
    soma ← (soma + x_i · w_i) mod 2^32
rd ← sext32(soma)
```

- **Bits altos ignorados:** os bits 63:32 de `rd` na entrada não entram na conta.
- **Resultado na convenção da ABI:** a extensão de sinal é a mesma do `addw`, então o resultado já é um `int32_t` válido no RV64.
- **Limites:** cada instrução soma no máximo `8 · 2^14 = 2^17` em módulo. No escopo, o maior acumulador é `2^24` mais o bias, na FC L. O wrap módulo `2^32` é definido, mas não deve acontecer.

| Caso | Instrução | rd | rs1 | rs2 | rd esperado | O que testa |
| --- | --- | --- | --- | --- | --- | --- |
| dot8-01 | cnn.dot8 | `0x0000000000000000` | `0x0000000000000000` | `0x0000000000000000` | `0x0000000000000000` | zeros |
| dot8-02 | cnn.dot8 | `0x0000000000000000` | `0x0807060504030201` | `0x0101010101010101` | `0x0000000000000024` | soma simples: 1+2+...+8 = 36 |
| dot8-03 | cnn.dot8 | `0x0000000000000000` | `0x0101010101010101` | `0xffffffffffffffff` | `0xfffffffffffffff8` | resultado negativo estendido para 64 bits |
| dot8-04 | cnn.dot8 | `0x0000000000000000` | `0x8080808080808080` | `0x8080808080808080` | `0x0000000000020000` | pior caso positivo: 8 x (-128 x -128) |
| dot8-05 | cnn.dot8 | `0x0000000000000000` | `0x8080808080808080` | `0x7f7f7f7f7f7f7f7f` | `0xfffffffffffe0400` | pior caso negativo: 8 x (-128 x 127) |
| dot8-06 | cnn.dot8 | `0x00000000000003e8` | `0x0807060504030201` | `0x0102030405060708` | `0x0000000000000460` | acumula sobre rd = 1000 |
| dot8-07 | cnn.dot8 | `0x000000007ffffff0` | `0x7f7f7f7f7f7f7f7f` | `0x7f7f7f7f7f7f7f7f` | `0xffffffff8001f7f8` | acumulador passa de 2^31-1: volta módulo 2^32 |
| dot8-08 | cnn.dot8 | `0xdeadbeef00000010` | `0x0807060504030201` | `0x0101010101010101` | `0x0000000000000034` | bits 63:32 de rd são ignorados |
| dot8-09 | cnn.dot8 | `0x0000000000000000` | `0xfc04fd03fe02ff01` | `0xf5f50909f9f90505` | `0x0000000000000000` | termos de sinais opostos se cancelam |

### `cnn.dwmac rd, rs1, rs2, p`

```
para j em {0, 1}:
    k ← 2p + j
    rd[32j+31:32j] ← (rd[32j+31:32j] + x_k · w_k) mod 2^32
```

- **Faixas independentes:** as duas faixas não trocam carry.
- **Constante `p`:** fica no `funct3`, por isso precisa ser uma constante de compilação.
- **Uso:** para 8 canais `c..c+7` de um tap, cada `p` atualiza os canais `c+2p` e `c+2p+1`. O bias int32 de dois canais consecutivos entra com um `ld`, já no formato de `rd`.
- **Limites:** com 9 taps, cada faixa acumula no máximo `9 · 2^14 < 2^18` mais o bias.

| Caso | Instrução | rd | rs1 | rs2 | rd esperado | O que testa |
| --- | --- | --- | --- | --- | --- | --- |
| dwmac-01 | cnn.dwmac p=0 | `0x0000000000000000` | `0x0000000000008080` | `0x0000000000007f80` | `0xffffc08000004000` | p=0, extremos: -128 x -128 e -128 x 127 |
| dwmac-02 | cnn.dwmac p=0 | `0x0000000000000000` | `0x0807060504030201` | `0x0202020202020202` | `0x0000000400000002` | p=0 usa os bytes 0 e 1 |
| dwmac-03 | cnn.dwmac p=1 | `0x0000000000000000` | `0x0807060504030201` | `0x0202020202020202` | `0x0000000800000006` | p=1 usa os bytes 2 e 3 |
| dwmac-04 | cnn.dwmac p=2 | `0x0000000000000000` | `0x0807060504030201` | `0x0202020202020202` | `0x0000000c0000000a` | p=2 usa os bytes 4 e 5 |
| dwmac-05 | cnn.dwmac p=3 | `0x0000000000000000` | `0x0807060504030201` | `0x0202020202020202` | `0x000000100000000e` | p=3 usa os bytes 6 e 7 |
| dwmac-06 | cnn.dwmac p=1 | `0x000002bcfffffe0c` | `0xf807fa05fc037f80` | `0x0101010103fd0101` | `0x000002b0fffffe03` | acumula sobre as duas faixas de rd |
| dwmac-07 | cnn.dwmac p=0 | `0x00000005ffffffff` | `0x0101010101010101` | `0x0101010101010101` | `0x0000000600000000` | faixa 0 passa de -1 para 0 sem carry na faixa 1 |
| dwmac-08 | cnn.dwmac p=3 | `0x800000007fffffff` | `0x0101000000000000` | `0xff01000000000000` | `0x7fffffff80000000` | cada faixa volta módulo 2^32 sozinha |

### `cnn.max8 rd, rs1, rs2`

```
para i de 0 a 7:
    rd[8i+7:8i] ← max(x_i, w_i)
```

A comparação é com sinal: `0x80` (−128) perde para `0x7F` (127). Com `rs2 = 0`, a instrução faz ReLU em int8.

| Caso | Instrução | rd | rs1 | rs2 | rd esperado | O que testa |
| --- | --- | --- | --- | --- | --- | --- |
| max8-01 | cnn.max8 | — | `0x9c64fb05ff007f80` | `0x9c64fb05ff007f80` | `0x9c64fb05ff007f80` | operandos iguais |
| max8-02 | cnn.max8 | — | `0x9c64fb05ff007f80` | `0x649c05fb00ff807f` | `0x6464050500007f7f` | maior por faixa, sinais misturados |
| max8-03 | cnn.max8 | — | `0x8080808080808080` | `0x8080808080808080` | `0x8080808080808080` | extremo negativo nas duas entradas |
| max8-04 | cnn.max8 | — | `0x9c64fb05ff007f80` | `0x0000000000000000` | `0x0064000500007f00` | max com zero equivale a ReLU em int8 |
| max8-05 | cnn.max8 | — | `0x8080808080808080` | `0x7f7f7f7f7f7f7f7f` | `0x7f7f7f7f7f7f7f7f` | comparação com sinal: 0x80 < 0x7F |
| max8-06 | cnn.max8 | — | `0x09f807fa05fc03fe` | `0x0af908fb06fd02ff` | `0x0af908fb06fd03ff` | cada faixa escolhe o seu operando |

### `cnn.rqnt rd, rs1, rs2` e `cnn.rqnt.relu rd, rs1, rs2`

Implementam a requantização de [scope.md](scope.md#quantização). `rs2` empacota os parâmetros, montados com `cnn_rqnt_params(M0, s)`:

| Bits de `rs2` | Campo |
| --- | --- |
| 31:0 | `M0`, int32 em `[2^30, 2^31)` |
| 36:32 | `s`, de 0 a 31 |
| 63:37 | Reservado: deve ser zero, e a instrução ignora |

```
a  ← sext32(rs1[31:0])
M0 ← sext32(rs2[31:0])
s  ← rs2[36:32]
y  ← (a · M0 + 2^(30+s)) >> (31+s)        (int64, deslocamento aritmético)
lo ← 0 em cnn.rqnt.relu, −128 em cnn.rqnt
rd ← sext8(min(max(y, lo), 127))
```

- **Sem overflow em int64:** `|a · M0| ≤ 2^62` e `2^(30+s) ≤ 2^61`.
- **Arredondamento:** empates vão para +∞. `50,5` vira `51`, e `-50,5` vira `-50`. Os kernels de referência devem usar exatamente esta fórmula para a equivalência byte a byte.
- **Escalas representáveis:** `M = M0 · 2^-(31+s)` fica em `[2^-32, 1)`. Escalas `M ≥ 1` não são representáveis.
- **`M0` fora da faixa:** o resultado continua definido pela fórmula, sem trap.

| Caso | Instrução | rd | rs1 | rs2 | rd esperado | O que testa |
| --- | --- | --- | --- | --- | --- | --- |
| rqnt-01 | cnn.rqnt | — | `0x0000000000000064` | `0x0000000040000000` | `0x0000000000000032` | escala 0,5: 100 -> 50 |
| rqnt-02 | cnn.rqnt | — | `0x0000000000000065` | `0x0000000040000000` | `0x0000000000000033` | 50,5 arredonda para cima: 51 |
| rqnt-03 | cnn.rqnt | — | `0xffffffffffffff9b` | `0x0000000040000000` | `0xffffffffffffffce` | -50,5 arredonda para cima: -50 |
| rqnt-04 | cnn.rqnt | — | `0x00000000000003e8` | `0x0000000040000000` | `0x000000000000007f` | satura em 127 |
| rqnt-05 | cnn.rqnt | — | `0xfffffffffffffc18` | `0x0000000040000000` | `0xffffffffffffff80` | satura em -128 |
| rqnt-06 | cnn.rqnt | — | `0x00000000000007d0` | `0x0000000460000000` | `0x000000000000005e` | escala 0,75 x 2^-4: 2000 -> 93,75 -> 94 |
| rqnt-07 | cnn.rqnt | — | `0xffffffff80000000` | `0x000000007fffffff` | `0xffffffffffffff80` | acc = -2^31 e M0 máximo: satura em -128 |
| rqnt-08 | cnn.rqnt | — | `0x000000007fffffff` | `0x0000001f7fffffff` | `0x0000000000000001` | s = 31: deslocamento de 62 bits sem overflow |
| rqnt-09 | cnn.rqnt | — | `0x1234567800000064` | `0x0000000040000000` | `0x0000000000000032` | bits 63:32 de rs1 são ignorados |
| rqnt-10 | cnn.rqnt | — | `0x0000000000000064` | `0xffffffe040000000` | `0x0000000000000032` | bits 63:37 de rs2 são ignorados |
| rqnt-11 | cnn.rqnt | — | `0x0000000000000000` | `0x0000000540000000` | `0x0000000000000000` | zero continua zero |
| rqnt.relu-01 | cnn.rqnt.relu | — | `0x0000000000000064` | `0x0000000040000000` | `0x0000000000000032` | positivo passa: 50 |
| rqnt.relu-02 | cnn.rqnt.relu | — | `0xffffffffffffff9c` | `0x0000000040000000` | `0x0000000000000000` | negativo vira 0 |
| rqnt.relu-03 | cnn.rqnt.relu | — | `0x00000000000003e8` | `0x0000000040000000` | `0x000000000000007f` | satura em 127 |
| rqnt.relu-04 | cnn.rqnt.relu | — | `0xffffffffffffffff` | `0x0000000040000000` | `0x0000000000000000` | -0,5 arredonda para 0 |
| rqnt.relu-05 | cnn.rqnt.relu | — | `0x0000000000000003` | `0x0000000040000000` | `0x0000000000000002` | 1,5 arredonda para 2 |

## Uso em C

Inclua o header a partir do benchmark:

```c
#include "../common/cnn_insn.h"
```

| Função ou macro | Sem `CNN_INSN_HW` | Com `CNN_INSN_HW` |
| --- | --- | --- |
| `int64_t cnn_dot8(int64_t acc, uint64_t x, uint64_t w)` | modelo em C | `cnn.dot8` |
| `CNN_DWMAC(acc, x, w, p)` (atualiza `acc`, um `uint64_t`; `p` literal de 0 a 3) | modelo em C | `cnn.dwmac p` |
| `uint64_t cnn_max8(uint64_t a, uint64_t b)` | modelo em C | `cnn.max8` |
| `int64_t cnn_rqnt(int64_t acc, uint64_t prm)` e `cnn_rqnt_relu` | modelo em C | `cnn.rqnt` e `cnn.rqnt.relu` |
| `cnn_dot8_model`, `cnn_dwmac_model`, `cnn_max8_model`, `cnn_rqnt_model` | sempre o modelo em C | idem |
| `uint64_t cnn_rqnt_params(int32_t m0, unsigned s)` | empacota `rs2` | idem |
| `uint64_t cnn_ld8(const void *p)`, `void cnn_sd8(void *p, uint64_t v)` | 8 bytes alinhados com um `ld`/`sd` (`memcpy` + `__builtin_assume_aligned`) | idem |

O modelo em C é a definição executável da semântica e o oráculo da equivalência (RCB-15). Ele assume deslocamento aritmético à direita de inteiros negativos, como o GCC faz.

Requisitos dos kernels:

- **Alinhamento.** Tensores alinhados a 8 bytes, para que cada `ld` leia 8 int8 de uma vez.
- **Dimensões.** A dimensão contígua deve ser múltipla de 8. Todas as formas de [scope.md](scope.md) já atendem: `Cin`, canais, `K` do im2col e `In` da FC.
- **Acumuladores `int64_t`.** `cnn_dot8` e `cnn_rqnt*` usam a largura do registrador. As instruções leem só os bits 31:0 e devolvem o resultado estendido com sinal, então o valor pode ir direto de `cnn_dot8` para `cnn_rqnt`, e um `int32_t` (o bias, por exemplo) entra por conversão implícita. Até a RCB-13 a interface usava `int32_t`. Na RCB-14 isso se mostrou caro: o GCC não sabe que a instrução devolve o valor estendido e colocava um `sext.w` depois de cada `cnn.dot8` no laço interno, ou seja, uma instrução a mais por 8 MACs que não pertence à variante. A semântica não mudou. O benchmark `cnn_insn_semantics` usa `asm` direto no modo hw e não foi afetado.

## Compilar e executar

O modo vem das flags do experimento, que o runner passa como `FLAGS` ao Makefile do benchmark:

```yaml
compiler:
  flags: [-O2, -DCNN_INSN_HW]   # sem -DCNN_INSN_HW, usa o modelo em C
```

| Modo | QEMU | gem5 oficial (sem as instruções) | gem5 do fork (`third_party/gem5`) |
| --- | --- | --- | --- |
| Modelo (padrão) | roda | roda | roda |
| `-DCNN_INSN_HW` | `Illegal instruction` | `panic: Unknown instruction`, que a CLI classifica como `instruction` | roda |

Benchmark de semântica:

```bash
# Dentro do container
uv run riscvcnnbench run experiments/cnn_insn_semantics.yaml
make -C benchmarks/cnn_insn_semantics          # modelo; FLAGS="-O2 -DCNN_INSN_HW" para o modo hw
qemu-riscv64 build/benchmarks/cnn_insn_semantics
```

A saída é `RESULT mode=<model|hw> cases=39 failures=0`, com código de saída 0. Com uma falha, o benchmark imprime o caso no stderr e sai com 1. No modo `hw`, cada caso é conferido duas vezes: pelo modelo e pela instrução real.

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_custom_insn.py` | As tabelas deste documento e a tabela `CASES` do benchmark são iguais; cada valor esperado é recalculado por um modelo em Python independente do modelo em C | `pytest` |
| `tests/test_custom_insn_e2e.py::test_model_runs_on_qemu` | Modelo em C passa nos 39 casos no QEMU | `pytest -m e2e` |
| `tests/test_custom_insn_e2e.py::test_model_runs_on_gem5_from_yaml` | Idem no gem5, pelo fluxo `riscvcnnbench run` | `pytest -m e2e` |
| `cnn_insn_semantics` nos casos de requantização | O oráculo `rcb_requantize` da base comum ([kernel_base.md](kernel_base.md)) coincide com o modelo do `cnn.rqnt` | `pytest -m e2e`, pelos testes acima |
| `tests/test_custom_insn_e2e.py::test_hw_build_uses_only_the_specified_encodings` | O binário com `-DCNN_INSN_HW` tem exatamente as 8 codificações; sem a flag, nenhuma | `pytest -m e2e` |
| `tests/test_custom_insn_e2e.py::test_hw_runs_on_gem5[atomic\|timing\|minor\|o3]` | Instruções reais no gem5 do fork: `RESULT mode=hw cases=39 failures=0` em cada CPU, pelo fluxo `riscvcnnbench run` | `pytest -m e2e` |
| `tests/test_custom_insn_e2e.py::test_wrong_instruction_semantics_is_detected` | Teste negativo (RCB-15): com `-DCNN_INSN_INJECT_ERROR`, o modo hw executa `cnn.dwmac p=0` no lugar do `cnn.dot8`; no gem5, exatamente os casos `dot8-*` em que as duas diferem (8 de 9, calculados pelo modelo em Python) falham, e o benchmark sai com 1 | `pytest -m e2e` |
| `tests/test_custom_insn_e2e.py::test_reserved_encodings_are_unknown` | 6 combinações reservadas de custom-0/1 terminam com `panic: Unknown instruction` com a palavra esperada, diagnosticado como `instruction` | `pytest -m e2e` |

## Implementação no gem5

As instruções estão no fork [YuriMZ-Nunes/gem5](https://github.com/YuriMZ-Nunes/gem5), branch `riscv-cnn-bench`, que é o submódulo `third_party/gem5` (RCB-13). É a única mudança do fork em relação ao gem5 oficial, e fica restrita a `src/arch/riscv/`:

| Arquivo do fork | Conteúdo |
| --- | --- |
| `src/arch/riscv/insts/cnn.hh` | Semântica: `cnn::dot8`, `cnn::dwmac`, `cnn::max8` e `cnn::rqnt`, cópias do modelo em C de `cnn_insn.h`; classe base `CnnOp` |
| `src/arch/riscv/insts/cnn.cc` | Disassembly de `CnnOp` (ver abaixo) |
| `src/arch/riscv/isa/formats/cnn.isa` | Formato `CnnOp` do parser do ISA |
| `src/arch/riscv/isa/decoder.isa` | Casos `0x02` (custom-0) e `0x0a` (custom-1) no `decode OPCODE5`, dentro de `decode RVTYPE` (só RV64) |
| `src/arch/riscv/insts/SConscript`, `isa/includes.isa`, `isa/formats/formats.isa` | Registro dos arquivos novos |

- **Decodificação.** Segue a tabela de codificação. As combinações reservadas e qualquer uso em RV32 caem no `Unknown instruction` padrão do decodificador.
- **Fontes e destino.** `cnn.dot8` e `cnn.dwmac` leem `Rd` além de `Rs1` e `Rs2`. O parser do ISA marca `Rd` como fonte e destino porque ele aparece dos dois lados da atribuição. Isso cria a dependência pelo acumulador nas CPUs minor e o3.
- **Classe de operação.** `IntMultOp` para `cnn.dot8`, `cnn.dwmac` e `cnn.rqnt*`, como no `mul`. `cnn.max8` usa a classe padrão, `IntAluOp`. As instruções contam em `commitStats0.committedInstType::IntMult` e `::IntAlu`.
- **Contagem.** Cada instrução é uma só, sem micro-operações, e conta 1 em `numInsts` e `numOps`.
- **Nomes no gem5.** No trace (`--debug-flags=Exec`), os mnemônicos usam `_` no lugar do ponto: `cnn_dot8 a6, a1, a2`, `cnn_dwmac a6, a1, a2, 3`, `cnn_max8`, `cnn_rqnt` e `cnn_rqnt_relu`. No `cnn.dwmac`, o último campo é `p`.

### Latência por CPU

A latência é a da classe de operação no pool de unidades funcionais de cada CPU. Valores padrão do gem5 do projeto, lidos em `src/cpu/minor/BaseMinorCPU.py` e `src/cpu/o3/FuncUnitConfig.py`:

| Classe | MinorCPU | O3CPU |
| --- | --- | --- |
| `IntAlu` | 3 ciclos, 2 unidades. A latência efetiva para um dependente é ~1 ciclo, porque `srcRegsRelativeLats=[2]` | 1 ciclo, 6 unidades |
| `IntMult` | 3 ciclos, 1 unidade com pipeline | 3 ciclos, 2 unidades com pipeline |
| `Simd*`, usadas pelo RVV | 6 ciclos, 1 unidade compartilhada com ponto flutuante | 1 ciclo, 4 unidades |

As CPUs atomic e timing ignoram a classe de operação: em `src/cpu/simple/base.cc`, ela só alimenta a estatística `issuedInstType`.

Confirmação medida em 21/10/2026, com um microbenchmark temporário que não faz parte do repositório:
- 2000 iterações de 8 instruções iguais, ou seja, 16000 instruções medidas e ~20 mil no total da ROI;
- compilado com `-march=rv64g`, sem instruções comprimidas, para que nenhuma instrução de 4 bytes fique desalinhada;
- L1I e L1D de 32KiB, 1GHz.

"Dependente" usa o resultado anterior como fonte. "Independente" usa 8 acumuladores. A tabela mostra `numCycles` da ROI:

| Cadeia | atomic | timing | minor | o3 |
| --- | --- | --- | --- | --- |
| `add` dependente | 20.080 | 40.616 | 18.536 | 16.317 |
| `mul` dependente | 20.132 | 40.816 | 48.697 | 48.433 |
| `cnn.dot8` dependente | 20.167 | 41.078 | 49.060 | 48.723 |
| `cnn.dwmac` dependente | 20.208 | 41.130 | 49.092 | 48.698 |
| `cnn.max8` dependente | 20.281 | 41.414 | 21.352 | 16.793 |
| `cnn.rqnt` dependente | 20.236 | 41.240 | 49.261 | 48.739 |
| `mul` independente | 20.327 | 41.550 | 21.541 | 8.884 |
| `cnn.dot8` independente | 20.386 | 41.728 | 19.633 | 8.940 |

Leitura da tabela:

- **atomic e timing.** O custo é o mesmo para qualquer classe: ~1 ciclo por instrução na atomic e ~2 na timing, que inclui o acerto na L1I.
- **minor e o3, cadeias `IntMult` dependentes.** Custam ~3,0 ciclos por instrução (≈ 48–49 mil ciclos para 16000 instruções), iguais ao `mul`.
- **`cnn.max8`.** Custa o mesmo que o `add`.
- **Cadeias independentes.** A o3 executa duas por ciclo, porque tem 2 unidades `IntMult`. A minor executa uma por ciclo, porque tem 1 unidade com pipeline.

Em resumo, nas CPUs detalhadas as instruções novas custam o mesmo que um `mul` ou um `add`. Supor que 8 multiplicações cabem na latência de um `mul` é uma hipótese otimista, discutida em [Decisões de projeto](#decisões-de-projeto).

**Limitação: latência própria.** Como `IntMult` é compartilhada com `mul`/`mulw`, mudar a latência dessa classe muda também a referência. Uma latência só das instruções exige uma classe de operação nova no gem5, registrada nas unidades da MinorCPU e da O3CPU. Isso fica para a análise de sensibilidade (RCB-18).

**Alinhamento em atomic e timing.** Com `-march=rv64gc`, uma instrução de 4 bytes pode começar num endereço 2 mod 4, depois de instruções comprimidas, e então a CPU precisa de duas buscas. No mesmo microbenchmark compilado com `rv64gc` e sem caches, as cadeias de instruções personalizadas ficaram desalinhadas e custaram, por instrução, +1 ciclo na atomic e ~+40 na timing, em relação ao `mul` alinhado. O efeito vale para qualquer instrução de 4 bytes, não só para as personalizadas. Ele deve ser lembrado ao comparar `numCycles` de variantes nessas CPUs.

## Como alterar uma instrução

Uma mudança de semântica ou de codificação precisa tocar, juntos:

1. o modelo em C e, se for o caso, a diretiva `.insn` em `benchmarks/common/cnn_insn.h`;
2. a tabela `CASES` em `benchmarks/cnn_insn_semantics/main.c`;
3. a tabela de casos e o pseudocódigo neste documento;
4. o modelo em Python e, se mudar o número de casos, a contagem em `tests/test_custom_insn.py`;
5. `ENCODINGS` e `MODEL_RESULT` em `tests/test_custom_insn_e2e.py`;
6. no fork do gem5, a função em `src/arch/riscv/insts/cnn.hh` (semântica) e o caso em `src/arch/riscv/isa/decoder.isa` (codificação); depois, commit no fork, `make gem5-build` e atualização do submódulo.

Se os itens 2 e 3 divergirem, ou se um valor esperado não bater com o modelo em Python, `pytest` falha.

## Por que estas instruções

### Critério

O conjunto é o menor que cobre os laços internos das sete operações de [scope.md](scope.md) e atende a três restrições:

- usar só os registradores inteiros de 64 bits;
- não acessar a memória;
- ter uma instrução por padrão de cálculo.

Com ativações em NHWC e a dimensão contígua múltipla de 8, um `ld` traz 8 int8 úteis, e os laços se reduzem a quatro padrões:

| Padrão no laço interno | Operações | Instrução |
| --- | --- | --- |
| Produto escalar int8 sobre uma dimensão contígua | Conv direta (sobre `Cin`, por tap), im2col+GEMM, pointwise, FC | `cnn.dot8` |
| MAC por canal, com os taps de um canal não contíguos | Depthwise | `cnn.dwmac` |
| Máximo elemento a elemento | Max pooling | `cnn.max8` |
| Multiplicação por `M0`, arredondamento, deslocamento, ReLU e saturação | Todas, menos o pooling | `cnn.rqnt`, `cnn.rqnt.relu` |

A montagem do buffer do im2col é só cópia de dados e não tem cálculo a acelerar.

Estimativa analítica do laço interno, que **não é medida**. Ela supõe uma referência escalar que carrega cada int8 com `lb` e ignora o controle do laço. Os números medidos da referência e das variantes estão em [kernels.md](kernels.md#instruções-medidas).

| Operação | Bloco | Referência (≈) | Com as instruções |
| --- | --- | --- | --- |
| Conv, im2col+GEMM, pointwise, FC | 8 MACs | 32: 16 `lb` + 8 `mul` + 8 `add` | 3: 2 `ld` + 1 `cnn.dot8` |
| Depthwise | 8 MACs (1 tap × 8 canais) | 32 | 6: 2 `ld` + 4 `cnn.dwmac` |
| Max pooling 2×2 | 8 canais de uma saída | 90 a 110 | 8: 4 `ld` + 3 `cnn.max8` + 1 `sd` |
| Requantização + ReLU | 1 elemento | 10 a 12 | 3: `lw` + `cnn.rqnt.relu` + `sb` |

### Relação com extensões e bibliotecas existentes

| Alternativa | O que oferece | Por que não basta, ou como se relaciona |
| --- | --- | --- |
| PULP-NN sobre Xpulpv2 | `pv.sdotsp.b`: produto escalar de 4 int8 acumulado em 32 bits; `pv.max.b`; cargas com pós-incremento; laços em hardware | É o modelo direto de `cnn.dot8` e `cnn.max8`, que são os análogos com 8 faixas em RV64. As cargas com pós-incremento e os laços em hardware ficaram de fora, porque mudam os acessos à memória e o fluxo de controle. |
| Extensão P (Packed SIMD), proposta | SIMD em registradores inteiros, por exemplo `SMAQA` (4 produtos int8 por palavra de 32 bits) e `SMAX8` | A ideia é a mesma, mas o conjunto é muito maior e acumula em duas faixas de 32 bits, o que exige uma soma final por saída. Não há suporte no gem5 do projeto. Conferir a situação atual da proposta antes de citar. |
| Extensão V (RVV 1.0) | `vwmacc`/`vwmul` + `vwredsum`, `vmax`, `vnclip` | Vira a terceira variante do experimento, comparável às instruções personalizadas. Exige estado vetorial, `vsetvli` e registradores de VLEN bits. Não tem uma instrução única de requantização com multiplicador `M0`. |
| Zve32x / Zve64x | Subconjuntos da V para embarcados | Ainda exigem uma unidade vetorial. As instruções personalizadas cabem num núcleo escalar `rv64gc`. |
| Zbb | `max`/`min` escalares de 64 bits | Não operam em faixas de 8 bits. A referência é compilada com `rv64gc`, sem Zbb, como ficou fixado em [scope.md](scope.md). |
| CMSIS-NN em Cortex-M com extensão DSP | `SXTB16` para expandir int8 em int16 e `SMLAD` para dois MACs de 16 bits | Mostra o custo de não ter produto escalar int8 direto. `cnn.dot8` não precisa expandir os operandos. |

### Candidatas descartadas

| Candidata | Motivo |
| --- | --- |
| Cargas com pós-incremento, MAC fundido com carga, leitura com passo | Seriam instruções de memória. A referência e a variante deixariam de fazer os mesmos acessos, o que confunde a análise de cache, e a implementação no gem5 fica mais complexa. |
| Laços em hardware | Mudam o fluxo de controle e são caras de implementar no gem5. |
| Instrução para o im2col | É cópia de dados, limitada por memória. |
| MAC faixa a faixa em int16 para a depthwise | Transborda com 9 taps: `9 · 16384 > 2^15 - 1`. |
| Variante `cnn.rqnt.hi`, que lê a faixa alta de `cnn.dwmac` | Economizaria um `srai` por par de canais, ao custo de mais uma codificação. Fica como extensão possível. |
| Registradores de 128 bits ou pares de registradores | Fogem do modelo de um destino de 64 bits do RISC-V. |
| Tipos sub-byte, quantização assimétrica ou por canal | Fora do escopo de [scope.md](scope.md). |

## Decisões de projeto

Resumo das decisões tomadas na RCB-10:

| Decisão | Motivo |
| --- | --- |
| Um acumulador int32 no `cnn.dot8` | Uma saída por registrador e nenhuma redução final. `2^24` cabe em 32 bits |
| `IntMult` para dot8, dwmac e rqnt; `IntAlu` para max8 | São instruções de multiplicador ou só de comparação. `IntMult` tem latência 3 tanto na Minor quanto na O3, e as classes `Simd*` têm 6 e 1. Supor que 8 multiplicações cabem na latência de um `mul` é hipótese |
| Instrução própria para a depthwise | Em NHWC os taps de um canal não são contíguos, e acumuladores de 16 bits transbordariam com 9 taps. Por isso são 2 faixas int32 por registrador |
| Header, modelo em C e benchmark nesta issue | Oráculo para a RCB-15, kernels validáveis antes do gem5 e teste pronto para a RCB-13 |
| custom-0 e custom-1 | custom-3 é das m5ops e custom-2 é reservado ao RV128 |
| Nenhum acesso à memória | Mantém as estatísticas de cache comparáveis entre as variantes e simplifica o gem5 |
| Formato R com `rd` como fonte | O formato R4 deixaria só 2 bits para distinguir instruções |
| Empates arredondados para +∞ | É a fórmula de `scope.md`. Difere do arredondamento do TFLite, mas a equivalência é entre as variantes do próprio projeto |
| Bits não usados ignorados | Funções totais, sem traps, o que simplifica o modelo, o gem5 e os testes |
