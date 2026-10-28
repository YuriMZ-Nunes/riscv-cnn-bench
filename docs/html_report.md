# Relatório de resultados em HTML

Uma página para ler os resultados de uma pasta sem abrir CSVs: visão geral, resultados com filtros e o gráfico de speedup, **comparação entre configurações escolhidas** e as tabelas do `analyze` (RCB-35). A página é gerada a partir do `report/` da pasta e abre no navegador, sem servidor nem internet.

| Parte | Situação |
| --- | --- |
| `riscvcnnbench relatorio` e `make relatorio` (`src/riscvcnnbench/report_page.py`, `src/riscvcnnbench/web/relatorio.*`) | Existente |
| Testes do JavaScript da página com o QuickJS | Existente (`tests/test_report_page.py`) |

## Gerar e abrir

```bash
make report DIR=results/campaigns/final      # runs.csv e pairs.csv, se ainda não existem
make analyze DIR=results/campaigns/final     # opcional: as tabelas da análise entram na página
make relatorio DIR=results/campaigns/final   # grava results/campaigns/final/relatorio.html
xdg-open results/campaigns/final/relatorio.html
```

Dentro do container: `uv run riscvcnnbench relatorio [pasta] [--input <report>] [-o <arquivo.html>] [--force]`. A pasta padrão é `results/`. A página lê `<pasta>/report/runs.csv` e `pairs.csv` e, se existir, `<pasta>/analysis/tables.md`. Sem `--force` (`FORCE=1` no `make`), o comando recusa sobrescrever uma página que já existe. Gere a página de novo depois de um `report` novo: ela não se atualiza sozinha.

Para comparar YAMLs que você escreveu, grave os dois com o mesmo `output.dir`, por exemplo `results/meus/a` e `results/meus/b`. Depois rode `make report DIR=results/meus` e `make relatorio DIR=results/meus`.

## O que a página mostra

1. **Visão geral.** Execuções, válidas, na análise e pares; operações, tamanhos, CPUs, cenários e séries presentes; por que execuções ficaram fora da análise; a lista das que têm problema.
2. **Filtros.** Operação, tamanho, CPU, cenário (com os ajustes das caches) e série (variante com latência, unidades ou VLEN). Valem para os resultados e para a comparação.
3. **Resultados.**
   - **Gráfico:** speedup em ciclos (S_C) do par escolhido (ref→custom, ref→rvv, custom→rvv e os outros do `pairs.csv`), um painel por CPU, um grupo por operação e tamanho e uma barra por cenário. O eixo é logarítmico, e as barras partem de 1× (sem ganho). O traço tracejado de cada grupo é a redução de instruções (R_I): uma barra acima dele quer dizer que o par ganhou mais em ciclos que em instruções (eficiência acima de 1, [analysis.md](analysis.md)). Passar o mouse numa barra mostra S_C, R_I e eficiência.
   - **Tabela:** uma linha por execução, com instruções, ciclos, IPC, instruções e ciclos por MAC (ou elemento) e faltas por mil instruções. Clicar no título de uma coluna numérica ordena por ela.
4. **Comparar configurações.**
   - Uma configuração é tudo o que não é operação, tamanho nem variante: CPU, cenário de memória (com os ajustes das caches e caches frias), flags, conjunto de dados e clock.
   - Marque duas ou mais configurações, escolha a base pelo círculo e a métrica.
   - Para cada operação, tamanho e série, a tabela mostra o valor em cada configuração e a razão sobre a base, em verde quando a configuração ganha e em vermelho quando perde (o número sempre aparece). Para ciclos, instruções e faltas, menor é melhor; para o IPC, maior.
   - A última linha é a média geométrica das razões.
5. **Análise.** As tabelas do `analyze` ([analysis.md](analysis.md#reproduzir)), quando a pasta as tem.

## Seleção e números

- **Seleção:** a análise usa as mesmas execuções e pares do `plot` e do `analyze`, ou seja, válidas, valendo (`current`), com checksum consistente e com ciclos. As outras aparecem só na visão geral, com o motivo.
- **Formato dos números:** como nas tabelas do `analyze`, com vírgula decimal e ponto nos milhares.
- **Rastreio:** o hash SHA-256 dos CSVs de entrada fica nos dados embutidos na página.
- **Cores:** as dos cenários seguem a paleta categórica validada (oito cores, com modo claro e escuro). Cada cenário mantém a cor quando um filtro tira os outros. Além do oitavo cenário, as barras ficam cinza.

## Testes

| Teste | Confere | Comando |
| --- | --- | --- |
| `tests/test_report_page.py` | Com CSVs sintéticos e o `relatorio.js` no QuickJS: os dados embutidos (série, cenário, motivo da exclusão); a formatação; o resumo e os filtros; a ordenação; as configurações; a comparação, com as razões e a média geométrica conferidas a mão; o gráfico, com a cor do cenário estável sob filtro; as tabelas do `analyze` convertidas em HTML, sem passar HTML do texto adiante; a página gravada; o `--force`; e a CLI | `make test` |
| `tests/test_campaign_e2e.py` | O relatório da campanha real pequena, com todas as execuções do `runs.csv` e as tabelas do `analyze` | `make e2e-test` |

## Limitações

- **Só lê o que o `report` gerou:** sem `report/`, não há página. Depois de novas execuções, rode `report` (e `analyze`) e `relatorio` de novo.
- **Uma métrica por vez na comparação**, e uma execução por configuração, operação e série. Se houver repetidas, vale a última lida, e a página avisa.
- **O gráfico mostra só o S_C.** Os gráficos de variantes e de R_I × S_C continuam no `plot` ([plots.md](plots.md)).
- **Página grande:** com centenas de execuções, a página tem algumas centenas de KB, por causa dos dados embutidos. A campanha final dá cerca de 0,7 MB.
