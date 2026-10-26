from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="riscvcnnbench",
    help=(
        "Framework reprodutível de benchmarks CNN quantizados em RISC-V/gem5.\n\n"
        "Fluxo: escreva um experimento YAML (veja docs/experiments.md), confira com "
        "`validate` e execute com `run`. Cada execução cria uma pasta própria "
        "(veja docs/results.md); `runs` lista as existentes, `stats` mostra as "
        "métricas da região de interesse de uma delas e `compare` compara as variantes."
    ),
    epilog=(
        "Exemplos: riscvcnnbench validate experiments/smoke_test.yaml · "
        "riscvcnnbench run experiments/hello_param_cache.yaml · "
        "riscvcnnbench runs results/hello_param_cache · "
        "riscvcnnbench stats results/fc_s/<run_id> · "
        "riscvcnnbench compare results"
    ),
    no_args_is_help=True,
)


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


if __name__ == "__main__":
    app()
