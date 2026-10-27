# Matriz de experimentos

`campaigns/final.yaml` é a matriz da campanha final (RCB-22): o que vai ser simulado, por que cada grupo existe e quanto tempo leva. O formato é o da execução em lote ([campaigns.md](campaigns.md)). O escopo de onde ela sai (operações, tamanhos, variantes, CPUs, métricas) está em [scope.md](scope.md), e os cenários de memória e as CPUs, em [scenarios.md](scenarios.md).

| Parte | Situação |
| --- | --- |
| Matriz `campaigns/final.yaml` (620 execuções) e medições `campaigns/medicao.yaml` | Existente |
| `riscvcnnbench campaign estimate` e a tabela `docs/matrix_estimate.csv` | Existente |
| Validação do `-O3` em `make validate` (`tests/test_compiler_validation.py`) | Existente |
| Piloto e estimativa refeita com ele | Planejado (RCB-23) |
| Execução da campanha final | Planejado (RCB-24) |

```bash
uv run riscvcnnbench campaign plan campaigns/final.yaml       # as 620 combinações
make campaign MATRIX=campaigns/final.yaml JOBS=4             # valida e executa (RCB-24)
```

## Grupos

Cada grupo responde a uma pergunta da proposta e diz qual variável isola. A descrição de cada um está também no `description` do grupo, no YAML.

| Grupo | Objetivo | Variável isolada | O que varia | Execuções novas |
| --- | --- | --- | --- | --- |
| `principal` | OE3 (diferenças entre as implementações) e OE4 (quando a redução de instruções vira ciclos e quando a memória limita) | Variante, CPU ou cenário de memória, uma de cada vez | 7 operações × S e L × ref, custom, rvv × timing, minor, o3-edge × 4 cenários | 504 |
| `latencia` | OE4 | Latência das instruções personalizadas (3 e 6) | custom × minor e o3-edge × 4 cenários × 2 latências, nas 7 operações em S e L | 112 |
| `compilador` | Sumário executivo da proposta ("otimizações de compilador") | Flags: `-O2` × `-O3` | conv direta e im2col em S × ref e custom, na minor, `l1-l2` | 4 |
| **Total** | | | | **620** |

### Principal

É um fatorial completo de variante × CPU × cenário, nos dois tamanhos. Assim, cada comparação da proposta muda um fator e mantém os outros fixos, sem precisar de um grupo por fator:

