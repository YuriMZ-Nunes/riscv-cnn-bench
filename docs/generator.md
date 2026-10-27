# Gerador de experimentos

Uma página para montar o YAML de um experimento, ou a matriz de uma campanha, sem escrevê-lo à mão (RCB-31). Você escolhe operação, tamanho, implementações, CPU, memória e flags. A página mostra o YAML, quantas simulações ele dá, onde ficam os dados de cada operação e o comando para rodar. As opções vêm do próprio código do projeto, e só as combinações válidas aparecem.

| Parte | Situação |
| --- | --- |
| `riscvcnnbench gerador` e `make gerador` (`src/riscvcnnbench/generator.py`, `src/riscvcnnbench/web/`) | Existente |
| Teste do JavaScript da página com o QuickJS, conferindo o YAML gerado com o validador | Existente (`tests/test_generator.py`) |

## Gerar e abrir

```bash
make gerador                                        # grava build/gerador.html
make gerador MEASURED="results/campaigns/final"     # com estimativa de tempo
xdg-open build/gerador.html                         # fora do container, no navegador
```

Dentro do container: `uv run riscvcnnbench gerador [-o <arquivo.html>] [-m <pasta>]... [--force]`. O padrão é `build/gerador.html`, que fica fora do Git. Sem `--force`, o comando recusa sobrescrever uma página que já existe.

A página é um arquivo HTML só, com o script e os estilos embutidos. Ela funciona sem servidor e sem internet, e pode ser copiada para outra máquina. Ela não executa simulações: só escreve o YAML. Para rodar, use o comando que ela mostra.

## O que a página faz

1. **Escolhas.** Escolha uma ou mais opções em cada seção:
   - operação e tamanho (S ou L);
   - implementações (`ref`, `custom`, `rvv`);
   - CPU e clock;
   - latência das instruções personalizadas (só aparece com a `custom` e uma CPU minor, o3 ou o3-edge);
   - VLEN (só aparece com a `rvv`);
   - cenário de memória, memória personalizada e estado das caches;
   - flags do compilador e conjunto de dados;
   - nome e descrição.
