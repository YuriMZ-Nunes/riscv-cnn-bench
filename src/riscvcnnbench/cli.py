from pathlib import Path

import typer

app = typer.Typer(
    name="riscvcnnbench",
    help="Framework reprodutível de benchmarks CNN quantizados em RISC-V/gem5.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Exibe a versão instalada do framework."""
    from riscvcnnbench import __version__

    typer.echo(f"riscv-cnn-bench {__version__}")


@app.command()
def validate(experiment: Path) -> None:
    """Valida um arquivo de experimento e mostra a configuração resultante."""
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
def run(experiment: Path) -> None:
    """Executa um experimento; por enquanto apenas valida o arquivo."""
    from riscvcnnbench.config import ConfigError, load_experiment

    try:
        load_experiment(experiment)
    except ConfigError as error:
        typer.echo(f"Erro: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"Execução futura do experimento: {experiment}")


if __name__ == "__main__":
    app()
