# O gem5 do fork

O simulador é um fork do gem5 com as instruções personalizadas. Este documento diz de onde ele vem, o que muda em relação ao gem5 oficial, qual commit gerou os resultados e como recompilá-lo ou alterá-lo. A instalação completa está em [installation.md](installation.md).

## Origem

| Item | Valor |
| --- | --- |
| Fork | <https://github.com/YuriMZ-Nunes/gem5>, branch `riscv-cnn-bench` |
| Gem5 oficial | <https://github.com/gem5/gem5>, branch `stable` |
| Base no gem5 oficial | `0c4d16fe9117a7cd25152358d81fd4885bec4b55` (versão 25.1) |
| No projeto | Submódulo `third_party/gem5`; o commit exato é o registrado no repositório (`git submodule status`) |
| Commit dos resultados | `ce032446a6`: o do piloto, da campanha final e dos dados publicados ([data.md](data.md)) |
| Executável dos resultados | `build/RISCV/gem5.opt`, versão 25.1.0.1, compilado em 26/10/2026, SHA-256 `c966242f97555b8d…` |

## O que o fork muda

São dois commits de código sobre a base, cada um mesclado por um pull request no fork:

| Commit | Issue | Arquivos | O quê |
| --- | --- | --- | --- |
| `7a4cefdc76` | RCB-13 | `src/arch/riscv/insts/cnn.{hh,cc}`, `SConscript`, `isa/formats/cnn.isa`, `formats.isa`, `includes.isa`, `isa/decoder.isa` | As cinco instruções (`cnn.dot8`, `cnn.dwmac`, `cnn.max8` em custom-0; `cnn.rqnt` e `cnn.rqnt.relu` em custom-1), a semântica e a decodificação |
| `cd1c254569` | RCB-18 | `src/cpu/op_class.hh`, `src/cpu/FuncUnit.py`, `src/cpu/o3/FuncUnitConfig.py`, `src/cpu/minor/BaseMinorCPU.py` | A classe de operação `CnnMult`, com unidade e latência próprias, que `cpu.custom_latency` e `cpu.custom_units` configuram |

No total, 11 arquivos e 278 linhas acrescentadas. Nada mais do gem5 oficial muda. A semântica e a implementação estão em [custom_instructions.md](custom_instructions.md#implementação-no-gem5), e a latência e as unidades em [scenarios.md](scenarios.md).

## Compilar e conferir

- `make gem5-build` compila `build/RISCV/gem5.opt` dentro do container (`JOBS=4` por padrão) e grava `gem5.opt.build-info.json`, com o commit, a branch, a URL do fork e o hash do executável. Compile sempre por esse alvo, para que as execuções saibam de onde veio o gem5.
- `make gem5-clean` apaga o build, para compilar do zero.
- `make ambiente` confere se o executável ainda é o do build-info ([container.md](container.md#construir-e-conferir)).

Um gem5 recompilado do mesmo commit tem outro hash, porque o executável guarda a data da compilação. As campanhas tratam como desatualizada uma execução feita com outro executável, e a auditoria de uma campanha exige um só ([campaigns.md](campaigns.md), [data.md](data.md#auditoria)).

## Alterar o fork

Trabalhe na branch `riscv-cnn-bench` dentro de `third_party/gem5`, faça o commit e o push no fork, recompile com `make gem5-build` e commite o novo ponteiro do submódulo no repositório principal. Mudar `src/cpu/op_class.hh` recompila boa parte do gem5 (cerca de 19 min com 4 tarefas).

Para trazer atualizações do gem5 oficial, dentro de `third_party/gem5`:

```bash
git remote add upstream https://github.com/gem5/gem5.git   # uma vez por clone
git fetch upstream
```

Uma atualização muda o simulador inteiro, e os resultados antigos deixam de ser comparáveis com os novos. Ela não foi feita depois da base `0c4d16f`.
