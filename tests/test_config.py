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


def test_full_config_is_loaded(tmp_path: Path) -> None:
    config = load_experiment(
        write(
            tmp_path,
            """\
name: completo
description: todos os campos
benchmark:
  name: hello_riscv_param
  args: [4096, "2"]
compiler:
  flags: ["-O3"]
cpu:
  model: o3
  clock: 2.5GHz
cache:
  l1i: {size: 16KiB}
  l1d: {size: 32KiB, assoc: 8}
  l2: {size: 1MiB, assoc: 16}
memory:
  type: ddr4
  size: 1GiB
output:
  dir: results/outro
""",
        )
    )

    assert config.name == "completo"
    assert config.description == "todos os campos"
    assert config.benchmark.args == ["4096", "2"]
    assert config.compiler.flags == ["-O3"]
    assert (config.cpu.model, config.cpu.clock) == ("o3", "2.5GHz")
    assert config.cache.l1i is not None and config.cache.l1i.assoc == 4
    assert config.cache.l1d is not None and config.cache.l1d.assoc == 8
    assert config.cache.l2 is not None and config.cache.l2.size == "1MiB"
    assert (config.memory.type, config.memory.size) == ("ddr4", "1GiB")
    assert config.results_dir == Path("results/outro")


VALID_START = "name: x\nbenchmark:\n  name: hello_riscv\n"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "benchmark:\n  name: hello_riscv\n",
            "name: campo obrigatório ausente",
        ),
        (
            "name: x\n",
            "benchmark: campo obrigatório ausente",
        ),
        (
            "name: x\nbenchmark:\n  args: [1]\n",
            "linha 2: benchmark.name: campo obrigatório ausente",
        ),
        (
            "name: meu experimento\nbenchmark:\n  name: hello_riscv\n",
            "linha 1: name: valor 'meu experimento' inválido; use apenas letras, números, _ e -",
        ),
        (
            VALID_START + "cahce: {}\n",
            "linha 4: cahce: campo desconhecido; você quis dizer 'cache'?",
        ),
        (
            VALID_START + "cpu:\n  modle: o3\n",
            "linha 5: cpu.modle: campo desconhecido; você quis dizer 'model'?",
        ),
        (
            VALID_START + "xyz: 1\n",
            "linha 4: xyz: campo desconhecido; campos válidos aqui: benchmark, cache,",
        ),
        (
            VALID_START + "cpu:\n  model: pentium\n",
            "linha 5: cpu.model: valor 'pentium' inválido; use 'atomic', 'timing', 'minor' ou 'o3'",
        ),
        (
            VALID_START + "cpu:\n  clock: 2\n",
            "linha 5: cpu.clock: deve ser texto, mas recebeu 2; use uma frequência como 800MHz",
        ),
        (
            VALID_START + "cpu:\n  clock: 2 GHz\n",
            "linha 5: cpu.clock: valor '2 GHz' inválido; use uma frequência como 800MHz",
        ),
        (
            VALID_START + "cache:\n  l1d:\n    size: 32KB\n",
            "linha 6: cache.l1d.size: valor '32KB' inválido; use um tamanho como 32KiB",
        ),
        (
            VALID_START + "cache:\n  l1d:\n    size: 32KiB\n    assoc: 0\n",
            "linha 7: cache.l1d.assoc: deve ser no mínimo 1, mas recebeu 0",
        ),
        (
            VALID_START + "cache:\n  l2:\n    size: 1MiB\n",
            "linha 4: cache: cache.l2 requer cache.l1i e cache.l1d",
        ),
        (
            VALID_START + "cpu: o3\n",
            "linha 4: cpu: deve conter subcampos (um mapeamento YAML), mas recebeu 'o3'",
        ),
        (
            "name: x\nbenchmark:\n  name: hello_riscv\n  args: 4096\n",
            "linha 4: benchmark.args: deve ser uma lista",
        ),
        (
            "name: x\nbenchmark:\n  name: nao_existe\n",
            "linha 3: benchmark.name: benchmark 'nao_existe' não encontrado em benchmarks/; "
            "disponíveis: hello_riscv, hello_riscv_param",
        ),
        (
            VALID_START + "cpu:\n  model: o3\ncpu:\n  model: timing\n",
            "linha 6: cpu: campo repetido; só o último valor seria usado",
        ),
        ("", "arquivo vazio"),
        ("- name: x\n", "deve ser um mapeamento de campos"),
        (
            VALID_START + "cpu:\n  model: o3\n   clock: 1GHz\n",
            "linha 6, coluna 9: YAML inválido",
        ),
    ],
)
def test_invalid_config_message(tmp_path: Path, text: str, expected: str) -> None:
    with pytest.raises(ConfigError) as error:
        load_experiment(write(tmp_path, text))

    assert expected in str(error.value)


def test_all_problems_reported_in_line_order(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "name: a b\nbenchmark:\n  name: hello_riscv\ncpu:\n  model: x\nmemory:\n  size: 1\n",
    )

    with pytest.raises(ConfigError) as error:
        load_experiment(path)

    problems = error.value.problems
    assert [problem.split(":")[0] for problem in problems] == ["linha 1", "linha 5", "linha 7"]
    assert str(error.value).startswith(f"{path} tem 3 problemas:")


def test_missing_file() -> None:
    with pytest.raises(ConfigError, match="arquivo não encontrado"):
        load_experiment(Path("nao_existe.yaml"))


def test_cli_validate() -> None:
    runner = CliRunner()

    ok = runner.invoke(app, ["validate", str(PROJECT_ROOT / "experiments/hello_param_cache.yaml")])
    assert ok.exit_code == 0
    assert "Configuração válida" in ok.stdout
    assert "l2=256KiB/8-way" in ok.stdout

    missing = runner.invoke(app, ["validate", "nao_existe.yaml"])
    assert missing.exit_code == 1
    assert "arquivo não encontrado" in missing.stderr


def test_cli_run_rejects_invalid_config(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["run", str(write(tmp_path, "name: x\n"))])

    assert result.exit_code == 1
    assert "benchmark: campo obrigatório ausente" in result.stderr
