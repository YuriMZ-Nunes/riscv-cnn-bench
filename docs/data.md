# Dados da campanha final

Resultado da execução da matriz final ([matrix.md](matrix.md)) e o pacote em que os dados são publicados (RCB-24). Os resultados ficam em `results/campaigns/final/`, que o Git ignora. Saem do repositório num pacote `.tar.gz`, anexado a uma release do GitHub e depositado no Zenodo, sob a licença CC BY 4.0.

| Parte | Situação |
| --- | --- |
| Campanha final executada (620 combinações), com CSV e gráficos | Existente, 27/10/2026 |
| Auditoria de uma campanha: `riscvcnnbench campaign audit` | Existente (`src/riscvcnnbench/package.py`) |
| Pacote de dados: `riscvcnnbench campaign package` | Existente |
| Release no GitHub com o pacote | Planejado: depende do merge desta entrega |
| Depósito no Zenodo e DOI | Planejado: feito pelo autor, com a conta dele |
| Análise dos resultados | Planejado (RCB-25) |

## O que rodou

```bash
make campaign MATRIX=campaigns/final.yaml JOBS=4
uv run riscvcnnbench report results/campaigns/final
uv run riscvcnnbench plot results/campaigns/final
uv run riscvcnnbench campaign audit results/campaigns/final
```

Em 27/10/2026, com o commit `06fe772` (o merge da RCB-23), a árvore limpa e o fork do gem5 em `ce03244`:

| Etapa | Quando (UTC) | Resultado |
| --- | --- | --- |
| Validação de equivalência (`validate: true`, `pytest -m validation`) | 14:30:19 a 14:39:56 | Aprovada |
| 620 simulações, 4 tarefas | 14:39:57 a 17:32:04 (2 h 52 min) | 620 concluídas, nenhuma falha |
| `report` | | 620 execuções válidas, todas valendo (`current`), nenhuma com checksum divergente; 734 pares (730 de variante, 4 de compilador), nenhum rejeitado |
| `plot` | | 51 figuras: 25 de variantes, 13 de speedup, 13 de R_I × S_C |
| `campaign audit` | | Sem problemas |

