"""Teste de ponta a ponta: compila o hello_riscv e executa no gem5.

Executado apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisa da toolchain RISC-V e do gem5 compilado.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")
RISCV_PREFIX = os.environ.get("RISCV_PREFIX", "riscv64-linux-gnu-")

pytestmark = pytest.mark.e2e


def read_stat(stats: str, name: str) -> float:
    match = re.search(rf"^{re.escape(name)}\s+(\S+)", stats, re.MULTILINE)
    assert match, f"{name} não encontrado em stats.txt"
    return float(match.group(1))


def test_hello_riscv_gem5(tmp_path: Path) -> None:
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    assert shutil.which(f"{RISCV_PREFIX}gcc"), "toolchain RISC-V não encontrada"

    # Compila em pasta temporária para não depender de build/ existente.
    build_dir = tmp_path / "build"
    binary = build_dir / "hello_riscv"
    subprocess.run(
        [
            "make",
            "-C",
            str(ROOT / "benchmarks/hello_riscv"),
            f"OUT_DIR={build_dir}",
            f"OUT={binary}",
        ],
        check=True,
    )
    assert binary.is_file()

    results_dir = tmp_path / "results"
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run-gem5.py"),
            "--gem5",
            str(GEM5),
            "--binary",
            str(binary),
            "--config",
            str(ROOT / "configs/gem5/se_riscv.py"),
            "--results-dir",
            str(results_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    run_dirs = list(results_dir.iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    stderr = (run_dir / "stderr.log").read_text(encoding="utf-8")
    assert run.returncode == 0, f"wrapper falhou:\n{run.stdout}\n{stdout}\n{stderr}"

    # Retorno da execução.
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "completed"
    assert metadata["exit_code"] == 0

    # Log do programa e do gem5.
    assert "RESULT sum=499500" in stdout
    assert "(code=0)" in stdout

    # Estatísticas do gem5.
    stats = (run_dir / "gem5/stats.txt").read_text(encoding="utf-8")
    assert read_stat(stats, "simInsts") > 0
    assert read_stat(stats, "simTicks") > 0
    assert read_stat(stats, "system.cpu.numCycles") > 0


def test_hello_param_cache_experiment(tmp_path: Path) -> None:
    """Executa o exemplo com variação de experiments/ no gem5 configurável."""
    from riscvcnnbench.config import load_experiment

    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    config = load_experiment(ROOT / "experiments/hello_param_cache.yaml")

    binary = tmp_path / "build" / config.benchmark.name
    subprocess.run(
        [
            "make",
            "-C",
            str(config.benchmark_dir),
            f"OUT_DIR={binary.parent}",
            f"OUT={binary}",
            f"FLAGS={' '.join(config.compiler.flags)}",
        ],
        check=True,
    )

    results_dir = tmp_path / "results"
    run = subprocess.run(
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
            "--",
            *config.gem5_args(),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    (run_dir,) = results_dir.iterdir()
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    stderr = (run_dir / "stderr.log").read_text(encoding="utf-8")
    assert run.returncode == 0, f"wrapper falhou:\n{run.stdout}\n{stdout}\n{stderr}"

    assert "RESULT n=65536 repeat=2 sum=4294901760" in stdout
    assert "cpu=timing clock=2GHz l1i=32KiB l1d=32KiB l2=256KiB memória=ddr4/512MiB" in stdout

    # As opções do YAML chegaram ao sistema simulado.
    stats = (run_dir / "gem5/stats.txt").read_text(encoding="utf-8")
    assert read_stat(stats, "system.cpu.dcache.overallMisses::total") > 0
    assert read_stat(stats, "system.l2cache.overallMisses::total") > 0
