## gem5

- Origem: fork https://github.com/YuriMZ-Nunes/gem5, branch `riscv-cnn-bench`
- Upstream: https://github.com/gem5/gem5 (branch `stable`)
- Base: 0c4d16fe9117a7cd25152358d81fd4885bec4b55 do upstream. Sobre ela, a branch
  `riscv-cnn-bench` tem código próprio: as instruções personalizadas (RCB-13), restritas a
  `src/arch/riscv/` (ver `docs/custom_instructions.md`, seção "Implementação no gem5").
  O commit exato é o registrado no submódulo (`git submodule status`).
- Build: `build/RISCV/gem5.opt`, sempre por `make gem5-build`, que grava commit, branch e URL
  do fork em `gem5.opt.build-info.json`.

Para alterar o gem5, trabalhe na branch `riscv-cnn-bench` dentro de `third_party/gem5`, faça o
commit e o push no fork, recompile com `make gem5-build` e commite o novo ponteiro do submódulo
no repositório principal.
Para trazer atualizações do gem5 oficial, dentro de `third_party/gem5`:

```bash
git remote add upstream https://github.com/gem5/gem5.git   # uma vez por clone
git fetch upstream
```
