import json
from pathlib import Path

from riscvcnnbench.config import PROJECT_ROOT, load_experiment
from riscvcnnbench.runner import (
    GEM5_CONFIG,
    build_command,
    resolved_config,
    results_dir,
    wrapper_command,
)


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "experiment.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_resolved_config_fills_defaults(tmp_path: Path) -> None:
    experiment = load_experiment(write(tmp_path, "name: x\nbenchmark:\n  name: hello_riscv\n"))

    assert resolved_config(experiment) == {
        "name": "x",
        "description": "",
        "benchmark": {"name": "hello_riscv", "args": []},
        "compiler": {"flags": ["-O2"]},
        "cpu": {"model": "atomic", "clock": "1GHz"},
        "cache": {"l1i": None, "l1d": None, "l2": None},
        "memory": {"type": "simple", "size": "512MiB"},
        "output": {"dir": str(PROJECT_ROOT / "results" / "x")},
    }


def test_results_dir_keeps_absolute_path(tmp_path: Path) -> None:
    experiment = load_experiment(
        write(
            tmp_path,
            f"name: x\nbenchmark:\n  name: hello_riscv\noutput:\n  dir: {tmp_path / 'out'}\n",
        )
    )

    assert results_dir(experiment) == tmp_path / "out"


def test_build_command_uses_experiment_flags(tmp_path: Path) -> None:
    experiment = load_experiment(
        write(
            tmp_path,
            "name: x\nbenchmark:\n  name: hello_riscv_param\n"
            'compiler:\n  flags: ["-O3", "-funroll-loops"]\n',
        )
    )
    binary = tmp_path / "inputs" / "hello_riscv_param"

    assert build_command(experiment, binary) == [
        "make",
        "-C",
        str(PROJECT_ROOT / "benchmarks" / "hello_riscv_param"),
        f"OUT_DIR={binary.parent}",
        f"OUT={binary}",
        "FLAGS=-O3 -funroll-loops",
    ]


def test_wrapper_command_builds_inside_run_dir(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "name: x\nbenchmark:\n  name: hello_riscv_param\n  args: [256, 1]\n"
        f"output:\n  dir: {tmp_path / 'out'}\n",
    )
    experiment = load_experiment(path)
    resolved = tmp_path / "resolved.json"
    command = wrapper_command(experiment, path, resolved, Path("/gem5"), "run1")

    binary = tmp_path / "out" / "run1" / "inputs" / "hello_riscv_param"
    # command = [python, wrapper, --opção, valor, ..., --quiet, "--", *gem5_args]
    separator = command.index("--")
    assert command[separator - 1] == "--quiet"
    options = dict(zip(command[2 : separator - 1 : 2], command[3 : separator - 1 : 2], strict=True))
    assert options["--binary"] == str(binary)
    assert options["--config"] == str(GEM5_CONFIG)
    assert options["--results-dir"] == str(tmp_path / "out")
    assert options["--run-id"] == "run1"
    assert options["--experiment"] == str(path)
    assert options["--resolved-config"] == str(resolved)
    assert json.loads(options["--build-command"]) == build_command(experiment, binary)
    assert command[separator + 1 :] == experiment.gem5_args()
    assert command[separator + 1 :][:2] == ["--arg=256", "--arg=1"]


def test_resolved_config_distinguishes_one_parameter(tmp_path: Path) -> None:
    base = "name: x\nbenchmark:\n  name: hello_riscv\ncpu:\n  clock: {}\n"
    first = resolved_config(load_experiment(write(tmp_path, base.format("1GHz"))))
    second = resolved_config(load_experiment(write(tmp_path, base.format("2GHz"))))

    assert first["cpu"]["clock"] == "1GHz"
    assert second["cpu"]["clock"] == "2GHz"
    first["cpu"]["clock"] = second["cpu"]["clock"]
    assert first == second
