"""Teste de ponta a ponta do parser de stats.txt (RCB-16).

Executado apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisa da toolchain RISC-V e do gem5 do fork compilado.

Roda, por `riscvcnnbench run`, a fc S (com ROI) e o hello_riscv_param (sem ROI)
nas CPUs atomic, timing, minor e o3, com e sem cache, com DDR4 e com memória
simple, e confere as métricas do parser com a configuração e com as linhas do
próprio stats.txt.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from riscvcnnbench.cli import app
from riscvcnnbench.parser import METRICS, split_blocks
from riscvcnnbench.runs import load_run, region_stats

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")
FC_S = ["512", "32", "1"]
L1 = {"l1i": {"size": "32KiB"}, "l1d": {"size": "32KiB"}}
L2 = {**L1, "l2": {"size": "256KiB"}}

# Nome -> (benchmark, argumentos, variante, CPU, caches, memória).
CASES = {
    "fc_atomic_nocache_simple": ("fc", FC_S, "ref", "atomic", {}, "simple"),
    "fc_atomic_l2_ddr4": ("fc", FC_S, "ref", "atomic", L2, "ddr4"),
    "fc_timing_l1_simple_custom": ("fc", FC_S, "custom", "timing", L1, "simple"),
    "fc_minor_l2_ddr4_rvv": ("fc", FC_S, "rvv", "minor", L2, "ddr4"),
    "fc_o3_nocache_ddr4": ("fc", FC_S, "ref", "o3", {}, "ddr4"),
    "fc_o3_l2_simple": ("fc", FC_S, "ref", "o3", L2, "simple"),
    "hello_timing_l2_ddr4": ("hello_riscv_param", ["1024", "1"], "ref", "timing", L2, "ddr4"),
}

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, str]]:
    """Executa cada caso uma vez; devolve a pasta da execução e o stdout do `run`."""
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    base = tmp_path_factory.mktemp("parser")
    done = {}
    for name, (benchmark, args, variant, cpu, cache, memory) in CASES.items():
        data = {
            "name": name,
            "benchmark": {"name": benchmark, "args": args, "variant": variant},
            "cpu": {"model": cpu},
            "memory": {"type": memory},
            "output": {"dir": str(base / "results" / name)},
        }
        if cache:
            data["cache"] = cache
        experiment = base / f"{name}.yaml"
        experiment.write_text(yaml.safe_dump(data), encoding="utf-8")
        run = subprocess.run(
            [sys.executable, "-m", "riscvcnnbench.cli", "run", str(experiment)]
            + ["--gem5", str(GEM5)],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, f"{name}:\n{run.stdout}\n{run.stderr}"
        (run_dir,) = (base / "results" / name).iterdir()
        done[name] = (run_dir, run.stdout)
    return done


@pytest.mark.parametrize("name", CASES)
def test_metrics_follow_the_configuration(runs: dict, name: str) -> None:
    benchmark, _, variant, cpu, cache, memory = CASES[name]
    run_dir, stdout = runs[name]
    stats = region_stats(load_run(run_dir))
    metrics = stats.metrics
    has_roi = benchmark == "fc"

    assert (stats.region, stats.blocks) == (("roi", 2) if has_roi else ("program", 1))
    assert stats.cpu == cpu
    assert metrics["insts"] > 0
    assert metrics["mem_refs"] == metrics["loads"] + metrics["stores"]
    # Tempo só nas CPUs que o modelam; preditor de desvios só na minor e na o3.
    if cpu == "atomic":
        assert metrics["cycles"] is metrics["ipc"] is metrics["sim_ticks"] is None
    else:
        assert metrics["ipc"] == pytest.approx(metrics["insts"] / metrics["cycles"], rel=1e-3)
    assert (metrics["branch_mispredicts"] is None) == (cpu in ("atomic", "timing"))
    # Uma métrica por componente configurado; ausente (None) nos que não existem.
    for level in ("l1i", "l1d", "l2"):
        assert (metrics[f"{level}_accesses"] is None) == (level not in cache)
        if level in cache:
            assert 0 <= metrics[f"{level}_misses"] <= metrics[f"{level}_accesses"]
    assert (metrics["dram_reads"] is None) == (memory != "ddr4")
    assert (metrics["simple_reads"] is None) == (memory != "simple")
    # Micro-ops: só a RVV divide instruções (LMUL > 1) no kernel da fc.
    if has_roi:
        assert (metrics["ops"] > metrics["insts"]) == (variant == "rvv")
    assert stdout.splitlines()[-1].startswith(
        f"Métricas: {'ROI' if has_roi else 'programa inteiro'}, {metrics['insts']} instruções, "
    )


@pytest.mark.parametrize("name", CASES)
def test_metrics_match_the_printed_lines(runs: dict, name: str) -> None:
    run_dir, _ = runs[name]
    stats = region_stats(load_run(run_dir))
    (block, *_) = split_blocks((run_dir / "gem5/stats.txt").read_text(encoding="utf-8"))

    assert stats.metrics["insts"] == int(block["simInsts"])
    for metric in METRICS:
        value, raw = stats.metrics[metric.key], block.get(metric.stat)
        if value is not None and raw is not None:
            assert value == pytest.approx(float(raw)), metric.key
        if value is None:
            assert metric.key in stats.missing


def test_omitted_zero_lines_become_zero(runs: dict) -> None:
    # Na ROI da fc S os dados já estão na L1d: o gem5 não imprime faltas nulas.
    run_dir, _ = runs["fc_timing_l1_simple_custom"]
    (block, *_) = split_blocks((run_dir / "gem5/stats.txt").read_text(encoding="utf-8"))
    metrics = region_stats(load_run(run_dir)).metrics

    assert "system.cpu.dcache.overallMisses::total" not in block
    assert (metrics["l1d_misses"], metrics["l1d_miss_rate"]) == (0, 0.0)
    assert metrics["l1d_avg_miss_latency"] is None
    assert metrics["l1d_accesses"] > 0


def test_runs_lists_the_metrics(runs: dict) -> None:
    root = next(iter(runs.values()))[0].parents[1]

    result = CliRunner().invoke(app, ["runs", str(root)])

    assert result.exit_code == 0, result.stderr
    rows = {line.split()[1]: line.split() for line in result.stdout.splitlines()[1:] if line}
    for name in CASES:
        stats = region_stats(load_run(runs[name][0])).metrics
        cycles = "-" if stats["cycles"] is None else str(stats["cycles"])
        assert rows[name][4:7] == ["completed", str(stats["insts"]), cycles], name
