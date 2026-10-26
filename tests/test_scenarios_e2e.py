"""Teste de ponta a ponta dos cenários de CPU e memória (RCB-18).

Executado apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisa da toolchain RISC-V e do gem5 do fork compilado.

Confere, pelas métricas da ROI lidas do stats.txt:
- a latência configurável das instruções personalizadas (insn_latency): muda os
  ciclos de uma cadeia de cnn.dot8 e não muda os de uma cadeia de mul, na minor,
  na o3 e na o3-edge;
- os quatro cenários de memória de configs/scenarios.yaml, com a fc S;
- as caches frias no início da ROI (benchmark.cache_state: cold);
- a O3 de borda (o3-edge): parâmetros no config.ini e IPC menor que o da O3
  padrão.
"""

import configparser
import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from riscvcnnbench.metric import RunMetrics, load_metrics
from riscvcnnbench.runs import load_run

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")
MUL, DOT8 = 0, 1  # OP do insn_latency
CHAIN = 1000  # iterações de 8 instruções
FC_S = {"name": "fc", "args": [512, 32, 1], "variant": "custom"}
# Linhas de 64 bytes dos pesos da fc S (32 × 512 bytes), lidos todos na ROI.
FC_S_WEIGHT_LINES = 32 * 512 // 64

pytestmark = pytest.mark.e2e


def run(tmp_path: Path, name: str, data: dict) -> tuple[RunMetrics, str]:
    """Executa um experimento por `riscvcnnbench run`; devolve as métricas e o stdout."""
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    results = tmp_path / name
    experiment = tmp_path / f"{name}.yaml"
    document = {"name": name, **data, "output": {"dir": str(results)}}
    experiment.write_text(yaml.safe_dump(document), encoding="utf-8")
    process = subprocess.run(
        [sys.executable, "-m", "riscvcnnbench.cli", "run", str(experiment), "--gem5", str(GEM5)],
        capture_output=True,
        text=True,
    )
    (run_dir,) = results.iterdir()
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert process.returncode == 0, f"{name}:\n{process.stdout}\n{process.stderr}\n{stdout}"
    measured = load_metrics(load_run(run_dir))
    assert measured.problem is None, f"{name}: {measured.problem}"
    return measured, stdout


@pytest.mark.parametrize("cpu", ["minor", "o3", "o3-edge"])
def test_custom_latency_changes_only_custom_cycles(tmp_path: Path, cpu: str) -> None:
    cycles = {}
    for op in (MUL, DOT8):
        for latency in (3, 6):
            measured, stdout = run(
                tmp_path,
                f"op{op}_lat{latency}",
                {
                    "scenario": "l1-l2",
                    "benchmark": {"name": "insn_latency", "args": [op, CHAIN]},
                    "cpu": {"model": cpu, "custom_latency": latency},
                },
            )
            assert f"custom_latency={latency}" in stdout
            cycles[op, latency] = measured.stats.metrics["cycles"]

    # A cadeia de mul não muda com a latência das instruções personalizadas.
    assert cycles[MUL, 6] == cycles[MUL, 3]
    # Com o padrão (3), cnn.dot8 leva o mesmo que o mul: mesma unidade, mesma latência.
    assert cycles[DOT8, 3] == pytest.approx(cycles[MUL, 3], rel=0.02)
    # Com 6, cada cnn.dot8 da cadeia leva 3 ciclos a mais.
    extra_per_insn = (cycles[DOT8, 6] - cycles[DOT8, 3]) / (8 * CHAIN)
    assert extra_per_insn == pytest.approx(3, rel=0.05)


@pytest.mark.parametrize("scenario", ["sem-cache", "l1", "l1-l2", "reduzido"])
def test_short_benchmark_in_each_memory_scenario(tmp_path: Path, scenario: str) -> None:
    measured, stdout = run(
        tmp_path,
        scenario,
        {"scenario": scenario, "benchmark": FC_S, "cpu": {"model": "timing"}},
    )

    assert "memória=ddr4/512MiB" in stdout
    metrics = measured.stats.metrics
    if scenario == "sem-cache":
        # Sem caches, até as instruções vêm da DRAM.
        assert metrics["l1d_misses"] is None and metrics["l1i_misses"] is None
        assert metrics["dram_reads"] > 0
    elif scenario == "reduzido":
        # Os 17 KiB da fc S não cabem na L1d de 4KiB, mas cabem na L2 de 32KiB: as
        # faltas da L2 são só as do código do kernel, buscado pela primeira vez na ROI.
        assert metrics["l1d_misses"] >= FC_S_WEIGHT_LINES
        assert metrics["l2_misses"] < FC_S_WEIGHT_LINES // 4
    else:
        # Cabem na L1d de 32KiB, aquecida pela inicialização.
        assert metrics["l1d_misses"] == 0


@pytest.mark.parametrize("cpu", ["timing", "o3-edge"])
def test_cold_caches_start_the_roi_empty(tmp_path: Path, cpu: str) -> None:
    data = {"scenario": "l1-l2", "benchmark": FC_S, "cpu": {"model": cpu}}
    cold_data = copy.deepcopy(data)
    cold_data["benchmark"]["cache_state"] = "cold"

    warm, warm_stdout = run(tmp_path, "warm", data)
    cold, cold_stdout = run(tmp_path, "cold", cold_data)

    assert "Caches esvaziadas antes da ROI" not in warm_stdout
    assert "Caches esvaziadas antes da ROI" in cold_stdout
    # Mesmo programa e mesma ROI; só o estado das caches muda.
    assert cold.result and warm.result and cold.result.checksum == warm.result.checksum
    assert cold.stats.metrics["insts"] == warm.stats.metrics["insts"]
    assert warm.stats.metrics["l1d_misses"] == 0
    # Frias: os pesos vêm de novo da DRAM. O código do kernel falta nos dois casos,
    # porque só é buscado na ROI.
    assert cold.stats.metrics["l1d_misses"] >= FC_S_WEIGHT_LINES
    assert cold.stats.metrics["l2_misses"] >= FC_S_WEIGHT_LINES
    assert cold.stats.metrics["l1i_misses"] >= warm.stats.metrics["l1i_misses"]
    assert cold.stats.metrics["cycles"] > warm.stats.metrics["cycles"]


def test_o3_edge_is_narrower_than_default(tmp_path: Path) -> None:
    data = {"scenario": "l1-l2", "benchmark": {**FC_S, "variant": "ref"}}
    default, _ = run(tmp_path, "o3", {**data, "cpu": {"model": "o3"}})
    edge, _ = run(tmp_path, "o3_edge", {**data, "cpu": {"model": "o3-edge"}})

    config = configparser.ConfigParser(interpolation=None)
    config.read(edge.run.path / "gem5" / "config.ini")
    cpu = config["system.cpu"]
    expected = {
        "fetchWidth": "4",
        "decodeWidth": "2",
        "renameWidth": "2",
        "dispatchWidth": "2",
        "issueWidth": "4",
        "commitWidth": "2",
        "numROBEntries": "64",
        "LQEntries": "16",
        "SQEntries": "16",
        "numPhysIntRegs": "80",
        "numPhysFloatRegs": "64",
    }
    assert {key: cpu[key] for key in expected} == expected
    queues = [name for name in config.sections() if name.startswith("system.cpu.instQueues")]
    assert [config[name]["numEntries"] for name in queues if "numEntries" in config[name]] == ["48"]

    # Mesmas instruções; a de borda emite menos por ciclo.
    assert edge.stats.metrics["insts"] == default.stats.metrics["insts"]
    assert edge.stats.metrics["ipc"] < default.stats.metrics["ipc"]
