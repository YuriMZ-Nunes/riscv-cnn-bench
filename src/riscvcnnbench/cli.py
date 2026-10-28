from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer

if TYPE_CHECKING:
    from riscvcnnbench.campaign import Plan

app = typer.Typer(
    name="riscvcnnbench",
    help=(
        "Framework reprodutível de benchmarks CNN quantizados em RISC-V/gem5.\n\n"
        "Fluxo: escreva um experimento YAML (veja docs/experiments.md), confira com "
        "`validate` e execute com `run`. Cada execução cria uma pasta própria "
        "(veja docs/results.md); `runs` lista as existentes, `stats` mostra as "
        "métricas da região de interesse de uma delas, `compare` compara as variantes, "
        "`report` exporta tudo em CSV, `plot` gera os gráficos e `analyze` as tabelas da "
        "análise a partir dos CSVs. "
        "`campaign` executa uma matriz de experimentos em lote (veja docs/campaigns.md)."
    ),
    epilog=(
        "Exemplos: riscvcnnbench validate experiments/smoke_test.yaml · "
        "riscvcnnbench run experiments/hello_param_cache.yaml · "
        "riscvcnnbench runs results/hello_param_cache · "
        "riscvcnnbench stats results/fc_s/<run_id> · "
        "riscvcnnbench compare results · "
        "riscvcnnbench campaign run campaigns/exemplo.yaml"
    ),
    no_args_is_help=True,
)
campaign_app = typer.Typer(
    help=(
        "Executa em lote uma matriz de experimentos (campaigns/*.yaml): `plan` mostra as "
        "combinações, `estimate` estima o tempo a partir de execuções medidas, `run` executa "
        "e retoma, `status` mostra o estado, `audit` confere se vale como resultado e "
        "`package` empacota para publicação. Veja docs/campaigns.md e docs/data.md."
    ),
    no_args_is_help=True,
)
app.add_typer(campaign_app, name="campaign")


@app.command()
def version() -> None:
    """Exibe a versão instalada do framework."""
    from riscvcnnbench import __version__

    typer.echo(f"riscv-cnn-bench {__version__}")


@app.command()
def validate(
    experiment: Annotated[Path, typer.Argument(help="Arquivo YAML do experimento.")],
) -> None:
    """Valida um experimento e mostra a configuração com os padrões aplicados.

    Não compila nem executa nada. Erros saem com a linha do YAML e uma sugestão.
    """
    from riscvcnnbench.config import ConfigError, load_experiment

    try:
        config = load_experiment(experiment)
    except ConfigError as error:
        typer.echo(f"Erro: {error}", err=True)
        raise typer.Exit(code=1) from error

    cache = config.cache
    levels = [
        f"{level}={getattr(cache, level).size}/{getattr(cache, level).assoc}-way"
        for level in ("l1i", "l1d", "l2")
        if getattr(cache, level)
    ]
    typer.echo(f"Configuração válida: {experiment}")
    typer.echo(f"  experimento: {config.name}")
    typer.echo(f"  benchmark:   {config.benchmark.name} {' '.join(config.benchmark.args)}".rstrip())
    typer.echo(f"  flags:       {' '.join(config.compiler.flags)}")
    typer.echo(f"  cpu:         {config.cpu.model} @ {config.cpu.clock}")
    typer.echo(f"  cache:       {', '.join(levels) or 'nenhuma'}")
    typer.echo(f"  memória:     {config.memory.type}, {config.memory.size}")
    typer.echo(f"  saída:       {config.results_dir}")


