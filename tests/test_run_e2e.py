"""Teste de ponta a ponta de `riscvcnnbench run`: YAML → build → gem5 → pasta.

Executado apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisa da toolchain RISC-V e do gem5 compilado.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from riscvcnnbench.config import load_experiment
from riscvcnnbench.runner import resolved_config
from riscvcnnbench.runs import diagnose, load_run

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")
RISCV_PREFIX = os.environ.get("RISCV_PREFIX", "riscv64-linux-gnu-")

pytestmark = pytest.mark.e2e


def write_experiment(tmp_path: Path, name: str, extra: str = "", args: str = "[256, 1]") -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(
        f"name: {name}\n"
        "benchmark:\n"
        "  name: hello_riscv_param\n"
        f"  args: {args}\n"
        f"output:\n  dir: {tmp_path / 'results' / name}\n" + extra,
        encoding="utf-8",
    )
    return path


def run_cli(path: Path, gem5: Path = GEM5) -> tuple[subprocess.CompletedProcess, Path, dict]:
    """Executa `riscvcnnbench run` e devolve o processo, a pasta e os metadados."""
    run = subprocess.run(
        [sys.executable, "-m", "riscvcnnbench.cli", "run", str(path), "--gem5", str(gem5)],
        capture_output=True,
        text=True,
        check=False,
    )
    (run_dir,) = load_experiment(path).results_dir.iterdir()
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    return run, run_dir, metadata


def test_run_executes_yaml(tmp_path: Path) -> None:
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    path = write_experiment(tmp_path, "run_ok")

    run, run_dir, metadata = run_cli(path)
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert run.returncode == 0, f"run falhou:\n{run.stdout}\n{run.stderr}\n{stdout}"

    assert metadata["schema_version"] == 4
    assert metadata["status"] == "completed"
    assert metadata["failed_step"] is None
    assert metadata["exit_code"] == 0
    assert metadata["program_exit_code"] == 0
    assert metadata["exit_cause"] == "exiting with last active thread context"
    assert "RESULT n=256 repeat=1 sum=32640" in stdout

    # YAML original, configuração resolvida e comando de build na pasta.
    assert (run_dir / "inputs/experiment.yaml").read_text(encoding="utf-8") == path.read_text(
        encoding="utf-8"
    )
    resolved = resolved_config(load_experiment(path))
    assert metadata["experiment"]["resolved"] == resolved
    assert metadata["experiment"]["source"] == str(path.resolve())
    saved = json.loads((run_dir / "inputs/experiment.resolved.json").read_text(encoding="utf-8"))
    assert saved == resolved

    build = metadata["build"]
    assert build["exit_code"] == 0
    assert build["command"][:3] == ["make", "-C", str(ROOT / "benchmarks/hello_riscv_param")]
    assert "FLAGS=-O2" in build["command"]
    assert (run_dir / "inputs/hello_riscv_param").is_file()
    assert (run_dir / "build.log").is_file()
    command = (run_dir / "command.txt").read_text(encoding="utf-8")
    assert command.startswith("# build\nmake -C ")
    assert "# gem5\n" in command
    assert "--arg=256 --arg=1 --cpu=atomic --clock=1GHz" in command

    assert run.stdout.startswith("Executando run_ok em ")
    assert f"Pasta:  {run_dir}\nStatus: completed\n" in run.stdout
    assert "Erro:" not in run.stderr


def test_run_reports_build_failure(tmp_path: Path) -> None:
    path = write_experiment(tmp_path, "run_build_fail", 'compiler:\n  flags: ["-fno-such-flag"]\n')

    run, run_dir, metadata = run_cli(path)

    assert run.returncode != 0
    assert metadata["status"] == "failed"
    assert metadata["failed_step"] == "build"
    assert metadata["build"]["exit_code"] != 0
    assert metadata["exit_code"] is None
    assert "-fno-such-flag" in (run_dir / "build.log").read_text(encoding="utf-8")
    assert "Build falhou" in (run_dir / "stderr.log").read_text(encoding="utf-8")
    assert not (run_dir / "gem5/stats.txt").exists()
    assert "Status: failed" in run.stdout
    assert "Erro: o benchmark 'hello_riscv_param' não compilou (make retornou 2): " in run.stderr
    assert "-fno-such-flag" in run.stderr
    assert f"Log: {run_dir}/build.log." in run.stderr


def test_run_reports_simulation_failure(tmp_path: Path) -> None:
    # gem5 falso que termina com erro, para não depender de um caso real de falha.
    fake_gem5 = tmp_path / "gem5-falso"
    fake_gem5.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    fake_gem5.chmod(0o755)
    path = write_experiment(tmp_path, "run_sim_fail")

    run, _, metadata = run_cli(path, gem5=fake_gem5)

    assert run.returncode == 3
    assert metadata["status"] == "failed"
    assert metadata["failed_step"] == "simulation"
    assert metadata["build"]["exit_code"] == 0
    assert metadata["exit_code"] == 3
    assert metadata["program_exit_code"] is None
    assert "Erro: o gem5 terminou com código 3 sem concluir a simulação." in run.stderr


def test_run_reports_benchmark_failure(tmp_path: Path) -> None:
    # hello_riscv_param retorna 2 para argumento inválido: falha do programa, não do gem5.
    path = write_experiment(tmp_path, "run_bench_fail", args='["abc"]')

    run, run_dir, metadata = run_cli(path)

    assert run.returncode == 2
    assert metadata["status"] == "failed"
    assert metadata["failed_step"] == "simulation"
    assert metadata["exit_code"] == 2
    assert metadata["program_exit_code"] == 2
    assert run.stderr == (
        "Erro: o benchmark 'hello_riscv_param' terminou com código 2: o gem5 funcionou, "
        "mas o programa reportou resultado inválido ou rejeitou a entrada. Mensagem do "
        "programa: ERRO: N deve ser um inteiro positivo: abc. "
        f"Veja {run_dir}/stdout.log e {run_dir}/stderr.log.\n"
    )


def test_unknown_instruction_is_diagnosed(tmp_path: Path) -> None:
    """Instrução em custom-0, que o gem5 sem instruções personalizadas não conhece."""
    source = tmp_path / "custom.c"
    source.write_text(
        "int main(void) {\n"
        "    int r;\n"
        '    __asm__ volatile(".insn r 0x0b, 0, 0, %0, %1, %2" : "=r"(r) : "r"(1), "r"(2));\n'
        "    return r;\n"
        "}\n",
        encoding="utf-8",
    )
    binary = tmp_path / "custom"
    subprocess.run(
        [
            f"{RISCV_PREFIX}gcc",
            "-O2",
            "-static",
            "-march=rv64gc",
            "-mabi=lp64d",
            "-o",
            binary,
            source,
        ],
        check=True,
    )
    results_dir = tmp_path / "results"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run-gem5.py"),
            "--gem5",
            str(GEM5),
            "--binary",
            str(binary),
            "--config",
            str(ROOT / "configs/gem5/se_riscv_configurable.py"),
            "--results-dir",
            str(results_dir),
        ],
        capture_output=True,
        check=False,
    )
    (run_dir,) = results_dir.iterdir()
    run = load_run(run_dir)

    assert run.metadata["failed_step"] == "simulation"
    assert run.metadata["program_exit_code"] is None
    problem = diagnose(run)
    assert problem is not None
    assert problem.kind == "instruction"
    assert "panic: Unknown instruction 0x" in problem.message
