## gem5

- Origem: fork https://github.com/YuriMZ-Nunes/gem5, branch `riscv-cnn-bench`
- Upstream: https://github.com/gem5/gem5 (branch `stable`)
- Revisão: 0c4d16fe9117a7cd25152358d81fd4885bec4b55 (igual ao upstream; o fork ainda não tem
  mudanças próprias)
- Build: `build/RISCV/gem5.opt`

As instruções personalizadas (RCB-13) serão commitadas na branch `riscv-cnn-bench` do fork.
Para trazer atualizações do gem5 oficial, dentro de `third_party/gem5`:

```bash
git remote add upstream https://github.com/gem5/gem5.git   # uma vez por clone
git fetch upstream
```