@app.command()
def run(
    experiment: Annotated[Path, typer.Argument(help="Arquivo YAML do experimento.")],
    gem5: Annotated[
        Path | None,
        typer.Option(help="Executável do gem5. Padrão: $GEM5_BIN ou o build do submódulo."),
    ] = None,
) -> None:
    """Compila o benchmark e executa o experimento no gem5, em uma pasta nova.

    Ao final mostra a pasta, o status e um resumo das métricas da região de
    interesse (detalhes com `stats`); em caso de falha, explica a causa e aponta
    o log. O código de saída é 0 só quando o gem5 e o programa simulado retornam 0.
    """
    from riscvcnnbench.config import ConfigError
    from riscvcnnbench.parser import StatsError
    from riscvcnnbench.runner import RunError, execute, prepare_run
    from riscvcnnbench.runs import diagnose, display, load_run, region_stats, summary

    try:
        prepared = prepare_run(experiment, gem5)
    except (ConfigError, RunError) as error:
        typer.echo(f"Erro: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"Executando {prepared.experiment.name} em {display(prepared.run_dir)}")
    code = execute(prepared)

    if not (prepared.run_dir / "metadata.json").is_file():
        # O wrapper recusou os argumentos antes de criar a pasta.
        typer.echo(f"Erro: a execução não foi criada (código {code}).", err=True)
        raise typer.Exit(code=code or 1)

    result = load_run(prepared.run_dir)
    typer.echo(f"Pasta:  {display(prepared.run_dir)}")
    typer.echo(f"Status: {result.metadata['status']}")
    problem = diagnose(result)
    if problem:
        typer.echo(f"Erro: {problem.message}", err=True)
    else:
        try:
            typer.echo(f"Métricas: {summary(region_stats(result))}")
        except StatsError as error:
            typer.echo(f"Aviso: {error}", err=True)
    raise typer.Exit(code=code)


@app.command()
def runs(
    root: Annotated[
        Path,
        typer.Argument(help="Pasta onde procurar execuções, como results/ ou results/<name>/."),
    ] = Path("results"),
) -> None:
    """Lista as execuções existentes, das mais antigas para as mais recentes.

    Para cada uma mostra experimento, benchmark, CPU, status (com a causa, se
    falhou) e, se concluída, instruções, ciclos e IPC da região de interesse.
    """
    from riscvcnnbench.runs import diagnose, display, list_runs, metric_cells

    if not root.is_dir():
        typer.echo(f"Erro: pasta não encontrada: {root}", err=True)
        raise typer.Exit(code=1)

    found = list_runs(root)
    if not found:
        typer.echo(f"Nenhuma execução em {root}.")
        return

    rows = []
    for item in found:
        problem = diagnose(item)
        status = item.metadata.get("status") or "?"
        rows.append(
            [
                item.metadata.get("run_id") or item.path.name,
                item.experiment,
                item.benchmark,
                item.cpu,
                f"{status} ({problem.kind})" if problem else status,
                *metric_cells(item),
                display(item.path),
            ]
        )
    header = [
        "RUN_ID",
        "EXPERIMENTO",
        "BENCHMARK",
        "CPU",
        "STATUS",
        "INSTS",
        "CICLOS",
        "IPC",
        "PASTA",
    ]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header) - 1)]
    for row in [header, *rows]:
        cells = [cell.ljust(width) for cell, width in zip(row, widths, strict=False)]
        typer.echo("  ".join([*cells, row[-1]]))
    typer.echo(
        f"\n{len(rows)} execução(ões). INSTS, CICLOS e IPC são da região de interesse "
        "(ou do programa inteiro, sem ROI); `riscvcnnbench stats <pasta>` mostra todas as "
        "métricas. Detalhes de cada campo em docs/results.md."
    )


@app.command()
def stats(
    run_dir: Annotated[
        Path, typer.Argument(help="Pasta de uma execução, como results/<name>/<run_id>.")
    ],
    as_json: Annotated[
        bool, typer.Option("--json", help="Imprime em JSON, para uso em scripts.")
    ] = False,
) -> None:
    """Mostra as métricas da região de interesse (ROI) de uma execução.

    Lê gem5/stats.txt e a linha RESULT do stdout.log sem alterá-los; nos
    benchmarks sem ROI, mostra o programa inteiro. Inclui as métricas derivadas
    (CPI, faltas por mil instruções, por repetição e por MAC). Métricas que não se
    aplicam (cache não configurada, ciclos na CPU atomic) aparecem como ausentes,
    com o motivo. Veja docs/results.md#métricas.
    """
    import json

    from riscvcnnbench.metric import BASE_DESCRIPTIONS, BASE_UNITS, DERIVED, load_metrics, unit_for
    from riscvcnnbench.parser import METRICS, StatsError
    from riscvcnnbench.runs import display, load_run

    if not (run_dir / "metadata.json").is_file():
        typer.echo(f"Erro: {run_dir} não é uma pasta de execução (falta metadata.json).", err=True)
        raise typer.Exit(code=1)
    run = load_run(run_dir)
    try:
        measured = load_metrics(run)
    except StatsError as error:
        typer.echo(f"Erro: {error}", err=True)
        raise typer.Exit(code=1) from error
    region = measured.stats

    status = run.metadata.get("status")
    if status != "completed":
        typer.echo(
            f"Aviso: a execução não foi concluída (status {status}); as métricas não valem "
            "como resultado.",
            err=True,
        )

    if as_json:
        document = {
            "run_id": run.metadata.get("run_id"),
            "path": display(run.path),
            "status": status,
            "experiment": run.experiment,
            "benchmark": run.benchmark,
            "variant": (run.resolved.get("benchmark") or {}).get("variant"),
            "cpu": region.cpu,
            "region": region.region,
            "blocks": region.blocks,
            "metrics": region.metrics,
            "missing": region.missing,
            "result": measured.result.fields if measured.result else None,
            "work_unit": measured.work_unit,
            "derived": measured.derived,
            "derived_missing": measured.missing,
        }
        typer.echo(json.dumps(document, indent=2, ensure_ascii=False))
        return

    where = "ROI, bloco 1 de 2" if region.region == "roi" else "programa inteiro, bloco único"
    result = measured.result
    typer.echo(f"Execução:  {display(run.path)}")
    typer.echo(f"Benchmark: {run.benchmark}, CPU {region.cpu or '?'}, status {status}")
    typer.echo(f"Região:    {where}")
    typer.echo(
        f"Resultado: {' '.join(f'{k}={v}' for k, v in result.fields.items()) if result else '-'}"
    )

    rows = [(metric.group, metric.key, metric.unit, metric.stat) for metric in METRICS]
    values, missing = dict(region.metrics), dict(region.missing)
    rows += [("Derivadas", key, unit, BASE_DESCRIPTIONS[key]) for key, unit in BASE_UNITS.items()]
    rows += [("Derivadas", ratio.key, ratio.unit, ratio.formula) for ratio in DERIVED]
    values.update(measured.derived)
    missing.update(measured.missing)
    width = max(len(row[1]) for row in rows)
    unit_width = max(len(unit_for(row[2], measured.work_unit)) for row in rows)
    group = None
    for row_group, key, unit, source in rows:
        if row_group != group:
            group = row_group
            typer.echo(f"\n{group}")
        value = values[key]
        if value is None:
            text, source = "ausente", f"{source} ({missing[key]})"
        else:
            text = f"{value:.6g}" if isinstance(value, float) else str(value)
        unit = unit_for(unit, measured.work_unit)
        typer.echo(f"  {key:<{width}}  {text:>12}  {unit:<{unit_width}}  {source}")