- **Efeito das instruções** (OE3): ref × custom, ref × rvv e custom × rvv na mesma CPU e no mesmo cenário (os pares do `compare`).
- **Quando instruções viram ciclos** (OE4): o mesmo par em timing, minor e o3-edge.
- **Limite da memória** (OE4): o mesmo par nos quatro cenários. Com S, os dados cabem na L1 de 32 KiB e só o `sem-cache` e o `reduzido` pesam. Com L, os três cenários com cache viram três situações diferentes: no `l1`, os dados vêm direto da DRAM; no `l1-l2`, cabem na L2, menos a FC; no `reduzido`, não cabem na L2 ([scenarios.md](scenarios.md#o-que-cabe-em-cada-nível)).

O L também roda no `sem-cache`. No começo, a ideia era deixá-lo de fora por custo. A amostra medida mostrou que ele acrescenta cerca de 1,6 h à campanha com 4 tarefas, e o fatorial completo evita ter de justificar uma exclusão no texto (decisão de 27/10/2026).

O par principal da proposta é ref × custom. A RVV é a comparação com a extensão padrão; ela seria a primeira a ser reduzida se o tempo não coubesse, mas coube, então ela entra em tudo.

### Latência

A latência das instruções personalizadas é uma suposição de projeto ([scenarios.md](scenarios.md)), então é avaliada em dois valores: 3, a mesma de um `mul`, e 6. Ela só muda a variante custom, e só nas CPUs que modelam a latência das unidades funcionais: minor e o3-edge. A ref e a rvv não são repetidas, porque a chave dos pares ignora a latência nelas (`IRRELEVANT`, RCB-17). A latência 3 é a mesma combinação do grupo principal, então só a 6 é nova.

### Compilador

Um contraste mínimo, para mostrar se a otimização do compilador muda a redução de instruções e o speedup. `-O2` continua sendo a base de todos os outros grupos ([scope.md](scope.md#compilação)). As duas operações foram escolhidas pela conferência do `-O3` (abaixo): são as em que o `-O3` mais mudou as instruções da custom, em sentidos opostos. As combinações com `-O2` já estão no grupo principal, então só as quatro com `-O3` são novas.

## Parâmetros fixos

| Parâmetro | Valor | Decisão |
| --- | --- | --- |
| Estado das caches no início da ROI | `warm` (aquecidas, o padrão) | RCB-18: o efeito da memória aparece nos cenários em que os dados não cabem, sem as faltas compulsórias, iguais nas três variantes |
| Repetições `R` | 1 (os argumentos de `experiments/`) | O gem5 é determinístico; repetir só mediria o tempo do host |
| CPU fora de ordem | `o3-edge` (MediumBOOM) | RCB-18: O3 configurada para borda; a `o3` padrão do gem5 fica fora da matriz |
| Latência das instruções personalizadas | 3 (principal) e 6 (latência) | RCB-18 |
| VLEN | 256 | O padrão do gem5 |
| Clock | 1 GHz | O padrão |
| Flags | `-O2`; `-O3` só no grupo compilador | Decisão de 22/10/2026 |
| Verificação | Simulada em todas as CPUs: cada execução confere a própria saída | Decisão de 21/10/2026 ([scope.md](scope.md#estimativa-de-tempo-de-simulação)) |
| Validação antes da campanha | `validate: true`: `pytest -m validation`, incluindo o `-O3` | RCB-15, RCB-18 e RCB-22 |

`tests/test_matrix.py` confere esses valores em todas as 620 combinações resolvidas.

## Estimativa de tempo

| | Execuções | Tempo em série | Fonte |
| --- | --- | --- | --- |
| S | 312 | 1,48 h | 308 medidas (todas as combinações S com `-O2`); as 4 com `-O3` vêm do modelo |
| L | 308 | 9,88 h | 24 medidas (a amostra); 284 do modelo |
| **Total** | **620** | **11,4 h** | **≈ 2,8 h com 4 tarefas**, na ordem do plano |

A maior execução é a conv direta L ref na o3-edge sem cache: 16,1 min, medida. Somando a validação, a campanha cabe numa noite. O `make validate` (e2e mais validação) levou 14 min 32 s em 26/10/2026. Mesmo que o L leve 50% a mais que o estimado, a campanha passa pouco das 4 h.

Por CPU e cenário, em minutos em série (S medido | L estimado):

| CPU | `sem-cache` | `l1` | `l1-l2` | `reduzido` |
| --- | --- | --- | --- | --- |
| timing | 6,1 \| 45,5 | 2,9 \| 12,3 | 2,9 \| 12,2 | 2,9 \| 12,3 |
| minor | 10,5 \| 85,2 | 6,7 \| 41,8 | 8,2 \| 41,9 | 6,8 \| 42,3 |
| o3-edge | 19,0 \| 154,7 | 7,4 \| 47,4 | 7,4 \| 48,3 | 7,6 \| 49,1 |

O `l1-l2` da minor inclui as quatro execuções do grupo compilador. A tabela com cada uma das 620 combinações e o tempo dela está em [matrix_estimate.csv](matrix_estimate.csv).

```bash
uv run riscvcnnbench campaign estimate campaigns/final.yaml \
    -m build/rcb21-probe/conferencia -m build/rcb22-probe/medicao -m build/rcb22-probe/semcache-l \
    --csv docs/matrix_estimate.csv
```

As pastas acima são as medições de 26 e 27/10/2026, em `build/` (ignorado pelo Git). Elas foram rodadas com código ainda não commitado da RCB-21, o que não muda o tempo. Para refazê-las, `campaigns/medicao.yaml` roda as mesmas 381 execuções.

### Como a estimativa é feita

`riscvcnnbench campaign estimate <matriz> -m <pasta> [-m <pasta>...] [-j N] [--csv <arquivo>]` não executa nada. Para cada combinação do plano:

1. **Medida.** Se uma execução concluída nas pastas tem a mesma configuração, a mesma chave da campanha, vale a duração dela, de `started_at` a `finished_at` (build e simulação). Havendo várias, vale a mais recente.
2. **Modelo.** Senão, duração = a + b · W:
   - W são as instruções simuladas do mesmo binário com os mesmos argumentos, somadas nos blocos do `stats.txt` (região de interesse e verificação). Podem vir de qualquer CPU, porque o número de instruções não depende dela.
   - a e b vêm de uma regressão linear sobre as execuções medidas na mesma CPU, clock e cenário.
   - Se W cai fora da faixa medida naquela CPU e cenário, a estimativa conta como extrapolada.
3. **Sem estimativa.** Sem W ou sem regressão, ou seja, com menos de duas execuções de W diferentes, a combinação fica de fora do total, com o motivo.

O tempo com N tarefas simula o pool do `campaign run`: as combinações saem na ordem do plano, cada uma para a primeira tarefa livre. A tabela `--csv` tem as colunas `name`, `groups`, `base`, `variant`, `cpu`, `scenario`, `custom_latency` (só na custom), `flags`, `work` (W), `seconds`, `source` (`medida`, `modelo` ou `sem estimativa`) e `detail` (a pasta medida ou o motivo).

### Medições

`campaigns/medicao.yaml` tem 381 execuções, divididas em quatro grupos. Todas terminaram com resultado válido.

| Grupo | O que mede | Execuções |
| --- | --- | --- |
| `s` | Todo o S da matriz (variantes, CPUs, cenários, as duas latências): a duração real de cada combinação S | 308 |
| `atomic-l` | W de cada binário L, na atomic | 21 |
| `amostra-l` | Velocidade de L: conv direta (a maior) e FC (a que mais depende da memória), ref, nas três CPUs e nos quatro cenários | 24 |
| `compilador` | As sete operações S, ref e custom, `-O2` e `-O3`, na atomic | 28 |

Instruções simuladas em L, em milhões, na ROI e na verificação. A ref soma 248,4 M, como em [scope.md](scope.md#estimativa-de-tempo-de-simulação):

| Operação | ref | custom | rvv |
| --- | --- | --- | --- |
| conv3x3_direct | 77,8 | 49,1 | 49,5 |
| conv3x3_im2col | 76,1 | 47,0 | 45,6 |
| depthwise3x3 | 22,0 | 15,3 | 14,4 |
| pointwise1x1 | 62,0 | 35,7 | 34,9 |
| maxpool2x2 | 1,9 | 1,1 | 1,1 |
| requant_relu | 1,2 | 1,0 | 0,8 |
| fc | 7,4 | 4,1 | 3,9 |

Velocidade das retas ajustadas (1/b), em milhões de instruções simuladas por segundo. Com cache, ela fica perto da que foi medida com um laço simples em 20/10/2026 ([scope.md](scope.md#estimativa-de-tempo-de-simulação)): 0,94 na timing, 0,31 na minor e 0,27 na o3 padrão. Sem cache, cai de 2 a 4 vezes:

| CPU | `sem-cache` | `l1` | `l1-l2` | `reduzido` |
| --- | --- | --- | --- | --- |
| timing | 0,22 | 0,91 | 0,92 | 0,91 |
| minor | 0,15 | 0,31 | 0,31 | 0,31 |
| o3-edge | 0,08 | 0,28 | 0,27 | 0,27 |

### Incerteza

O S está todo medido. Para o L, a reta de cada CPU e cenário passa pelas duas amostras, conv direta (W de 78 M) e FC (W de 7 M), e as outras cinco operações L são interpoladas entre elas.

- Ajustada só com o S, a reta erra o L de forma diferente em cada operação: prevê de 27 a 64% a mais para a conv direta L e até 27% a menos para a FC L.
- Com as amostras no ajuste, o erro nesses pontos some, mas isso não diz quanto ele é nas operações que não foram amostradas.
- Deixando a conv L fora do ajuste, a reta erra a conv L em 40 a 67% para mais.

Por isso, a incerteza do L é bem maior que a do S. A RCB-23 (piloto) mede outras operações L e refaz a estimativa com o mesmo comando.

## Conferência do `-O3`

A issue pede conferir, antes, que as variantes passam com `-O3` e registrar a contagem de instruções. Em 27/10/2026:

- **QEMU:** as sete operações, em S e L, compiladas com `-O3` nas três variantes (custom com o modelo em C), terminaram com `mismatches=0` e o checksum da ref `-O2`: 56 de 56 casos.
- **gem5 atomic:** as sete operações em S, ref e custom com as instruções reais, com `-O2` e `-O3`, passaram e deram o mesmo checksum: 28 de 28.

Instruções da região de interesse, em S, na atomic:

| Operação | ref `-O2` → `-O3` | R_I | custom `-O2` → `-O3` | R_I |
| --- | --- | --- | --- | --- |
| conv3x3_direct | 2.499.690 → 2.480.219 | 1,008 | 719.552 → 670.065 | 1,074 |
| conv3x3_im2col | 2.324.694 → 2.323.414 | 1,001 | 489.465 → 520.953 | 0,940 |
| depthwise3x3 | 975.113 → 970.481 | 1,005 | 160.373 → 153.780 | 1,043 |
| pointwise1x1 | 1.976.613 → 1.976.359 | 1,000 | 305.198 → 304.944 | 1,001 |
| maxpool2x2 | 113.898 → 113.620 | 1,002 | 10.221 → 9.943 | 1,028 |
| requant_relu | 49.182 → 49.182 | 1,000 | 24.603 → 24.603 | 1,000 |
| fc | 115.270 → 115.273 | 1,000 | 12.642 → 12.645 | 1,000 |

Na ref, o `-O3` muda as instruções em menos de 1% em todas as operações. Na custom, muda em quatro. Os ciclos não foram medidos aqui; eles saem do grupo compilador da campanha. A conferência ficou permanente em `tests/test_compiler_validation.py`, que roda com `make validate`:
- no QEMU, as 7 operações em S e L, nas 3 variantes com `-O3`;
- no gem5 atomic, as duas operações do grupo, ref e custom com `-O3`.

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_matrix.py` | As 620 combinações da matriz final (por grupo, nenhuma inválida), os parâmetros fixos em cada uma, grupos com objetivo e variável, e que `medicao.yaml` cobre todo o S da matriz (as 308 com `-O2`) | `make test` |
| `tests/test_estimate.py` | Regressão, simulação do pool, W somado nos blocos, cada origem (medida, a mais recente valendo; modelo extrapolado; sem W; sem reta), tabela CSV e CLI | `make test` |
| `tests/test_compiler_validation.py` | O `-O3` no QEMU e no gem5 atomic (acima) e que as operações do teste são as do grupo compilador | `make validate` |
| `tests/test_campaign_e2e.py` | `campaign estimate` sobre uma campanha real pequena: as concluídas valem pela duração medida, e a que falhou fica sem estimativa | `make e2e-test` |

## Limitações

- A estimativa de L interpola entre duas operações amostradas (veja Incerteza); a do S é a duração de uma execução só, que varia com a carga do host.
- O tempo com 4 tarefas supõe que as simulações em paralelo não se atrasam umas às outras. As medições já rodaram com 4 tarefas no mesmo host, então isso já está incluído, mas outra carga no host muda o resultado.
- O modelo não sabe de mudanças no código que mudem W; com outro código, é preciso medir de novo.
- A matriz não tem caches frias (`cold`), VLEN diferente de 256, a O3 padrão do gem5 nem a CPU atomic: são opções do framework fora da campanha.
