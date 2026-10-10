from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench.cli import app
from riscvcnnbench.config import PROJECT_ROOT, ConfigError, load_experiment

EXAMPLES = [
    "experiments/smoke_test.yaml",
    "experiments/hello_param_minimal.yaml",
    "experiments/hello_param_cache.yaml",
]


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "experiment.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("example", EXAMPLES)
def test_examples_are_valid(example: str) -> None:
    load_experiment(PROJECT_ROOT / example)


def test_minimal_uses_defaults(tmp_path: Path) -> None:
    config = load_experiment(write(tmp_path, "name: m\nbenchmark:\n  name: hello_riscv\n"))

    assert config.compiler.flags == ["-O2"]
    assert config.cpu.model == "atomic"
    assert config.cpu.clock == "1GHz"
    assert config.cache.l1i is None and config.cache.l1d is None and config.cache.l2 is None
    assert config.memory.type == "simple"
    assert config.memory.size == "512MiB"
    assert config.results_dir == Path("results/m")
    assert config.gem5_args() == [
        "--cpu=atomic",
        "--clock=1GHz",
        "--mem-type=simple",
        "--mem-size=512MiB",
    ]


def test_cache_example_gem5_args() -> None:
    config = load_experiment(PROJECT_ROOT / "experiments/hello_param_cache.yaml")

    assert config.gem5_args() == [
        "--arg=65536",
        "--arg=2",
        "--cpu=timing",
        "--clock=2GHz",
        "--l1i-size=32KiB",
        "--l1i-assoc=4",
        "--l1d-size=32KiB",
        "--l1d-assoc=4",
        "--l2-size=256KiB",
        "--l2-assoc=8",
        "--mem-type=ddr4",
        "--mem-size=512MiB",
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("name: x\nbenchmark: {name: hello_riscv}\ncahce: {}\n", "cahce"),
        ("name: x\nbenchmark: {name: hello_riscv}\ncpu: {model: pentium}\n", "cpu.model"),
        ("name: x\nbenchmark: {name: hello_riscv}\ncpu: {clock: 2}\n", "cpu.clock"),
        ("name: x\nbenchmark: {name: hello_riscv}\ncache: {l1d: {size: 32KB}}\n", "cache.l1d.size"),
        ("name: x\nbenchmark: {name: hello_riscv}\ncache: {l2: {size: 1MiB}}\n", "l2 requer"),
        ("name: x\nbenchmark: {name: nao_existe}\n", "benchmark não encontrado"),
        ("name: com espaço\nbenchmark: {name: hello_riscv}\n", "name"),
        ("benchmark: {name: hello_riscv}\n", "name"),
        ("", "mapeamento YAML"),
        ("name: [\n", "YAML inválido"),
    ],
)
def test_invalid_configs(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_experiment(write(tmp_path, text))


def test_cli_validate() -> None:
    runner = CliRunner()

    ok = runner.invoke(app, ["validate", str(PROJECT_ROOT / "experiments/hello_param_cache.yaml")])
    assert ok.exit_code == 0
    assert "Configuração válida" in ok.stdout
    assert "l2=256KiB/8-way" in ok.stdout

    missing = runner.invoke(app, ["validate", "nao_existe.yaml"])
    assert missing.exit_code == 1
