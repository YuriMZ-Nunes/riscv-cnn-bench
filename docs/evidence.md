# Evidências por objetivo

Onde está a evidência de cada resposta do TCC: a pergunta de pesquisa, os objetivos específicos da proposta, as hipóteses, e as tabelas e figuras que sustentam cada uma. Cada item aponta o documento, o CSV e a campanha de onde vem, para que um número do texto possa ser seguido até as execuções. Os números estão em [analysis.md](analysis.md); aqui fica só o caminho até eles.

| Parte | Situação |
| --- | --- |
| Mapa da pergunta, dos objetivos específicos 1 a 5 e das hipóteses para as evidências | Existente |
| Tabelas e figuras sugeridas para o texto, com a origem de cada uma | Existente; a escolha final é do texto do TCC |
| Texto da monografia | Fora do repositório |

## Fontes

| Fonte | Onde | Como refazer |
| --- | --- | --- |
| Campanha final: 620 execuções (`principal`, `latencia`, `compilador`) | `results/campaigns/final/`; no pacote publicado, `campanhas/final/` ([data.md](data.md)) | `make campaign MATRIX=campaigns/final.yaml` ([reproducibility.md](reproducibility.md#matriz-completa)) |
| Tabelas por execução e por par | `report/runs.csv`, `report/pairs.csv` da campanha | `make report DIR=results/campaigns/final` ([report.md](report.md)) |
| Tabelas da análise | `analysis/instructions.csv`, `speedup.csv`, `variants.csv`, `latency.csv`, `compiler.csv` e `tables.md` | `make analyze DIR=results/campaigns/final` ([analysis.md](analysis.md#reproduzir)) |
| Figuras | `figures/*.pdf` e `*.png`; a legenda sugerida e o contexto de cada uma em `figures/figures.json` | `make plot DIR=results/campaigns/final` ([plots.md](plots.md)) |
| Piloto (processo e determinismo) | `results/campaigns/piloto/`; no pacote, `campanhas/piloto/` | [pilot.md](pilot.md) |
| Dados publicados | DOI [10.5281/zenodo.23698495](https://doi.org/10.5281/zenodo.23698495), release [`dados-v1`](https://github.com/YuriMZ-Nunes/riscv-cnn-bench/releases/tag/dados-v1) | [data.md](data.md) |

A campanha final rodou em 27/10/2026 com o commit `06fe772` do projeto e o fork do gem5 em `ce03244` ([data.md](data.md#o-que-rodou)). Toda linha do `runs.csv` tem o caminho da pasta da execução, e cada pasta tem o `metadata.json` com a proveniência ([results.md](results.md)).

## Pergunta de pesquisa

> Como instruções RISC-V personalizadas afetam a quantidade de instruções executadas, o número de ciclos e as instruções por ciclo das principais operações de CNN utilizadas na inferência para Edge AI, em diferentes configurações de cache e memória?

| Parte da resposta | Evidência |
| --- | --- |
| Instruções: a custom reduz de 2,0× a 12,6×; nas operações com MAC, de 3,5× a 9,2× | `analysis/instructions.csv` (`r_i_custom`, `r_i_rvv`); [analysis.md](analysis.md#instruções) |
| Ciclos: no `l1-l2`, de 1,6× a 22,9×; nas operações com MAC, de 3,6× a 10,1× | `analysis/speedup.csv` (`pair = ref→custom`, `s_c`); `tables.md`, seções "Speedup em ciclos S_C"; [analysis.md](analysis.md#ciclos-e-ipc) |
| IPC: a custom executa com IPC maior que a ref na minor e na o3-edge em várias operações, e menor nas limitadas pela memória | `analysis/variants.csv` (`ipc`); `analysis/speedup.csv` (`efficiency` = razão de IPC); [analysis.md](analysis.md#quando-a-redução-de-instruções-vira-redução-de-ciclos) |
| Cache e memória: sem lugar para os dados, o ganho encolhe (FC L, maxpool L) | `analysis/variants.csv` (`cycles_vs_reference`, `l1d_mpki`, `l2_mpki`, `dram_reads`); [analysis.md](analysis.md#onde-a-memória-limita-o-ganho) |

## Objetivos específicos

| Objetivo (proposta) | O que mostra que foi atingido | Onde |
| --- | --- | --- |
| **1.** Base comparativa de operações de CNN, com referência e versões com instruções personalizadas, e equivalência dos resultados | Sete operações int8 em S e L, cada uma em três variantes (referência, personalizada e RVV). A validação de equivalência passou antes da campanha. Na campanha, as 620 execuções têm `mismatches=0` e o mesmo checksum entre as variantes | [scope.md](scope.md#operações), [kernels.md](kernels.md); `validation.log` da campanha; `runs.csv` (`mismatches`, `checksum_consistent`); [data.md](data.md#o-que-rodou) |
| **2.** Framework no gem5 para variar a hierarquia de memória, coletar métricas e registrar o necessário à reprodução | YAML validado, cenários de memória e CPUs, execução em lote, métricas da região de interesse, proveniência em cada execução. A auditoria da campanha não acusou problemas | [architecture.md](architecture.md), [experiments.md](experiments.md), [scenarios.md](scenarios.md), [campaigns.md](campaigns.md), [results.md](results.md); `campaign audit` ([data.md](data.md#auditoria)) |
| **3.** Quantificar instruções, ciclos e IPC entre referência e personalizada, nas configurações avaliadas | R_I por operação e tamanho; S_C e IPC por CPU e cenário | `analysis/instructions.csv`, `speedup.csv`, `variants.csv`; figuras `variantes_*` e `speedup_*`; [analysis.md](analysis.md#instruções), [analysis.md](analysis.md#ciclos-e-ipc) |
| **4.** Identificar quando menos instruções viram menos ciclos e quando a memória limita o ganho | Eficiência S_C/R_I por CPU e cenário; ciclos relativos ao `l1-l2`; faltas e leituras da DRAM; sensibilidade à latência | `analysis/speedup.csv` (`efficiency`), `variants.csv`, `latency.csv`; figuras `ri_sc_*` e `speedup_L_ref-custom`; [analysis.md](analysis.md#quando-a-redução-de-instruções-vira-redução-de-ciclos), [analysis.md](analysis.md#onde-a-memória-limita-o-ganho), [analysis.md](analysis.md#sensibilidade-à-latência) |
| **5.** Caracterização comparativa, com dados, configurações e documentação para reproduzir | Análise completa, pacote de dados com DOI e licença CC BY 4.0, documentação de instalação e reprodução. Nove combinações foram rodadas de novo e saíram idênticas aos dados publicados | [analysis.md](analysis.md), [data.md](data.md), [installation.md](installation.md), [reproducibility.md](reproducibility.md#reprodução-conferida) |

O contraste `-O2` × `-O3` responde às "otimizações de compilador" do sumário executivo da proposta: `analysis/compiler.csv`, [analysis.md](analysis.md#compilador).

## Hipóteses

Formuladas na RCB-10 e registradas na issue da RCB-25, antes da análise. O veredito e os números estão em [analysis.md](analysis.md#hipóteses).

| Hipótese | Veredito | Evidência |
| --- | --- | --- |
| 1. A maior redução de instruções ocorre em conv, pointwise e FC, e a menor na depthwise | Parcialmente refutada | `analysis/instructions.csv`; `tables.md`, "Instruções da ROI e redução de instruções (R_I)" |
| 2. Na FC L, que excede a L2, o speedup fica bem abaixo da redução de instruções | Confirmada | `analysis/speedup.csv` (FC L, `efficiency`); `analysis/variants.csv` (faltas e leituras da DRAM); figura `ri_sc_L_ref-custom` |
| 3a. Na timing, o speedup acompanha a redução de instruções em S | Confirmada | `analysis/speedup.csv` (timing, S); `tables.md`, "Eficiência S_C/R_I, ref→custom, tamanho S" |
| 3b. Na minor, a latência e a unidade única reduzem o ganho | Refutada com latência 3, confirmada com latência 6; a unidade única não foi isolada | `analysis/latency.csv`; `tables.md`, "Sensibilidade à latência das instruções personalizadas" |
| 3c. Na o3, parte da latência é escondida | Confirmada | `analysis/latency.csv` (o3-edge) |

## Tabelas e figuras para o texto

Sugestões, com a origem de cada uma. As figuras saem prontas do `plot` (PDF vetorial, sem título, legíveis em preto e branco), com a legenda sugerida no `figures.json`. As tabelas devem ser montadas no LaTeX a partir do CSV ou do documento indicado.

| Conteúdo | Tipo | Origem |
| --- | --- | --- |
| Operações, formas e tamanhos S e L, com MACs e bytes | Tabela | [scope.md](scope.md#dimensões); `experiments/<operação>_{s,l}.yaml` |
| Instruções personalizadas: codificação, semântica e operações | Tabela | [custom_instructions.md](custom_instructions.md#resumo) |
| Cenários de memória e o que cabe em cada nível | Tabela | `configs/scenarios.yaml`; [scenarios.md](scenarios.md#o-que-cabe-em-cada-nível) |
| CPUs simuladas (timing, minor, o3-edge) | Tabela | [scenarios.md](scenarios.md#cpus) |
| Matriz de experimentos: grupos, objetivo e execuções | Tabela | `campaigns/final.yaml`; [matrix.md](matrix.md) |
| Arquitetura do framework | Figura (redesenhar) | [architecture.md](architecture.md#visão-geral) |
| R_I por operação e tamanho, custom e RVV | Tabela | `analysis/instructions.csv` |
| S_C ref→custom por CPU e cenário, S e L | Tabela | `analysis/speedup.csv`; `tables.md` |
| Variantes por operação: instruções e ciclos por MAC, IPC (minor, `l1-l2`, S) | Figura | `figures/variantes_S_minor_l1-l2.pdf` ← `report/runs.csv` |
| R_I × S_C com a diagonal, ref→custom e ref→rvv, S e L | Figura | `figures/ri_sc_{S,L}_ref-{custom,rvv}.pdf` ← `report/pairs.csv` |
| S_C ref→custom em L por cenário e CPU (efeito da memória no maxpool e na FC) | Figura | `figures/speedup_L_ref-custom.pdf` ← `report/pairs.csv` |
| Ciclos relativos ao `l1-l2` e faltas por mil instruções | Tabela | `analysis/variants.csv` |
| Latência 3 × 6 | Tabela | `analysis/latency.csv` |
| `-O2` × `-O3` | Tabela | `analysis/compiler.csv` |
| Hipóteses, veredito e evidência | Tabela | [analysis.md](analysis.md#hipóteses) |
| Trade-offs entre custom, RVV, CPU e memória | Tabela | [analysis.md](analysis.md#trade-offs) |
| Reprodução conferida | Tabela | [reproducibility.md](reproducibility.md#reprodução-conferida) |

## Limitações e trabalhos futuros

Ficam separados: uma limitação muda como ler os resultados deste trabalho; um trabalho futuro é uma extensão que ele não cobre.

| Tipo | Onde |
| --- | --- |
| Limitações da análise (modo SE, latências fixas, o3-edge configurada, contorno da RVV na O3, caches aquecidas, ref sem Zbb, MACs nominais, tamanhos reduzidos, sem RTL) | [analysis.md](analysis.md#limitações) |
| Limitações dos dados e da reprodução (imagem não registrada nas campanhas, caminho da pasta, um só host) | [data.md](data.md#limitações), [reproducibility.md](reproducibility.md#limitações) |
| Fora do escopo por decisão (rede completa, treino e acurácia, quantização assimétrica, RTL, área e energia, FS, multinúcleo) | [scope.md](scope.md#fora-do-escopo) |
| Trabalhos futuros, por esforço: só rodar, configuração Python, fork do gem5, kernels | [future.md](future.md) |