@app.command()
def compare(
    root: Annotated[
        Path,
        typer.Argument(help="Pasta onde procurar execuções, como results/ ou uma campanha."),
    ] = Path("results"),
    as_json: Annotated[
        bool, typer.Option("--json", help="Imprime em JSON, para uso em scripts.")
    ] = False,
) -> None:
    """Compara as execuções aos pares: variantes no mesmo cenário e -O2 × outras -O.

    Pares de variantes: ref × custom, ref × rvv e custom × rvv, com a mesma operação,
    parâmetros, dados, flags, CPU, caches, memória e gem5. Mostra a redução de
    instruções (R_I), o speedup em ciclos (S_C) e a razão de IPC, com S_C = R_I ×
    IPC_b/IPC_a. Pares com checksum diferente são rejeitados; execuções que falharam
    ou calcularam errado ficam de fora, com o motivo. Veja docs/results.md.
    """
    import json

    from riscvcnnbench.metric import PAIR_RATIOS, collect, parameters_label, scenario_label
    from riscvcnnbench.metric import compare as compare_runs
    from riscvcnnbench.runs import display

    if not root.is_dir():
        typer.echo(f"Erro: pasta não encontrada: {root}", err=True)
        raise typer.Exit(code=1)

    items, excluded = collect(root)
    comparison = compare_runs(items, excluded)
    accepted = [pair for pair in comparison.pairs if not pair.problem]
    rejected = [pair for pair in comparison.pairs if pair.problem]

    if as_json:
        document = {
            "pairs": [
                {
                    "kind": pair.kind,
                    "label": pair.label,
                    "a": display(pair.a.run.path),
                    "b": display(pair.b.run.path),
                    "scenario": pair.a.scenario(),
                    "values": pair.values,
                    "missing": pair.missing,
                    "problem": pair.problem,
                }
                for pair in comparison.pairs
            ],
            "excluded": [
                {"path": display(path), "reason": reason} for path, reason in comparison.excluded
            ],
            "superseded": [display(path) for path in comparison.superseded],
        }
        typer.echo(json.dumps(document, indent=2, ensure_ascii=False))
        return

    if accepted:
        header = ["OPERAÇÃO", "PARÂMETROS", "CPU", "CENÁRIO", "PAR"]
        header += [ratio.key.upper() for ratio in PAIR_RATIOS]
        rows = [header]
        for pair in accepted:
            values = [pair.values[ratio.key] for ratio in PAIR_RATIOS]
            rows.append(
                [
                    pair.a.result.bench if pair.a.result else "?",
                    parameters_label(pair.a),
                    pair.a.run.cpu,
                    scenario_label(pair.a.run.resolved),
                    pair.label,
                    *("-" if value is None else f"{value:.3f}" for value in values),
                ]
            )
        widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
        for row in rows:
            typer.echo(
                "  ".join(
                    cell.ljust(width) for cell, width in zip(row, widths, strict=True)
                ).rstrip()
            )
    typer.echo(
        f"\n{len(accepted)} par(es) aceito(s), {len(rejected)} rejeitado(s). R_I = instruções "
        "de a ÷ de b; S_C = ciclos de a ÷ de b; IPC_RATIO = IPC de b ÷ de a, e S_C = R_I × "
        "IPC_RATIO. Detalhes em docs/results.md."
    )
    if rejected:
        typer.echo("\nPares rejeitados:")
        for pair in rejected:
            typer.echo(f"  {display(pair.a.run.path)} × {display(pair.b.run.path)}: {pair.problem}")
    if comparison.excluded:
        typer.echo("\nFora da comparação:")
        for path, reason in comparison.excluded:
            typer.echo(f"  {display(path)}: {reason}")
    if comparison.superseded:
        typer.echo("\nRepetidas, substituídas pela execução mais recente:")
        for path in comparison.superseded:
            typer.echo(f"  {display(path)}")


