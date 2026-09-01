from typer.testing import CliRunner

from riscvcnnbench.cli import app


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "riscv-cnn-bench" in result.stdout
