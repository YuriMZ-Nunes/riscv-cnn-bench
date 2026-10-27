"""Determinismo do gem5 (RCB-23).

Executado apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisa da toolchain RISC-V e do gem5 do fork compilado.

A mesma configuração, executada duas vezes pelo `riscvcnnbench run`, compila o
mesmo binário e produz o mesmo stats.txt, menos as estatísticas do host (tempo
real, memória e taxas por segundo real), e a mesma saída do programa. Casos com as instruções personalizadas
e com a RVV, na minor e na o3-edge, em cenários com e sem os dados na L1d.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from riscvcnnbench.parser import stats_differences

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")

# Nome -> (variante, CPU, cenário, latência).
CASES = {
    "custom_minor_reduzido_lat6": ("custom", "minor", "reduzido", 6),
    "rvv_o3edge_l1l2": ("rvv", "o3-edge", "l1-l2", 3),
}

pytestmark = pytest.mark.e2e


def program_output(stdout: str) -> list[str]:
    return [
        line for line in stdout.splitlines() if line.startswith(("RESULT ", "Simulação encerrada"))
    ]


@pytest.mark.parametrize("name", list(CASES))
def test_same_inputs_same_stats(tmp_path: Path, name: str) -> None:
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    variant, cpu, scenario, latency = CASES[name]
    data = {
        "name": name,
        "scenario": scenario,
        "benchmark": {"name": "fc", "args": ["512", "32", "1"], "variant": variant},
        "cpu": {"model": cpu, "custom_latency": latency},
        "output": {"dir": str(tmp_path / "results")},
    }
    experiment = tmp_path / f"{name}.yaml"
    experiment.write_text(yaml.safe_dump(data), encoding="utf-8")

    for _ in range(2):
        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "riscvcnnbench.cli",
                "run",
                str(experiment),
                "--gem5",
                str(GEM5),
            ],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, f"{run.stdout}\n{run.stderr}"

    first, second = sorted((tmp_path / "results").iterdir())
    metadata = [
        json.loads((d / "metadata.json").read_text(encoding="utf-8")) for d in (first, second)
    ]
    assert metadata[0]["binary_sha256"] == metadata[1]["binary_sha256"]
    stats = [(d / "gem5" / "stats.txt").read_text(encoding="utf-8") for d in (first, second)]
    assert "hostSeconds" in stats[0]  # as do host existem e ficam de fora
    compared, differences = stats_differences(*stats)
    assert differences == []
    assert compared > 1000
    # O cabeçalho do gem5 muda (hora, host, pid, pasta); a saída do programa e o
    # tick final, não.
    output = [
        program_output((d / "stdout.log").read_text(encoding="utf-8")) for d in (first, second)
    ]
    assert len(output[0]) == 2 and output[0] == output[1]