@app.command()
def report(
    root: Annotated[
        Path,
        typer.Argument(help="Pasta com as execuções, como results/ ou uma campanha."),
    ] = Path("results"),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Pasta dos CSVs. Padrão: <pasta>/report/."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Regrava runs.csv e pairs.csv se já existirem.")
    ] = False,
) -> None:
    """Exporta as execuções em CSV: runs.csv (uma linha por execução) e pairs.csv.

    runs.csv traz identificação, configuração, linha RESULT, métricas brutas e
    derivadas da região de interesse e proveniência; pairs.csv, os pares do
    `compare`. Nada é descartado: falhas, resultados inválidos, checksums
    diferentes e execuções substituídas ficam marcados. Valor ausente é célula
    vazia. Colunas em docs/report.md.
    """
    from riscvcnnbench.report import ReportError, write_report
    from riscvcnnbench.runs import display

    if not root.is_dir():
        _fail(f"pasta não encontrada: {root}")
    try:
        written = write_report(root, output, force)
    except ReportError as error:
        _fail(str(error))
    typer.echo(f"Gravado em {display(written.output)}:")
    typer.echo(
        f"  runs.csv: {written.runs} execução(ões), {written.valid} válida(s), "
        f"{written.current} valendo (current), {written.inconsistent} com checksum divergente"
    )
    typer.echo(f"  pairs.csv: {written.pairs} par(es), {written.rejected} rejeitado(s)")


@app.command()
def plot(
    root: Annotated[
        Path,
        typer.Argument(help="Pasta com o report, como results/ ou uma campanha."),
    ] = Path("results"),
    source: Annotated[
        Path | None,
        typer.Option("--input", help="Pasta com runs.csv e pairs.csv. Padrão: <pasta>/report/."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Pasta das figuras. Padrão: <pasta>/figures/."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Regrava as figuras se já existirem.")
    ] = False,
) -> None:
    """Gera os gráficos de comparação (PDF e PNG) a partir dos CSVs do `report`.

    Três tipos: instruções e ciclos por MAC e IPC por operação e variante; speedup
    em ciclos por cenário de memória e CPU; R_I contra S_C com a diagonal. Entram
    só execuções e pares válidos, com ciclos. Os CSVs usados são copiados para a
    pasta das figuras, com figures.json (contexto, execuções e legenda sugerida de
    cada figura). Veja docs/plots.md.
    """
    from riscvcnnbench.plot import PlotError, write_plots
    from riscvcnnbench.runs import display

    source = source or root / "report"
    try:
        written = write_plots(source, output or root / "figures", force)
    except PlotError as error:
        _fail(str(error))
    kinds = written.kinds
    typer.echo(f"Gravado em {display(written.output)} (PDF e PNG):")
    typer.echo(
        f"  {kinds['variantes']} de variantes, {kinds['speedup']} de speedup, "
        f"{kinds['ri_sc']} de R_I × S_C"
    )
    for name, used, skipped in (
        ("runs.csv", f"{written.used_runs} execução(ões) usada(s)", written.skipped_runs),
        ("pairs.csv", f"{written.used_pairs} par(es) usado(s)", written.skipped_pairs),
    ):
        reasons = ", ".join(f"{count} {reason}" for reason, count in skipped.most_common())
        typer.echo(f"  {name}: {used}" + (f"; fora: {reasons}" if reasons else ""))
    if written.repeated:
        typer.echo(f"  {written.repeated} ponto(s) repetido(s): vale o mais recente")
    typer.echo("  figures.json: contexto, execuções e legenda sugerida de cada figura")


@app.command()
def analyze(
    root: Annotated[
        Path,
        typer.Argument(help="Pasta com o report, como uma campanha."),
    ] = Path("results"),
    source: Annotated[
        Path | None,
        typer.Option("--input", help="Pasta com runs.csv e pairs.csv. Padrão: <pasta>/report/."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Pasta das tabelas. Padrão: <pasta>/analysis/."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Regrava as tabelas se já existirem.")
    ] = False,
) -> None:
    """Gera as tabelas da análise a partir dos CSVs do `report`.

    Instruções e R_I; speedup em ciclos e eficiência S_C/R_I por CPU e cenário;
    IPC, ciclos relativos ao l1-l2 e faltas de cache; sensibilidade à latência das
    instruções personalizadas; -O2 × -O3. Entram só execuções e pares válidos, com
    ciclos, como no `plot`. Grava um CSV por tabela, tables.md e analysis.json.
    Veja docs/analysis.md.
    """
    from riscvcnnbench.analysis import AnalysisError, write_analysis
    from riscvcnnbench.plot import PlotError
    from riscvcnnbench.runs import display

    target = output or root / "analysis"
    try:
        tables = write_analysis(source or root / "report", target, force)
    except (AnalysisError, PlotError) as error:
        _fail(str(error))
    typer.echo(f"Gravado em {display(target)}:")
    for table in tables:
        typer.echo(f"  {table.name}.csv: {len(table.rows)} linha(s)")
    typer.echo("  tables.md: as tabelas em Markdown; analysis.json: hash das entradas")


