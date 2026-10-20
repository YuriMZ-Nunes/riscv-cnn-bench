from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="riscvcnnbench",
    help=(
        "Framework reprodutível de benchmarks CNN quantizados em RISC-V/gem5.\n\n"
        "Fluxo: escreva um experimento YAML (veja docs/experiments.md), confira com "
        "`validate` e execute com `run`. Cada execução cria uma pasta própria "
        "(veja docs/results.md); `runs` lista as existentes."
    ),
    epilog=(
        "Exemplos: riscvcnnbench validate experiments/smoke_test.yaml · "
        "riscvcnnbench run experiments/hello_param_cache.yaml · "
        "riscvcnnbench runs results/hello_param_cache"
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

    Ao final mostra a pasta e o status; em caso de falha, explica a causa e aponta
    o log. O código de saída é 0 só quando o gem5 e o programa simulado retornam 0.
    """
    from riscvcnnbench.config import ConfigError
    from riscvcnnbench.runner import RunError, execute, prepare_run
    from riscvcnnbench.runs import diagnose, display, load_run

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
    raise typer.Exit(code=code)


@app.command()
def runs(
    root: Annotated[
        Path,
        typer.Argument(help="Pasta onde procurar execuções, como results/ ou results/<name>/."),
    ] = Path("results"),
) -> None:
    """Lista as execuções existentes, das mais antigas para as mais recentes.

    Para cada uma mostra experimento, benchmark, CPU, status e, se falhou, a causa.
    """
    from riscvcnnbench.runs import diagnose, display, list_runs

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
                display(item.path),
            ]
        )
    header = ["RUN_ID", "EXPERIMENTO", "BENCHMARK", "CPU", "STATUS", "PASTA"]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header) - 1)]
    for row in [header, *rows]:
        cells = [cell.ljust(width) for cell, width in zip(row, widths, strict=False)]
        typer.echo("  ".join([*cells, row[-1]]))
    typer.echo(f"\n{len(rows)} execução(ões). Detalhes de cada campo em docs/results.md.")


if __name__ == "__main__":
    app()
