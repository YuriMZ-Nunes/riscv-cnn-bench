# Container e dependências

O que a imagem do projeto contém, as versões fixadas, como construí-la e conferi-la, e o que foi verificado num container limpo (RCB-27). A instalação passo a passo está no README.

| Parte | Situação |
| --- | --- |
| `Containerfile` com a imagem base e as ferramentas RISC-V fixadas | Existente |
| `riscvcnnbench ambiente` e `make ambiente`: confere e registra o ambiente | Existente (`src/riscvcnnbench/environment.py`) |
| Verificação num container limpo (build da imagem, experimento de referência, `make validate`) | Executada em 27/10/2026 ([resultado](#verificação-num-container-limpo)) |

## O que vem de onde

| Parte | De onde vem | Versão |
| --- | --- | --- |
| Sistema base | `docker.io/library/ubuntu:24.04`, fixado pelo digest `sha256:1e0a86e5…` | Ubuntu 24.04 |
| Compilador RISC-V | `gcc-13-riscv64-linux-gnu`, `g++-13-…`, `cpp-13-…` (e os metapacotes `gcc-riscv64-linux-gnu`) | 13.3.0-6ubuntu2~24.04.1cross1 |
| binutils RISC-V | `binutils-riscv64-linux-gnu` | 2.42-4ubuntu2.10 |
| glibc para RISC-V | `libc6-dev-riscv64-cross` | 2.39-0ubuntu8cross1 |
| QEMU (modo usuário) | `qemu-user` | 1:8.2.2+ds-0ubuntu1.18 |
| Python | `python3` do Ubuntu | 3.12.3 |
| uv | instalador oficial, versão fixada (`UV_VERSION`) | 0.12.23 |
| SCons e dependências de build do gem5 | pacotes do Ubuntu (Boost, protobuf, HDF5, capstone, libelf, zlib e outros) | SCons 4.5.2 |
| Graphviz | dependência do `python3-pydot`, para o `config.dot` do gem5 | 2.42.2 |
| Bibliotecas Python do framework | `uv sync` (`make sync`), com as versões travadas no `uv.lock` | pydantic 2.13.5, typer 0.27.2, PyYAML 6.0.3, pandas 2.3.3, matplotlib 3.11.1; desenvolvimento: pytest 8.4.2, ruff 0.16.5, quickjs 1.19.4 |
| gem5 do fork | submódulo `third_party/gem5`, compilado por `make gem5-build` dentro do container; fica na pasta do projeto, não na imagem | 25.1.0.1, commit `ce03244` |

A imagem tem só as ferramentas. O código, o `.venv` e o gem5 compilado ficam na pasta do projeto, montada em `/workspace`.

Os pacotes `python3-pandas`, `python3-matplotlib` e `python3-pytest` do Ubuntu também estão na imagem, mas o framework usa os do `.venv`, travados pelo `uv.lock`.

## Construir e conferir

```bash
make image            # constrói a imagem localhost/riscv-cnn-bench:dev
make sync             # cria o .venv com o uv.lock
make gem5-build       # compila o gem5 do fork (15 a 45 min) e grava o build-info
make ambiente         # confere e registra o ambiente em build/ambiente.json
make smoke-test       # CLI, testes, lint e formato
make validate         # e2e e validação de equivalência (~20 min com RCB_JOBS=4)
```

`make ambiente` roda `riscvcnnbench ambiente` dentro do container, com o nome e o ID da imagem. Ele confere cada item:

| Item | Como confere |
| --- | --- |
| Toolchain e binutils | `riscv64-linux-gnu-gcc --version` e `as --version` |
| `rv64gc` | Compila um programa escalar com `-march=rv64gc -static` e roda no `qemu-riscv64`, conferindo a saída |
| `rv64gcv` | Compila um programa com intrínsecos RVV (`riscv_vector.h`) com `-march=rv64gcv` e roda no QEMU com `-cpu rv64,v=true,vlen=256,vext_spec=v1.0`, os parâmetros dos testes das variantes RVV |
| QEMU, Python, uv, SCons, Git | A versão de cada um |
| gem5 | A versão (`--build-info`), o hash do executável e se ele confere com o `gem5.opt.build-info.json` de `make gem5-build` |
| Bibliotecas Python | A versão instalada de cada uma; as do framework são obrigatórias, as de desenvolvimento só avisam |
| Imagem | `RCB_IMAGE` e `RCB_IMAGE_ID`, que o `make` passa; chamado direto no `make shell`, fica como aviso |

A saída é 0 quando todos os itens obrigatórios estão ok, e 1 quando falta algum. Para comparar dois ambientes, compare os `build/ambiente.json` deles. Com `--json`, o mesmo documento vai para a tela.

## Imagens e campanhas

Cada execução grava no `metadata.json`, em `environment`, a plataforma, o Python e o compilador RISC-V. Quando rodada pelo `make`, grava também o nome e o ID da imagem.

| Imagem | Uso |
| --- | --- |
| `localhost/riscv-cnn-bench:campanha-final` | Etiqueta local (RCB-27) da imagem `308bf637ff88…`, criada em 07/10/2026. Foi a imagem que rodou o piloto e a campanha final, que não a registraram ([data.md](data.md#limitações)). Mantida para reproduzir exatamente aquele ambiente |
| `localhost/riscv-cnn-bench:dev` | A imagem de trabalho; `make image` a reconstrói |

Para guardar uma imagem fora da máquina: `podman save -o riscv-cnn-bench-campanha-final.tar localhost/riscv-cnn-bench:campanha-final`. O arquivo tem cerca de 2,3 GB.

## Versões fixadas e o que fazer quando uma some

O Ubuntu mantém no índice do apt só a versão mais recente de cada pacote em `noble-updates`. Uma versão fixada no `Containerfile` some do índice quando sai uma correção nova, e aí `make image` falha com "Version ... not found". Em 27/10/2026, todas as versões fixadas ainda eram as candidatas do índice.

Quando uma versão sumir, há três saídas:

1. **Atualizar a versão fixada** para a nova candidata, reconstruir e repetir `make ambiente` e `make validate`. Os binários dos benchmarks podem mudar com outro compilador. Compare o `binary_sha256` das execuções antes de juntar resultados de imagens diferentes.
2. **Usar o arquivo de snapshots do Ubuntu.** O `snapshot.ubuntu.com` serve o índice de uma data, e o apt do 24.04 aceita `apt-get update --snapshot <AAAAMMDDTHHMMSSZ>`. Isto não foi testado no projeto.
3. **Usar a imagem guardada**: `podman load -i <arquivo>.tar`.

## Verificação num container limpo

Em 27/10/2026, a imagem foi reconstruída do zero (`podman build --no-cache`, etiqueta `localhost/riscv-cnn-bench:rcb27`) com o `Containerfile` desta revisão. Depois, foi comparada com a imagem da campanha (`:campanha-final`, `308bf637ff88`). O gem5 compilado e o `.venv` foram os da pasta do projeto, iguais para as duas.

| Conferência | Resultado |
| --- | --- |
| Build | 6 min 11 s, sem passo manual; imagem `dc2f0fc013e8`, 2,25 GB |
| Pacotes do Ubuntu | 561 nas duas; 31 com versão diferente, todos atualizações de segurança mais novas que as da imagem de 07/10 (ca-certificates, curl, git, libxml2, linux-libc-dev, openssh-client, protobuf, tzdata, xz-utils, zlib e outros). Toolchain RISC-V, QEMU, Python e SCons iguais |
| `riscvcnnbench ambiente` | Saída 0 nas duas; a única diferença é a imagem |
| Experimento de referência (fc S, `custom`, minor, `l1-l2`) | Mesmo `binary_sha256` (`ed782e8b4dc0…`), mesmo gem5, `stats.txt` igual linha a linha sem as `host*` (2224 linhas), 18.968 ciclos na região de interesse nas duas |
| `make smoke-test` (versão, `pytest`, `ruff check`, `ruff format --check`) | 353 testes passaram; lint e formato limpos |
| `make validate` (`pytest -m "e2e or validation"`) | 253 testes passaram em 20 min 09 s (`RCB_JOBS=4`) |

O experimento de referência rodou com caminhos de pasta de mesmo tamanho nas duas imagens (`build/rcb27/old` e `build/rcb27/new`). O tamanho do caminho da pasta de execução entra na pilha do programa (`argv`) e muda os ciclos em cerca de 0,04 %. Com caminhos de mesmo tamanho, os ciclos são idênticos.

Conclusão: com as versões fixadas hoje, a imagem nova gerou o mesmo binário e as mesmas estatísticas que a imagem da campanha no experimento de referência, e passou em toda a validação. As diferenças ficam em pacotes que não entram na compilação nem na simulação. Os binários das outras operações não foram comparados um a um. A `:dev` não foi trocada pela `:rcb27`: a decisão de reconstruí-la fica para quando uma versão fixada sumir.

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_environment.py` | Com comandos simulados: a versão de cada ferramenta (inclusive o SCons pelo padrão), ferramenta ausente, gem5 ausente, sem build-info, conferindo e não conferindo; imagem informada ou não; só os itens obrigatórios decidem; a CLI (tabela, JSON, arquivo e saída 1) | `make test` |
| `tests/test_environment_e2e.py` | O ambiente real do container: toolchain, `rv64gc` e `rv64gcv` no QEMU, Python, SCons, gem5 e as bibliotecas | `make e2e-test` |

## Limitações

- **A imagem não é reproduzível bit a bit.** As camadas mudam de hash a cada build, porque os arquivos têm datas. O que se fixa são as versões dos pacotes. O `make ambiente` registra as versões, e o `binary_sha256` de cada execução mostra se o compilador gerou o mesmo binário.
- **Só algumas versões estão fixadas:** as da cadeia RISC-V, do QEMU e do uv. As dependências de build do gem5 e o Python do Ubuntu vêm na versão do índice no dia do build.
- **O gem5 compilado não está na imagem.** Ele depende do `make gem5-build` na pasta do projeto, que leva de 15 a 45 minutos.