@app.command()
def relatorio(
    root: Annotated[
        Path,
        typer.Argument(help="Pasta com o report, como uma campanha ou results/."),
    ] = Path("results"),
    source: Annotated[
        Path | None,
        typer.Option("--input", help="Pasta com runs.csv e pairs.csv. Padrão: <pasta>/report/."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Arquivo HTML. Padrão: <pasta>/relatorio.html."),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Regrava a página se já existir.")] = False,
) -> None:
    """Grava um relatório HTML dos resultados, para abrir no navegador.

    Visão geral, resultados com filtros e o gráfico de speedup, comparação entre
    configurações escolhidas (CPU, cenário, flags, dados) com a razão sobre uma
    base, e as tabelas do `analyze` (se a pasta tiver analysis/). Lê os CSVs do
    `report`, com a seleção do `plot`; não precisa de servidor nem de internet.
    Veja docs/html_report.md.
    """
    from riscvcnnbench.plot import PlotError
    from riscvcnnbench.report_page import DEFAULT_NAME, ReportPageError, write_page
    from riscvcnnbench.runs import display

    target = output or root / DEFAULT_NAME
    try:
        data = write_page(source or root / "report", target, root / "analysis", force)
    except (ReportPageError, PlotError) as error:
        _fail(str(error))
    used = sum(1 for run in data["runs"] if not run["skip"])
    typer.echo(f"Relatório gravado em {display(target)}")
    typer.echo(
        f"  {len(data['runs'])} execução(ões), {used} na análise; {len(data['pairs'])} par(es)"
    )
    typer.echo(f"  tabelas do analyze: {'incluídas' if data['analysis'] else 'ausentes'}")
    typer.echo("Abra no navegador (fora do container), por exemplo: xdg-open " + str(target))


@app.command()
def gerador(
    output: Annotated[Path, typer.Option("--output", "-o", help="Arquivo HTML a gravar.")] = Path(
        "build/gerador.html"
    ),
    measured: Annotated[
        list[Path] | None,
        typer.Option(
            "--measured",
            "-m",
            help="Pasta com execuções medidas, para estimar o tempo (repita para várias).",
        ),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Regrava a página se já existir.")] = False,
) -> None:
    """Grava uma página HTML para montar experimentos e campanhas sem escrever YAML.

    Abra o arquivo no navegador (não precisa de servidor nem de internet): escolha
    operação, tamanho, variantes, CPUs, memória e flags, e a página mostra o YAML,
    o número de simulações, onde ficam os dados e o comando para rodar. As opções
    vêm do código do projeto. Com --measured, estima o tempo pelo modelo do
    `campaign estimate`. Veja docs/generator.md.
    """
    from riscvcnnbench.generator import GeneratorError, write_page
    from riscvcnnbench.runs import display

    try:
        data = write_page(output, measured, force)
    except GeneratorError as error:
        _fail(str(error))
    typer.echo(f"Página gravada em {display(output)}")
    typer.echo(f"  {len(data['ops'])} operação(ões), {len(data['scenarios']) - 1} cenário(s)")
    estimate = data["estimate"]
    if estimate:
        typer.echo(
            f"  estimativa de tempo a partir de {estimate['samples']} execução(ões) medida(s), "
            f"{len(estimate['fits'])} reta(s) por CPU e cenário"
        )
    elif measured:
        typer.echo("  sem estimativa: nenhuma execução medida nas pastas dadas")
    typer.echo("Abra no navegador (fora do container), por exemplo: xdg-open " + str(output))


MatrixArg = Annotated[Path, typer.Argument(help="Matriz da campanha (campaigns/<nome>.yaml).")]
OutputOption = Annotated[
    Path | None,
    typer.Option("--output", help="Pasta da campanha. Padrão: results/campaigns/<name>."),
]


def _fail(message: str) -> NoReturn:
    typer.echo(f"Erro: {message}", err=True)
    raise typer.Exit(code=1)


def _plan_or_exit(target: Path, output: Path | None) -> "Plan":
    from riscvcnnbench.campaign import CampaignError, load_plan_from
    from riscvcnnbench.config import ConfigError

    try:
        return load_plan_from(target, output.resolve() if output else None)
    except (ConfigError, CampaignError) as error:
        _fail(str(error))


@campaign_app.command("plan")
def campaign_plan(
    matrix: MatrixArg,
    output: OutputOption = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Imprime o plano em JSON, para uso em scripts.")
    ] = False,
) -> None:
    """Mostra as combinações da matriz, sem executar nada.

    Lista as execuções únicas, as repetidas (iguais a outra depois de ignorar os
    campos que não afetam a variante ou a CPU) e as inválidas, com o motivo.
    """
    import json
    import math

    from riscvcnnbench.runs import display

    plan = _plan_or_exit(matrix, output)
    if as_json:
        typer.echo(json.dumps(plan.document(), indent=2, ensure_ascii=False))
        return

    typer.echo(f"Campanha {plan.campaign.name}: {len(plan.runs)} execução(ões) únicas")
    typer.echo(f"Pasta: {display(plan.root)}")
    for group in plan.campaign.groups:
        size = len(group.experiments) * math.prod(len(v) for v in group.vary.values())
        first = sum(1 for run in plan.runs if run.groups[0] == group.name)
        typer.echo(f"  grupo {group.name}: {size} combinação(ões), {first} nova(s)")
    if plan.runs:
        typer.echo("")
        rows = [["NOME", "GRUPOS"]] + [[run.name, ",".join(run.groups)] for run in plan.runs]
        width = max(len(row[0]) for row in rows)
        for name, groups in rows:
            typer.echo(f"{name.ljust(width)}  {groups}")
    if plan.duplicates:
        typer.echo(
            f"\n{len(plan.duplicates)} combinação(ões) repetida(s), iguais a outra depois de "
            "ignorar os campos que não as afetam (rodam uma vez)."
        )
    if plan.invalid:
        typer.echo(f"\n{len(plan.invalid)} combinação(ões) inválida(s), que não serão executadas:")
        for item in plan.invalid:
            values = ", ".join(f"{k}={v}" for k, v in item["values"].items())
            typer.echo(f"  {item['base']} [{item['group']}] {values}:")
            for problem in item["problems"]:
                typer.echo(f"    {problem}")


