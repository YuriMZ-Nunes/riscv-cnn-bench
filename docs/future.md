# Trabalhos futuros

O que ficou fora do TCC e pode ser estendido (RCB-34). Para cada item, a tabela diz o que muda, por que ficou de fora e o que exigiria. As limitações da análise que motivam vários deles estão em [analysis.md](analysis.md#limitações), e o escopo, em [scope.md](scope.md#fora-do-escopo).

| Parte | Situação |
| --- | --- |
| Esta lista | Existente, 27/10/2026. É registro: nenhum item abaixo está implementado ou foi medido |

O esforço de cada item cai num destes níveis, do menor para o maior:

| Nível | O que envolve |
| --- | --- |
| **Rodar** | O framework já permite; falta uma campanha ([campaigns.md](campaigns.md)), que o `campaign estimate` dimensiona e o `analyze` resume |
| **Configuração Python** | Campos novos no YAML e argumentos em `configs/gem5/se_riscv_configurable.py`, sem recompilar o gem5, como na RCB-32 e na RCB-33. Valores iguais ao padrão saem da configuração resolvida, para não mudar a chave das execuções existentes |
| **Fork do gem5** | Mudança no fork (`YuriMZ-Nunes/gem5`, branch `riscv-cnn-bench`), `make gem5-build` e novo ponteiro do submódulo. O executável novo tem outro hash, e as campanhas antigas aparecem como desatualizadas no `campaign status`. Os dados publicados continuam reproduzíveis pelo commit `ce03244` do fork ([data.md](data.md)) |
| **Kernels** | Benchmarks ou variantes novas em `benchmarks/`, com oráculo e validação de equivalência ([kernels.md](kernels.md)) |

## Experimentos que só falta rodar

| Experimento | Campos | Por que ficou de fora | O que responderia |
| --- | --- | --- | --- |
| Prefetcher na FC L e no maxpool L | `cache.<nível>.prefetcher` (RCB-32), com as caches do `l1-l2` escritas à mão | O campo veio depois da campanha final; a campanha opcional de sensibilidade da RCB-32 não foi rodada | Se um prefetcher tira o limite de memória que a análise viu nessas operações ([analysis.md](analysis.md#onde-a-memória-limita-o-ganho)) |
| Unidades e pipeline nos kernels | `cpu.custom_units`, `cpu.custom_pipelined` (RCB-33) | Os campos vieram depois da campanha final | A parte da hipótese 3 que ficou sem isolar: o efeito de ter uma só unidade ([analysis.md](analysis.md#hipóteses)). Hoje só há a medição do `insn_latency` ([scenarios.md](scenarios.md#unidades-e-pipeline)) |
| Caches frias | `benchmark.cache_state: cold` | A matriz fixou caches aquecidas para caber no tempo (RCB-22); o efeito só foi medido como ilustração na FC S ([scenarios.md](scenarios.md#estado-das-caches-no-início-da-roi)) | Quanto do ganho depende de os dados já estarem nas caches |
| VLEN de 128, 512 e 1024 bits | `cpu.vlen` | A matriz fixou 256, o padrão do gem5 | Se a RVV ganha ou perde da custom com vetores mais curtos ou mais longos |
| O3 padrão do gem5 | `cpu.model: o3` | A matriz usa a `o3-edge`, mais próxima de um núcleo de borda ([scenarios.md](scenarios.md#o3-de-borda-o3-edge)) | Quanto da latência e do ganho uma CPU fora de ordem larga esconderia |
| Caches de outros tamanhos e latências | `cache.*` (RCB-32), pelo gerador ([generator.md](generator.md)) | A matriz usou os quatro cenários nomeados | Onde o ganho de cada operação passa a ser limitado pela memória |
| Contraste de compilador amplo | `compiler.flags`, como `-O3` ou `-funroll-loops` | O contraste da campanha é mínimo: duas operações, uma CPU, um cenário ([analysis.md](analysis.md#compilador)) | Se o compilador muda o ganho das instruções em todas as operações e CPUs |
| Outros tamanhos de operação | `benchmark.args` | Dois tamanhos por operação (S e L), escolhidos pelo que cabe nas caches ([scope.md](scope.md#dimensões)) | A curva do ganho com o tamanho. Os argumentos precisam respeitar as restrições de cada kernel, como `Cin` múltiplo de 8 na custom |

## Configurações que exigem só a configuração Python

| Item | O que muda | Por que ficou de fora | O que exigiria |
| --- | --- | --- | --- |
| Memória principal | Outros tipos de DRAM, mais típicos de borda, e mais canais e ranks | A DRAM ficou fixa em DDR4-2400 com 1 canal ([scenarios.md](scenarios.md#parâmetros-fixos)) | Ampliar `memory.type` com interfaces que o gem5 já tem (entre elas `LPDDR5_*`, `DDR5_*` e `HBM_*`, em `src/mem/DRAMInterface.py`); para vários canais, um controlador por canal e a intercalação dos endereços |
| Unidade vetorial | Quantidade e latência das unidades das classes `Simd*` usadas pela RVV | As latências são as padrões do gem5. Isso é a limitação "classes de unidade diferentes" da comparação custom × RVV ([analysis.md](analysis.md#limitações)) | Campos como `cpu.vector_units` e uma latência, aplicados ao `SIMD_Unit` da O3 e ao `MinorDefaultFloatSimdFU` da Minor, como a RCB-33 fez com `CnnMult` |
| Microarquitetura da CPU | Larguras, ROB, filas de instruções e de cargas, preditor de desvios | O foco do TCC são instruções e memória; a `o3-edge` foi fixada na RCB-18 | Expor os parâmetros de `O3_EDGE` e da Minor como campos; o preditor por um campo que escolha entre os do gem5 (`LocalBP`, `TournamentBP`, `BiModeBP`, `GshareBP` e outros) |
| Hierarquia de caches | Uma L3, outra política de substituição, outra inclusão | Núcleo de borda sem L3; LRU e `mostly_incl` são os padrões do gem5 | Um nível `cache.l3` com o barramento dele; `cache.<nível>.replacement` com as políticas do gem5 (`LRURP`, `RandomRP`, `BRRIPRP` e outras); `cache.<nível>.clusivity` (`mostly_incl` ou `mostly_excl`) |

## Mudanças no fork do gem5

| Item | O que muda | Por que ficou de fora | O que exigiria |
| --- | --- | --- | --- |
| Latência do `cnn.max8` | Hoje o `cnn.max8` é da classe `IntAlu`, junto com somas e comparações; não dá para mudar a latência só dele | Decisão da RCB-33: recompilar e trocar o executável do gem5 custaria mais do que o ganho, porque o `cnn.max8` só aparece no maxpool, limitado pela memória em L | Uma classe própria (por exemplo, `CnnAlu`) no `decoder.isa`, no `op_class.hh` e no `FuncUnit.py` do fork, registrada nas unidades da O3 e da Minor; `make gem5-build` (cerca de 19 min); um campo `cpu.max8_latency`; conferir que os ciclos padrão não mudam |
| Latência própria do `cnn.rqnt` | As três instruções de `CnnMult` têm a mesma latência ([scenarios.md](scenarios.md#limitações)) | Uma latência para a classe bastou para a sensibilidade da campanha | Outra classe no fork para o `cnn.rqnt[.relu]`, como no item anterior |
| Reduções RVV sem contorno | A RVV reduz em LMUL 1 e soma o valor inicial no escalar, por causa de um defeito da O3CPU com registradores fixados ([kernels.md](kernels.md#limitação-do-gem5-reduções-rvv-na-o3cpu)) | O contorno no kernel resolveu a validação sem mexer no simulador | Corrigir a dependência no fork (ou adotar um gem5 em que esteja corrigida) e voltar as reduções da RVV para LMUL maior, validando nas três CPUs |

## Kernels e quantização

| Item | O que muda | Por que ficou de fora | O que exigiria |
| --- | --- | --- | --- |
| Quantização assimétrica e por canal | Ponto zero nas ativações e nos pesos, e multiplicador e deslocamento por canal de saída | Um esquema único, int8 simétrico por tensor, mantém as variantes comparáveis ([scope.md](scope.md#quantização)) | Novos oráculos e kernels nas três variantes; com ponto zero, um termo de correção nos produtos ou uma instrução nova; por canal, carregar o multiplicador de cada saída para o `cnn.rqnt` |
| Outros tipos | int4, int16, ponto flutuante | Fora do escopo ([scope.md](scope.md#fora-do-escopo)) | Kernels e, para a custom, instruções novas no fork |
| Rede completa | Uma CNN pequena de ponta a ponta, com pesos e entradas reais | A avaliação é por operação (decisão de 17/10/2026) | Compor as operações num benchmark, com dados de um modelo treinado e quantizado, e medir a rede inteira e cada camada |
| Referência e compiladores | Referência com Zbb, outro compilador (como o LLVM) e a autovetorização como quarta variante | A referência usa `rv64gc` sem Zbb, e a RVV usa intrínsecos, para o código ser controlado ([scope.md](scope.md#compilação)) | Variante ou flags novas em `kernel.mk` e a validação de equivalência delas |

## Escopo e validação física

| Item | O que muda | Por que ficou de fora | O que exigiria |
| --- | --- | --- | --- |
| Vários núcleos | Kernels paralelos e coerência de caches | Um núcleo isola o efeito de instruções e memória | Kernels paralelos, uma configuração com várias CPUs e as caches coerentes, e métricas por núcleo |
| Modo full-system | Sistema operacional, interrupções e memória virtual de verdade | O modo SE isola o kernel ([analysis.md](analysis.md#limitações)) | Uma configuração FS para RISC-V (o gem5 traz exemplos em `configs/example/gem5_library/`, como `riscvmatched-fs.py`), uma imagem de kernel e de disco com os benchmarks, e adaptar o wrapper |
| RTL, área e energia | O custo de hardware das instruções e da unidade vetorial | O gem5 dá desempenho arquitetural; a validação física ficou fora (proposta, seção 3) | Implementar as instruções num núcleo RISC-V em RTL aberto, sintetizar para área e frequência, e estimar energia; comparar com a RVV na mesma base |

## Melhorias do framework

| Item | O que muda | Por que ficou de fora | O que exigiria |
| --- | --- | --- | --- |
| Estimativa de tempo em operações limitadas pela memória | O modelo a + b · W errou a FC L da custom e da RVV em 1,4 a 3,5 vezes, porque o tempo do host não segue as instruções ([matrix.md](matrix.md#campanha-final-previsto--medido)) | O total da campanha acertou | Um termo para o tráfego de memória (faltas ou leituras da DRAM) no modelo do `estimate.py` |
| Caminho da pasta da execução | O comprimento do caminho muda os ciclos em cerca de 0,04% ([pilot.md](pilot.md#determinismo)) | Achado na RCB-32, depois da campanha | Rodar o binário de um caminho de comprimento fixo (por exemplo, um link curto) dentro do wrapper |
| Gerador | Várias associatividades, vários grupos e dimensões livres na página ([generator.md](generator.md#limitações)) | A página cobre o caso comum | Ampliar o `gerador.js`, com as restrições de cada kernel nos dados da página |