Nada mudou na árvore durante a campanha, como manda a regra adotada depois do piloto ([pilot.md](pilot.md#problemas-encontrados)). Todas as execuções registraram `project.dirty: false`.

O tempo ficou dentro da estimativa: 11,43 h em série contra 11,34 h previstas, e 2 h 52 min com 4 tarefas contra cerca de 2 h 50 min. Por combinação, o modelo errou mais na FC L ([matrix.md](matrix.md#campanha-final-previsto--medido)).

## Auditoria

`riscvcnnbench campaign audit <pasta da campanha>` não executa nada. Ela confere, em cada combinação do plano, a execução que vale: a mais recente concluída com o executável do gem5 mais frequente na campanha, como em `campaign status`.

| Conferência | Se falhar |
| --- | --- |
| Concluída, com a linha `RESULT` e `mismatches=0` (`RunMetrics.problem`) | Problema |
| `project.dirty` e `gem5_repository.dirty` falsos | Problema |
| `gem5_build.matches_executable` verdadeiro: o executável é o do build registrado | Problema |
| Todas do mesmo commit do projeto | Problema |
| Validação de equivalência aprovada no `campaign.json`, do mesmo commit e do mesmo gem5 | Observação |
| Execuções a mais nas pastas (repetidas ou substituídas), e quantas com `dirty: true` | Observação |
| `report/runs.csv` e `figures/figures.json` presentes | Observação |

A saída é 0 sem problemas e 1 com eles, que são listados um por linha. As observações não impedem o pacote, mas ficam registradas no README e no `MANIFEST.json` dele.

Nas duas campanhas publicadas:

| Campanha | Combinações | Commit | Observações |
| --- | --- | --- | --- |
| `final` | 620 de 620 | `06fe772` | Nenhuma |
| `piloto` | 64 de 64 | `ecb7223` | 12 execuções a mais, 8 delas com `dirty: true` (as substituídas, [pilot.md](pilot.md#problemas-encontrados)); sem validação no `campaign.json`, porque o piloto não usou `validate: true` |

## Pacote

```bash
uv run riscvcnnbench campaign package results/campaigns/final results/campaigns/piloto \
    -o results/pacotes/riscv-cnn-bench-dados-v1.tar.gz
```

Fora do container: `make campaign-package DIRS="results/campaigns/final results/campaigns/piloto" OUT=results/pacotes/riscv-cnn-bench-dados-v1.tar.gz`.

O comando faz a auditoria de cada campanha e recusa se houver problemas. Com `--allow-problems`, empacota mesmo assim, e os problemas ficam no README e no MANIFEST. Ele também recusa se o arquivo já existe ou se duas campanhas têm pastas com o mesmo nome. A pasta raiz dentro do pacote é o nome do arquivo sem `.tar.gz`, ou o `--name`:

```text
riscv-cnn-bench-dados-v1/
  README.md         o que é, cada campanha (descrição, contagens, período, commits, validação, observações)
  LICENSE.txt       CC BY 4.0
  MANIFEST.json     o mesmo em JSON, mais o hash do gem5 e o commit do código que gerou o pacote
  SHA256SUMS        hash de cada arquivo acima e das campanhas
  campanhas/
    final/          a pasta da campanha inteira: campaign.yaml, plan.json, experiments/,
    piloto/         campaign.json, validation.log, runs/, report/, figures/
```

A pasta de cada execução está descrita em [results.md](results.md), as tabelas em [report.md](report.md) e as figuras em [plots.md](plots.md). O pacote leva tudo o que a campanha tem, inclusive as execuções substituídas do piloto, para que o histórico possa ser conferido. As tabelas marcam com `current` a execução que vale.

O executável do gem5 não vai no pacote. Ele é identificado pelo hash (`gem5_sha256`), pelo build-info e pelo commit do fork, e pode ser compilado de novo a partir deles ([hello_riscv.md](hello_riscv.md)). Os binários RISC-V de cada execução vão em `inputs/`.

Para conferir depois de baixar:

```bash
tar -xzf riscv-cnn-bench-dados-v1.tar.gz
cd riscv-cnn-bench-dados-v1 && sha256sum -c SHA256SUMS
```

Um pacote de teste, gerado em 27/10/2026 antes do commit, tinha 260,9 MB compactado e 797 MB extraído, com 12.006 arquivos. O `sha256sum -c` passou em todos. O pacote publicado deve ser gerado de novo depois do merge, para que o `MANIFEST.json` registre um commit do código com a árvore limpa.

## Publicação

O pacote é publicado em dois lugares: numa **release do GitHub**, junto do código que o gerou, e no **Zenodo**, que dá um DOI permanente para citar.

### Release no GitHub

Depois do merge, a partir da `main`:

```bash
gh release create dados-v1 results/pacotes/riscv-cnn-bench-dados-v1.tar.gz \
    --title "Dados da campanha final (v1)" --notes-file <notas>
```

A tag `dados-v1` marca o commit do código que gerou o pacote. As notas repetem o README do pacote e o hash SHA-256 do `.tar.gz`. O limite do GitHub é de 2 GiB por arquivo anexado.

### Zenodo

O depósito é feito pelo autor, em <https://zenodo.org/uploads/new>, enviando o mesmo `.tar.gz`. A integração automática do Zenodo com o GitHub arquiva o código-fonte da release, não os arquivos anexados, então os dados vão como um depósito próprio.

| Campo | Valor |
| --- | --- |
| Tipo | Dataset |
| Título | riscv-cnn-bench: dados de simulação de operações de CNN int8 em RISC-V no gem5 (v1) |
| Autores | O autor do TCC, com ORCID se houver |
| Descrição | O primeiro parágrafo e a lista de campanhas do README do pacote |
| Versão | v1 |
| Licença | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| Palavras-chave | RISC-V, gem5, CNN, quantização int8, RVV, instruções personalizadas, simulação |
| Identificadores relacionados | *is supplement to* o repositório <https://github.com/YuriMZ-Nunes/riscv-cnn-bench> (ou a release `dados-v1`); *is derived from* o fork <https://github.com/YuriMZ-Nunes/gem5> |

O Zenodo reserva o DOI antes da publicação ("Reserve DOI"). Assim dá para pôr o DOI nas notas da release e neste documento antes de publicar. Uma versão nova dos dados (v2) entra como nova versão do mesmo registro. O DOI do conceito continua apontando para a mais recente.

### Como citar

Até o depósito, a referência é provisória:

> Autor. *riscv-cnn-bench: dados de simulação de operações de CNN int8 em RISC-V no gem5*, versão 1. Zenodo, 2026. DOI: a definir.

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_package.py` | Auditoria de uma campanha falsa limpa (contagens, commits, período, caminho relativo) e com problemas (`dirty`, `mismatches`, falha, dois commits), a refeita limpa valendo e a antiga como observação; conteúdo do pacote (pasta raiz, dono anônimo, README, MANIFEST, licença), cada linha do `SHA256SUMS` contra o arquivo, recusa com problemas, pacote existente e pastas de mesmo nome; a CLI | `make test` |

## Limitações

- O piloto entra no pacote como registro do processo, não como dado da análise ([pilot.md](pilot.md#limitações)).
- A auditoria confere a proveniência gravada pelo wrapper. Ela não roda as simulações de novo. O determinismo foi conferido no piloto, no mesmo host ([pilot.md](pilot.md#determinismo)).
- A imagem do container não vai no pacote, e as execuções das duas campanhas não a identificam: `environment.container_image_id` ficou nulo. O alvo `make campaign` não passava `RCB_IMAGE` e `RCB_IMAGE_ID` (corrigido nesta entrega), e a campanha final foi lançada com `podman run` direto. A imagem presente no host era `localhost/riscv-cnn-bench:dev`, ID `308bf637ff88…`, criada em 07/10/2026. É anterior à última mudança do `Containerfile` (10/10/2026, que fixou o digest da imagem base e a versão do uv), então uma reconstrução pode não sair igual. O que cada execução grava em `environment` é a plataforma, o Python (3.12.3) e o compilador RISC-V (`riscv64-linux-gnu-gcc` 13.3.0-6ubuntu2~24.04.1). O hash do binário compilado (`binary_sha256`) também fica registrado.
- Os dados são sintéticos e a avaliação é por operação ([scope.md](scope.md)). Não há rede completa nem dataset.