@campaign_app.command("run")
def campaign_run(
    matrix: MatrixArg,
    jobs: Annotated[
        int | None,
        typer.Option("--jobs", "-j", min=1, help="Simulações em paralelo. Padrão: número de CPUs."),
    ] = None,
    validate_first: Annotated[
        bool,
        typer.Option("--validate", help="Roda pytest -m validation antes (como validate: true)."),
    ] = False,
    update: Annotated[
        bool, typer.Option("--update", help="Aceita uma matriz diferente da já usada na pasta.")
    ] = False,
    gem5: Annotated[
        Path | None,
        typer.Option(help="Executável do gem5. Padrão: $GEM5_BIN ou o build do submódulo."),
    ] = None,
    output: OutputOption = None,
) -> None:
    """Executa a campanha, ou continua uma interrompida, sem refazer o que já terminou.

    Cada combinação roda como um `riscvcnnbench run`, com a própria pasta em
    <campanha>/runs/<nome>/. Pula as já concluídas com o mesmo gem5 e refaz as que
    falharam, foram interrompidas ou nunca rodaram. Uma falha não para as outras.
    Saída 0 se todas estão concluídas, 1 se alguma falhou e 130 se interrompida.
    """
    import os

    from riscvcnnbench.campaign import CampaignError, run_campaign
    from riscvcnnbench.config import ConfigError
    from riscvcnnbench.runner import RunError, default_gem5

    gem5_path = (gem5 or default_gem5()).resolve()
    workers = jobs or os.cpu_count() or 1
    try:
        outcome = run_campaign(
            matrix,
            gem5_path,
            workers,
            typer.echo,
            output=output.resolve() if output else None,
            validate=validate_first,
            update=update,
        )
    except (ConfigError, CampaignError, RunError) as error:
        _fail(str(error))

    target = output or matrix
    if outcome.interrupted:
        typer.echo(
            f"\nInterrompida. Retome com o mesmo comando; o estado está em "
            f"`riscvcnnbench campaign status {target}`.",
            err=True,
        )
        raise typer.Exit(code=130)
    done = len(outcome.executed) - len(outcome.failed)
    typer.echo(
        f"\nSessão: {outcome.skipped} já concluída(s), {len(outcome.executed)} executada(s), "
        f"{done} concluída(s), {len(outcome.failed)} com problema."
    )
    flagged = [state for state in outcome.executed if state.provenance()]
    if flagged:
        typer.echo(
            f"Aviso: {len(flagged)} concluída(s) nesta sessão com a árvore suja ou outro "
            f"executável do gem5; elas não valem como resultado. Veja `riscvcnnbench campaign "
            f"status {target}`.",
            err=True,
        )
    if outcome.failed:
        typer.echo(
            f"Veja as causas em `riscvcnnbench campaign status {target}`; rodar de novo refaz "
            "só as que não terminaram.",
            err=True,
        )
        raise typer.Exit(code=1)


