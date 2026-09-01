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
    """Valida a existência de um arquivo de experimento."""
    if not experiment.is_file():
        typer.echo(f"Erro: arquivo não encontrado: {experiment}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Configuração encontrada: {experiment}")


@app.command()
def run(experiment: Path) -> None:
    """Executa um experimento; implementação inicial de teste."""
    if not experiment.is_file():
        typer.echo(f"Erro: arquivo não encontrado: {experiment}", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Execução futura do experimento: {experiment}")


if __name__ == "__main__":
    app()