2. **Memória personalizada.** Além dos cenários nomeados, dá para definir a memória à mão: tamanho, associatividade, latência, MSHRs, alvos por MSHR e prefetcher da L1i, da L1d e da L2 (cada nível pode ser desligado), a linha das caches, e tipo (`simple` ou `ddr4`) e tamanho da memória principal ([scenarios.md](scenarios.md#ajustes-das-caches)). Vários tamanhos separados por vírgula num nível viram uma varredura, como `8KiB, 16KiB, 32KiB` na L1d, e marcar mais de um prefetcher compara com e sem ele. Os ajustes começam nos padrões e só entram no YAML quando mudam. A página só aceita tamanhos cujo número de conjuntos, tamanho ÷ (linha × associatividade), seja potência de 2, como o gem5 exige, e só aceita L2 com L1i e L1d. O tamanho da memória principal não muda os resultados: os programas usam menos de 1 MiB.
3. **Conjunto de dados.** `random` é o padrão das medições; `satpos` e `satneg` são os dados extremos da validação. Eles vêm de `benchmarks/common/rcb_data.h` e entram como `-DRCB_DATA=<n>` em `compiler.flags` ([kernel_base.md](kernel_base.md#dados-determinísticos)).
4. **Experimento ou campanha.** Se tudo der uma combinação só, a página gera o YAML de um experimento ([experiments.md](experiments.md)). Se der várias, gera a matriz de uma campanha ([campaigns.md](campaigns.md)). A matriz põe em `vary` o que tem mais de um valor e em `set` o que tem um só e não é o padrão. Os cenários nomeados ficam no grupo `principal`, e a memória personalizada num grupo `memoria`, porque a campanha não mistura `scenario` com `cache` e `memory` no mesmo grupo.
5. **Contagem.** A página conta as simulações distintas com a mesma normalização do `campaign plan`. A latência só vale para a `custom` nas CPUs com unidades funcionais (minor, o3 e o3-edge), e a VLEN só para a `rvv`; fora disso, as combinações repetidas contam uma vez.
6. **Problemas.** O que não pode rodar aparece numa lista, e o YAML só sai quando ela está vazia:
   - nome fora do padrão;
   - seção sem escolha;
   - caches frias numa configuração sem caches;
   - "sem cenário" junto de outros cenários ou da memória personalizada;
   - na memória personalizada, tamanho fora do formato, número de conjuntos que não é potência de 2, ou L2 sem L1;
   - latência fora de 1 a 64;
   - clock fora do formato.
7. **Onde ficam os dados.** Para cada operação e tamanho escolhidos, a página mostra o tamanho dos dados da região de interesse e o nível em que eles cabem em cada configuração de memória: L1d, L2, ou DRAM (memória, com a `simple`). A regra é a da capacidade, que a medição confirmou nas 56 células da tabela de [scenarios.md](scenarios.md#o-que-cabe-em-cada-nível). Quando os dados vêm da DRAM, a memória tende a limitar o ganho ([analysis.md](analysis.md#onde-a-memória-limita-o-ganho)).
8. **Tempo.** Se a página foi gerada com `--measured`, ela estima o tempo de cada simulação pelo mesmo modelo do `campaign estimate` ([matrix.md](matrix.md#como-a-estimativa-é-feita)): a + b · W, com W as instruções simuladas do binário e a reta da CPU e do cenário. Mostra o total em série e com N tarefas. Configurações de memória que nunca foram medidas não têm reta, e as combinações delas ficam fora da estimativa. Sem uma execução medida do mesmo binário, ou sem a reta da CPU e do cenário, a combinação fica fora da estimativa, e a página diz quantas ficaram.
9. **Salvar e rodar.** "Baixar YAML" grava `<nome>.yaml` na pasta de downloads do navegador, e "Copiar" põe o texto na área de transferência. Guarde o arquivo em `build/meus/`, dentro da pasta do projeto: o container só enxerga essa pasta, e `build/` fica fora do Git, então as execuções não saem com `dirty: true`. A página mostra os comandos: `make run` para um experimento; `make campaign-plan`, `make campaign`, `report`, `plot` e `analyze` para uma campanha.

## De onde vêm as opções

A página é gerada a partir do código. Quando um benchmark, um cenário ou um limite muda, basta gerar a página de novo.

| Opção | Fonte |
| --- | --- |
| Operações | As pastas de `benchmarks/` com Makefile e com `experiments/<operação>_s.yaml` ou `_l.yaml` |
| Implementações de cada operação | `config.available_variants`: `ref` e um `kernel_<variante>.c` por variante |
| Tamanhos S e L | Os argumentos de `experiments/<operação>_{s,l}.yaml`; os nomes dos argumentos vêm do comentário `# args:` |
| Tamanho dos dados | A fórmula de cada operação em `generator.FOOTPRINT` (entrada, pesos, bias, saída e o buffer da im2col), conferida pelo teste com a tabela de [scenarios.md](scenarios.md#o-que-cabe-em-cada-nível) |
| Cenários de memória | `configs/scenarios.yaml`, com a descrição e os tamanhos das caches |
| Memória personalizada | Os valores iniciais vêm do cenário `l1-l2`; os tipos e o padrão da memória, de `MemoryConfig`; o formato dos tamanhos, de `SIZE_PATTERN`; a linha de 64 bytes, de `generator.CACHE_LINE` (padrão do gem5) |
| Conjuntos de dados | As definições de `RCB_DATA_NAME` em `benchmarks/common/rcb_data.h` |
| CPUs, VLEN, limites da latência, padrões de nome e clock | Os modelos Pydantic de `config.py` (`CpuConfig`, `BenchmarkConfig`, `NAME_PATTERN`, `CLOCK_PATTERN`) |
| Estimativa | `estimate.samples` e `estimate.fit` sobre as pastas de `--measured` |

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_generator.py` | Roda o `gerador.js` da página no QuickJS (dependência de desenvolvimento `quickjs`). Confere: os dados tirados do código; o tamanho dos dados e o nível onde eles ficam contra a tabela de [scenarios.md](scenarios.md#o-que-cabe-em-cada-nível) (14 linhas); escolhas únicas nas 7 operações, em S e L, em quatro configurações, e uma com memória personalizada, dados `satpos` e caches frias, que geram experimentos aceitos pelo `load_experiment`, com as chaves da estimativa iguais às do `estimate.py`; escolhas múltiplas que geram matrizes cujo `campaign plan` não tem combinações inválidas e tem exatamente as mesmas combinações da página (inclusive as 504 do grupo principal da matriz final, uma varredura de L1d e L2 com dois grupos e uma com linha, latência, MSHRs e varredura de prefetchers); um experimento com todos os ajustes das caches, com o rótulo do cenário igual ao do Python; as mensagens de problema; a estimativa a partir de execuções medidas; a página gravada; e a CLI | `make test` |

## Limitações

- **Só os tamanhos S e L.** Outras dimensões exigem editar `benchmark.args` no YAML gerado ([experiments.md](experiments.md)). As restrições de cada kernel não estão no gerador (por exemplo, `Cin` múltiplo de 8 na custom).
- **Uma memória personalizada por vez**, com uma associatividade por nível; a varredura é só nos tamanhos. Para comparar associatividades, gere uma matriz por vez ou edite o `vary`.
- **Uma latência, um número de MSHRs e de alvos por nível**; a varredura é só nos tamanhos e no prefetcher.
- **Só `-O2` e `-O3`.** Outras flags exigem editar `compiler.flags`.
- **Uma matriz com um grupo só.** Grupos diferentes, como o contraste de compilador da matriz final, exigem editar a matriz ([campaigns.md](campaigns.md)).
- **A estimativa usa só o modelo.** Mesmo quando a combinação exata foi medida, a página usa a reta, e não a duração medida. O erro do modelo é maior em operações limitadas pela memória ([matrix.md](matrix.md#campanha-final-previsto--medido)).
- **A página não confere o YAML depois de editado à mão.** Para isso, use `uv run riscvcnnbench validate` ou `campaign plan`.
