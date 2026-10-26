"""Teste de ponta a ponta das métricas derivadas e das comparações (RCB-17).

Executado apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisa da toolchain RISC-V e do gem5 do fork compilado.

Roda a fc S por `riscvcnnbench run` nas três variantes na MinorCPU com L1, a
referência também com -O3 e o par ref × custom na atomic, e confere os pares de
`riscvcnnbench compare` com as métricas de cada execução.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from riscvcnnbench.cli import app
from riscvcnnbench.metric import collect, compare

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")
L1 = {"l1i": {"size": "32KiB"}, "l1d": {"size": "32KiB"}}

# Nome -> (variante, CPU, flags).
CASES = {
    "minor_ref": ("ref", "minor", ["-O2"]),
    "minor_custom": ("custom", "minor", ["-O2"]),
    "minor_rvv": ("rvv", "minor", ["-O2"]),
    "minor_ref_o3": ("ref", "minor", ["-O3"]),
    "atomic_ref": ("ref", "atomic", ["-O2"]),
    "atomic_custom": ("custom", "atomic", ["-O2"]),
}

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Executa cada caso uma vez; devolve a pasta com todas as execuções."""
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    base = tmp_path_factory.mktemp("metric")
    for name, (variant, cpu, flags) in CASES.items():
        data = {
            "name": name,
            "benchmark": {"name": "fc", "args": ["512", "32", "1"], "variant": variant},
            "compiler": {"flags": flags},
            "cpu": {"model": cpu},
            "cache": L1,
            "output": {"dir": str(base / "results" / name)},
        }
        experiment = base / f"{name}.yaml"
        experiment.write_text(yaml.safe_dump(data), encoding="utf-8")
        run = subprocess.run(
            [sys.executable, "-m", "riscvcnnbench.cli", "run", str(experiment)]
            + ["--gem5", str(GEM5)],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, f"{name}:\n{run.stdout}\n{run.stderr}"
    return base / "results"


def test_pairs_of_real_runs(results: Path) -> None:
    items, excluded = collect(results)
    comparison = compare(items, excluded)
    pairs = {(pair.a.stats.cpu, pair.label): pair for pair in comparison.pairs}

    assert (comparison.excluded, comparison.superseded) == ([], [])
    assert set(pairs) == {
        ("minor", "ref→custom"),
        ("minor", "ref→rvv"),
        ("minor", "custom→rvv"),
        ("minor", "ref(-O2→-O3)"),
        ("atomic", "ref→custom"),
    }
    for pair in pairs.values():
        a, b = pair.a.stats.metrics, pair.b.stats.metrics
        # Mesmo resultado: o checksum foi conferido para formar o par.
        assert pair.problem is None
        assert pair.a.result.checksum == pair.b.result.checksum
        assert pair.values["r_i"] == a["insts"] / b["insts"]
        if pair.a.stats.cpu == "atomic":
            assert pair.values["s_c"] is None
        else:
            assert pair.values["s_c"] == a["cycles"] / b["cycles"]
            assert pair.values["s_c"] == pytest.approx(
                pair.values["r_i"] * pair.values["ipc_ratio"]
            )
    # As instruções da ROI não dependem da CPU: R_I igual na minor e na atomic.
    assert pairs["minor", "ref→custom"].values["r_i"] == pairs["atomic", "ref→custom"].values["r_i"]
    # Só a RVV divide instruções em micro-ops.
    assert pairs["minor", "ref→rvv"].values["r_i_ops"] < pairs["minor", "ref→rvv"].values["r_i"]
    assert pairs["minor", "ref→custom"].values["r_i"] > 1


def test_derived_metrics_of_a_real_run(results: Path) -> None:
    items, _ = collect(results)
    (ref,) = [item for item in items if item.run.experiment == "minor_ref"]

    assert ref.work_unit == "MAC"
    assert (ref.derived["repetitions"], ref.derived["work"]) == (1, 16384)
    assert ref.derived["insts_per_work"] == ref.stats.metrics["insts"] / 16384
    assert ref.derived["cpi"] == ref.stats.metrics["cycles"] / ref.stats.metrics["insts"]
    assert ref.missing == {"l2_mpki": "system.l2cache não existe nesta configuração"}


def test_cli_compare_on_real_runs(results: Path) -> None:
    text = CliRunner().invoke(app, ["compare", str(results)])
    document = json.loads(CliRunner().invoke(app, ["compare", str(results), "--json"]).stdout)

    assert text.exit_code == 0, text.stderr
    assert "5 par(es) aceito(s), 0 rejeitado(s)." in text.stdout
    rows = [line.split() for line in text.stdout.splitlines()[1:6]]
    assert {(row[2], row[4]) for row in rows} == {
        ("minor@1GHz", "ref→custom"),
        ("minor@1GHz", "ref→rvv"),
        ("minor@1GHz", "custom→rvv"),
        ("atomic@1GHz", "ref→custom"),
        ("minor@1GHz", "ref(-O2→-O3)"),
    }
    assert {pair["kind"] for pair in document["pairs"]} == {"variante", "compilador"}
