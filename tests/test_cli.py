from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench.cli import app

SMOKE = Path(__file__).resolve().parents[1] / "experiments" / "smoke_test.yaml"


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "riscv-cnn-bench" in result.stdout


def test_help_lists_main_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("validate", "run", "runs", "stats", "version"):
        assert command in result.stdout
    assert "docs/experiments.md" in result.stdout


def test_run_help_explains_exit_code() -> None:
    result = CliRunner().invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "programa simulado" in result.stdout
    assert "--gem5" in result.stdout


def test_run_without_gem5(tmp_path: Path) -> None:
    missing = tmp_path / "gem5.opt"

    result = CliRunner().invoke(app, ["run", str(SMOKE), "--gem5", str(missing)])

    assert result.exit_code == 1
    assert result.stderr == (
        f"Erro: gem5 não encontrado em {missing}. Compile com `make gem5-build` "
        "ou indique outro executável com --gem5.\n"
    )


def test_run_without_toolchain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gem5 = tmp_path / "gem5.opt"
    gem5.touch()
    monkeypatch.setenv("RISCV_PREFIX", "inexistente-")

    result = CliRunner().invoke(app, ["run", str(SMOKE), "--gem5", str(gem5)])

    assert result.exit_code == 1
    assert result.stderr == (
        "Erro: inexistente-gcc não encontrado. Execute dentro do container: "
        "`make run EXPERIMENT=<yaml>` ou `make shell`.\n"
    )