@campaign_app.command("status")
def campaign_status(
    target: Annotated[
        Path, typer.Argument(help="Matriz da campanha (.yaml) ou a pasta da campanha.")
    ],
    gem5: Annotated[
        Path | None,
        typer.Option(help="gem5 de referência para 'concluída'. Padrão: o de `campaign run`."),
    ] = None,
    output: OutputOption = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Imprime em JSON, para uso em scripts.")
    ] = False,
) -> None:
    """Mostra o estado de cada combinação da campanha, com o diagnóstico das falhas.

    O estado vem das pastas das execuções: concluída (com este gem5), falhou,
    interrompida, incompleta, desatualizada (concluída com outro gem5) ou pendente.
    Para as concluídas, instruções, ciclos e IPC da região de interesse, e quais
    não valem como resultado: árvore suja (project.dirty ou gem5_repository.dirty)
    ou executável do gem5 diferente do build registrado (matches_executable false).
    """
    import json

    from riscvcnnbench.campaign import count_by, file_sha256, states
    from riscvcnnbench.runner import default_gem5
    from riscvcnnbench.runs import diagnose, display

    plan = _plan_or_exit(target, output)
    found = states(plan, file_sha256((gem5 or default_gem5()).resolve()))

    if as_json:
        document = []
        for state in found:
            problem = diagnose(state.run) if state.run and not state.done else None
            insts, cycles, ipc = state.cells()
            document.append(
                {
                    "name": state.planned.name,
                    "groups": state.planned.groups,
                    "status": state.status,
                    "diagnosis": problem.kind if problem else None,
                    "message": problem.message if problem else None,
                    "run": display(state.run.path) if state.run else None,
                    "attempts": state.attempts,
                    "insts": insts,
                    "cycles": cycles,
                    "ipc": ipc,
                    "provenance": state.provenance(),
                }
            )
        typer.echo(json.dumps(document, indent=2, ensure_ascii=False))
        return

    typer.echo(f"Campanha {plan.campaign.name} em {display(plan.root)}")
    header = ["NOME", "STATUS", "INSTS", "CICLOS", "IPC", "TENTATIVAS"]
    rows = [header] + [
        [state.planned.name, state.label(), *state.cells(), str(state.attempts)] for state in found
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    for row in rows:
        typer.echo("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip())
    counts = count_by(state.status for state in found)
    summary = ", ".join(f"{status}: {count}" for status, count in counts.items())
    typer.echo(f"\n{len(found)} combinação(ões): {summary}.")
    problems = [state for state in found if state.run and not state.done]
    if problems:
        typer.echo("\nSem conclusão:")
        for state in problems:
            problem = diagnose(state.run) if state.run else None
            reason = problem.message if problem else "concluída com outro executável do gem5"
            typer.echo(f"  {state.planned.name}: {reason} ({display(state.run.path)})")
    flagged = [
        (state.planned.name, state.provenance(), state.run.path)
        for state in found
        if state.run and state.provenance()
    ]
    if flagged:
        typer.echo(f"\nConcluídas que não valem como resultado: {len(flagged)}")
        for name, problems, path in flagged:
            typer.echo(f"  {name}: {', '.join(problems)} ({display(path)})")
        typer.echo(
            "Para refazer com a árvore limpa: riscvcnnbench run "
            f"{display(plan.root)}/experiments/<nome>.yaml (a mais recente passa a valer)."
        )


def _hours(seconds: float) -> str:
    return f"{seconds / 3600:.2f} h" if seconds >= 3600 else f"{seconds / 60:.1f} min"


@campaign_app.command("estimate")
def campaign_estimate(
    target: Annotated[
        Path, typer.Argument(help="Matriz da campanha (.yaml) ou a pasta da campanha.")
    ],
    measured: Annotated[
        list[Path],
        typer.Option(
            "--measured",
            "-m",
            help="Pasta com execuções medidas (repita para várias): results/, uma campanha...",
        ),
    ],
    jobs: Annotated[
        int, typer.Option("--jobs", "-j", min=1, help="Tarefas em paralelo na estimativa.")
    ] = 4,
    table: Annotated[
        Path | None,
        typer.Option("--csv", help="Grava a tabela das combinações, com o tempo de cada uma."),
    ] = None,
    output: OutputOption = None,
) -> None:
    """Estima o tempo da campanha a partir de execuções já medidas, sem executar nada.

    Cada combinação usa a duração de uma execução medida com a mesma configuração
    ou, sem ela, a + b · W: W são as instruções simuladas do mesmo binário (em
    qualquer CPU) e a, b vêm de uma regressão sobre as execuções medidas na mesma
    CPU e cenário. O total com N tarefas simula a ordem de `campaign run`. Veja
    docs/matrix.md.
    """
    from riscvcnnbench.estimate import MEASURED, MISSING, MODEL, estimate, write_csv
    from riscvcnnbench.metric import scenario_label
    from riscvcnnbench.runs import display

    for root in measured:
        if not root.is_dir():
            _fail(f"pasta não encontrada: {root}")
    plan = _plan_or_exit(target, output)
    source = target / "campaign.yaml" if target.is_dir() else target
    result = estimate(plan, source, measured, jobs)
    if table:
        write_csv(table, result)

    typer.echo(
        f"Campanha {plan.campaign.name}: {len(plan.runs)} combinação(ões); estimativa a partir "
        f"de {result.samples} execução(ões) medida(s) em {len(measured)} pasta(s)"
    )
    extrapolated = sum(1 for item in result.estimates if item.extrapolated)
    typer.echo(
        f"  {MEASURED}: {result.count(MEASURED)}, {MODEL}: {result.count(MODEL)} "
        f"({extrapolated} fora da faixa de W medida), {MISSING}: {result.count(MISSING)}"
    )

    cells: dict[tuple[str, str], list[float]] = {}
    for item in result.estimates:
        if item.resolved:
            key = (item.resolved["cpu"]["model"], scenario_label(item.resolved))
            cells.setdefault(key, []).append(item.seconds or 0.0)
    rows = [["CPU", "CENÁRIO", "COMBINAÇÕES", "EM SÉRIE"]] + [
        [cpu, scenario, str(len(values)), _hours(sum(values))]
        for (cpu, scenario), values in cells.items()
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    typer.echo("")
    for row in rows:
        typer.echo("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip())

    typer.echo("\nPor grupo (onde a combinação aparece primeiro):")
    for group in plan.campaign.groups:
        mine = [item for item in result.estimates if item.groups[0] == group.name]
        total = sum(item.seconds or 0.0 for item in mine)
        typer.echo(f"  {group.name}: {len(mine)} combinação(ões), {_hours(total)} em série")

    typer.echo(
        f"\nTotal: {_hours(result.serial)} em série; com {jobs} tarefa(s), "
        f"≈ {_hours(result.makespan)} na ordem do plano"
    )
    longest = result.longest
    if longest is not None and longest.seconds is not None:
        typer.echo(
            f"Maior combinação: {longest.name}, ≈ {_hours(longest.seconds)} ({longest.source})"
        )
    missing = [item for item in result.estimates if item.source == MISSING]
    if missing:
        typer.echo(f"\nSem estimativa (fora do total): {len(missing)}")
        for item in missing:
            typer.echo(f"  {item.name}: {item.detail}")
    if table:
        typer.echo(f"\nTabela gravada em {display(table)}")


@campaign_app.command("audit")
def campaign_audit(
    target: Annotated[Path, typer.Argument(help="Pasta da campanha.")],
) -> None:
    """Confere se a campanha vale como resultado, sem executar nada.

    Todas as combinações concluídas e válidas (RESULT com mismatches=0), com
    project.dirty e gem5_repository.dirty falsos, gem5_build.matches_executable
    verdadeiro e um só commit do projeto. Validação de equivalência, report e
    figuras ausentes e execuções a mais aparecem como observações. Saída 0 sem
    problemas, 1 com. Veja docs/data.md.
    """
    from riscvcnnbench.campaign import CampaignError
    from riscvcnnbench.config import ConfigError
    from riscvcnnbench.package import audit

    if not target.is_dir():
        _fail(f"pasta não encontrada: {target}")
    try:
        found = audit(target)
    except (ConfigError, CampaignError) as error:
        _fail(str(error))
    typer.echo(f"Campanha {found.name}: {found.done} de {found.combinations} concluída(s)")
    commits = ", ".join(f"{str(c)[:7]} ({n})" for c, n in found.project_commits.items())
    gem5 = ", ".join(f"{str(c)[:7]} ({n})" for c, n in found.gem5_commits.items())
    typer.echo(f"  commit do projeto: {commits or '-'}; do fork do gem5: {gem5 or '-'}")
    typer.echo(f"  de {found.first_started or '-'} a {found.last_finished or '-'}")
    if found.validation:
        typer.echo(
            f"  validação: aprovada em {found.validation.get('finished_at')} "
            f"(commit {str(found.validation.get('project_commit'))[:7]})"
        )
    for note in found.notes:
        typer.echo(f"  observação: {note}")
    if found.problems:
        typer.echo(f"\n{len(found.problems)} problema(s):")
        for problem in found.problems:
            typer.echo(f"  {problem}")
        raise typer.Exit(code=1)
    typer.echo("\nSem problemas.")


@campaign_app.command("package")
def campaign_package(
    targets: Annotated[list[Path], typer.Argument(help="Pastas das campanhas.")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Arquivo .tar.gz a gravar.")],
    name: Annotated[
        str | None,
        typer.Option(help="Pasta raiz dentro do pacote. Padrão: o nome do arquivo sem .tar.gz."),
    ] = None,
    allow_problems: Annotated[
        bool,
        typer.Option(
            "--allow-problems", help="Empacota mesmo com problemas (ficam no README e MANIFEST)."
        ),
    ] = False,
) -> None:
    """Junta campanhas num .tar.gz para publicação.

    O pacote tem README.md, LICENSE.txt (CC BY 4.0), MANIFEST.json (commits,
    contagens, validação, observações), SHA256SUMS e as pastas das campanhas
    inteiras em campanhas/. Antes, faz a auditoria de `campaign audit` e recusa
    se ela achar problemas. Veja docs/data.md.
    """
    from riscvcnnbench.campaign import CampaignError, project_state
    from riscvcnnbench.config import ConfigError
    from riscvcnnbench.package import package
    from riscvcnnbench.runs import display

    for target in targets:
        if not target.is_dir():
            _fail(f"pasta não encontrada: {target}")
    root = name or output.name.removesuffix(".tar.gz").removesuffix(".tgz")
    try:
        audits = package(targets, output, root, allow_problems, project_state())
    except (ConfigError, CampaignError) as error:
        _fail(str(error))
    for item in audits:
        typer.echo(f"  {item.name}: {item.done} de {item.combinations} concluída(s)")
        for note in [*item.notes, *item.problems]:
            typer.echo(f"    {note}")
    size = output.stat().st_size / 1e6
    typer.echo(f"Pacote gravado em {display(output)} ({size:.1f} MB), pasta raiz {root}/")


if __name__ == "__main__":
    app()
