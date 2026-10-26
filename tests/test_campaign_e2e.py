"""Teste de ponta a ponta das campanhas (RCB-19).

Executado apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisa da toolchain RISC-V e do gem5 do fork compilado.

Roda pela CLI uma matriz pequena (fc S, ref e custom, atomic e timing) com um
grupo que falha de propósito (argumento inválido), confere o estado de cada
combinação, a retomada sem repetir as concluídas e os pares do compare sobre a
pasta da campanha.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")

pytestmark = pytest.mark.e2e


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "riscvcnnbench.cli", *args], capture_output=True, text=True
    )


def test_campaign_runs_resumes_and_records_failures(tmp_path: Path) -> None:
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    # K = 7 não é múltiplo de 8: o benchmark recusa e sai com 2.
    bad = tmp_path / "int8_ruim.yaml"
    bad.write_text(
        "name: int8_ruim\nbenchmark:\n  name: int8_base_example\n  args: [7, 16, 1]\n",
        encoding="utf-8",
    )
    root = tmp_path / "campanha"
    matrix = tmp_path / "matriz.yaml"
    matrix.write_text(
        f"""\
name: e2e
output: {{dir: {root}}}
set: {{scenario: l1-l2}}
groups:
  - name: variantes
    experiments: [fc_s]
    vary:
      benchmark.variant: [ref, custom]
      cpu.model: [atomic, timing]
  - name: falha
    experiments: [{bad}]
""",
        encoding="utf-8",
    )
    options = ["--gem5", str(GEM5)]
    failing = "int8_ruim__ref__atomic__l1-l2"

    first = cli("campaign", "run", str(matrix), "--jobs", "2", *options)

    assert first.returncode == 1, f"{first.stdout}\n{first.stderr}"
    assert "5 combinação(ões): 0 já concluída(s), 5 a executar com 2 tarefa(s)" in first.stdout
    assert f"{failing}: falhou (benchmark)" in first.stdout
    status = cli("campaign", "status", str(root), "--json", *options)
    rows = {row["name"]: row for row in json.loads(status.stdout)}
    assert rows.pop(failing)["diagnosis"] == "benchmark"
    assert {row["status"] for row in rows.values()} == {"concluída"}
    # Cada combinação é um experimento comum, com nome e pasta próprios.
    custom = rows["fc_s__custom__timing__l1-l2"]
    metadata = json.loads((ROOT / custom["run"] / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["experiment"]["resolved"]["name"] == "fc_s__custom__timing__l1-l2"
    assert metadata["experiment"]["resolved"]["scenario"] == "l1-l2"
    assert int(custom["insts"]) < int(rows["fc_s__ref__timing__l1-l2"]["insts"])

    second = cli("campaign", "run", str(matrix), "--jobs", "2", *options)

    # Só a que falhou roda de novo; as pastas antigas ficam.
    assert second.returncode == 1
    assert "5 combinação(ões): 4 já concluída(s), 1 a executar" in second.stdout
    attempts = {path.name: len(list(path.iterdir())) for path in (root / "runs").iterdir()}
    assert attempts.pop(failing) == 2
    assert set(attempts.values()) == {1}
    log = json.loads((root / "campaign.json").read_text(encoding="utf-8"))
    assert [session["executed"] for session in log["sessions"]] == [5, 1]

    compare = cli("compare", str(root), "--json")
    labels = sorted(pair["label"] for pair in json.loads(compare.stdout)["pairs"])
    assert labels == ["ref→custom", "ref→custom"]
