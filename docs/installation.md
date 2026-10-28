# Instalação

Do clone ao ambiente conferido: o container, o gem5 do fork, a toolchain e os testes. Depois disto, [reproducibility.md](reproducibility.md) mostra como rodar um exemplo e a matriz completa. A visão das partes está em [architecture.md](architecture.md).

| Parte | Situação |
| --- | --- |
| Passo a passo abaixo | Existente; seguido do zero em 27/10/2026 com uma imagem nova ([container.md](container.md#verificação-num-container-limpo)) |
| Outros sistemas (macOS, Windows, Linux ARM) | Não testados |

## Requisitos

| Item | Detalhe |
| --- | --- |
| Sistema | Linux x86-64. Testado só num host Fedora 44 (kernel 7.2) |
| Podman | Rootless; o `Makefile` usa `--userns=keep-id`. Testado com o Podman 5.8.7. Docker não é usado |
| GNU Make e Git | Para os alvos do `Makefile` e o submódulo do gem5 |
| Rede | Para baixar a imagem base, os pacotes do Ubuntu, o submódulo e as bibliotecas Python |
| Disco | Cerca de 9 GB: imagem 2,3 GB, clone com o histórico do submódulo 0,4 GB, gem5 compilado 5,7 GB, `.venv` 0,3 GB. A campanha final ocupa mais 0,7 GB em `results/` |
| Memória e núcleos | O build do gem5 usa `JOBS=4` por padrão. O consumo de memória não foi medido |

Tudo o mais (compilador RISC-V, QEMU, Python, uv, SCons e as dependências do gem5) vem dentro do container ([container.md](container.md#o-que-vem-de-onde)).

## Passo a passo

```bash
git clone https://github.com/YuriMZ-Nunes/riscv-cnn-bench.git
cd riscv-cnn-bench
git submodule update --init --recursive   # o gem5 do fork em third_party/gem5

make image          # imagem localhost/riscv-cnn-bench:dev (~6 min)
make sync           # .venv com as versões do uv.lock
make gem5-build     # gem5 do fork (15 a 45 min; JOBS=8 para mais núcleos)
make ambiente       # confere tudo e grava build/ambiente.json
make smoke-test     # CLI, testes rápidos, lint e formato (~1 min)
make validate       # ponta a ponta e equivalência das variantes (~20 min)
```

| Passo | O que faz | Como saber que deu certo |
| --- | --- | --- |
| `git submodule update` | Baixa o fork do gem5 no commit registrado pelo repositório | `git submodule status` mostra `ce032446a6…` para `third_party/gem5` |
| `make image` | Constrói a imagem a partir do `Containerfile`, com as versões fixadas | Termina com `Successfully tagged localhost/riscv-cnn-bench:dev` |
| `make sync` | Cria o `.venv` dentro da pasta do projeto, pelo container | `uv sync` sem erro |
| `make gem5-build` | Compila `third_party/gem5/build/RISCV/gem5.opt` e grava `gem5.opt.build-info.json` com o commit, a branch e o hash | O arquivo de build-info existe ao lado do executável |
| `make ambiente` | Compila e roda `rv64gc` e `rv64gcv` no QEMU, confere as versões, o gem5 contra o build-info e as bibliotecas | Saída 0 e todos os itens `ok` |
| `make smoke-test` | Versão da CLI, `pytest` sem os testes longos, `ruff check` e `ruff format --check` | Todos os testes passam |
| `make validate` | Testes de ponta a ponta no gem5 e a equivalência das três variantes em S e L, com dados extremos, no QEMU e no gem5 | Todos os testes passam. `RCB_JOBS=N` muda o paralelismo |

Os tempos são os medidos neste host: imagem em 6 min 11 s, `make validate` em 20 min 09 s com 4 tarefas. O tempo do `make gem5-build` depende da máquina.

Para entrar no container: `make shell`. Lá dentro, a CLI é `uv run riscvcnnbench <comando>`.

## O gem5 do fork

O submódulo `third_party/gem5` aponta para o fork [YuriMZ-Nunes/gem5](https://github.com/YuriMZ-Nunes/gem5), branch `riscv-cnn-bench`. As instruções personalizadas e a classe `CnnMult` existem só nele. O que o fork muda, o commit usado nos resultados e como alterá-lo estão em [environment.md](environment.md).

- **Recompilar** depois de mudar o fork: `make gem5-build`. O SCons recompila só o que mudou, e o build-info é gravado de novo.
- **Do zero:** `make gem5-clean` e depois `make gem5-build`.
- **Conferir:** `make ambiente` compara o hash do executável com o build-info. Cada execução grava os dois no `metadata.json` (`gem5_sha256` e `gem5_build.matches_executable`).

Um gem5 recompilado tem outro hash, mesmo do mesmo commit, porque o executável guarda a data da compilação. A campanha trata como desatualizadas as execuções feitas com outro executável ([campaigns.md](campaigns.md)).

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
| --- | --- | --- |
| `make image` falha com `Version '...' for '...' was not found` | Uma versão fixada no `Containerfile` saiu do índice do Ubuntu | [container.md](container.md#versões-fixadas-e-o-que-fazer-quando-uma-some) |
| `third_party/gem5` vazio | O clone foi feito sem os submódulos | `git submodule update --init --recursive` |
| `make ambiente` mostra `gem5  FALTA` | O gem5 não foi compilado, ou foi compilado fora do `make gem5-build` | `make gem5-build` |
| `build-info NÃO confere` | O executável mudou depois do registro | `make gem5-build` de novo |
| Um container perde o acesso aos arquivos | Dois containers rodando ao mesmo tempo com a pasta montada: o `:Z` reetiqueta os arquivos para o último | Rode um container por vez |
| Aviso `The input device is not a TTY` | Alvo do `make` chamado sem terminal (os alvos usam `-it`) | Só um aviso; o comando roda |
| `make e2e-test` ou `make validate` falham logo no início | Os testes de ponta a ponta exigem o gem5 compilado e a toolchain, e falham (não são pulados) sem eles | `make gem5-build` antes de `make e2e-test` ou `make validate` |

## Depois da instalação

- Um experimento: `make run EXPERIMENT=experiments/fc_s.yaml` ([experiments.md](experiments.md)).
- Montar um experimento sem escrever YAML: `make gerador` ([generator.md](generator.md)).
- O exemplo rápido e a matriz completa: [reproducibility.md](reproducibility.md).
