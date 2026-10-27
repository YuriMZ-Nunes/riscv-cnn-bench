"""Teste de ponta a ponta das unidades das instruções personalizadas (RCB-33).

Executado apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisa da toolchain RISC-V e do gem5 do fork compilado.

Com o insn_latency (cnn.dot8): numa cadeia dependente (MODE 0), cada instrução
espera a anterior, e nem mais unidades nem pipeline ajudam; em 8 cadeias
independentes (MODE 1), o que limita é quantas instruções as unidades aceitam
por ciclo. Confere também a montagem das unidades no config.ini da o3-edge.
"""

import configparser
from pathlib import Path

import pytest

from test_scenarios_e2e import DOT8, run

pytestmark = pytest.mark.e2e

N = 1000  # iterações de 8 cnn.dot8
UNITS = {
    "padrao": {},
    "np": {"custom_pipelined": False},
    "np2u": {"custom_pipelined": False, "custom_units": 2},
    "2u": {"custom_units": 2},
}


def cycles(tmp_path: Path, cpu: str, mode: int) -> dict[str, float]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    found = {}
    for name, extra in UNITS.items():
        measured, stdout = run(
            tmp_path,
            f"m{mode}_{name}",
            {
                "scenario": "l1-l2",
                "benchmark": {"name": "insn_latency", "args": [DOT8, N, mode]},
                "cpu": {"model": cpu, **extra},
            },
        )
        if extra.get("custom_units"):
            assert f"custom_units={extra['custom_units']}" in stdout
        if extra.get("custom_pipelined") is False:
            assert "custom_pipelined=false" in stdout
        found[name] = measured.stats.metrics["cycles"]
    return found


@pytest.mark.parametrize("cpu", ["minor", "o3-edge"])
def test_units_and_pipeline(tmp_path: Path, cpu: str) -> None:
    chain = cycles(tmp_path / "cadeia", cpu, 0)
    lanes = cycles(tmp_path / "independentes", cpu, 1)

    # Cadeia dependente: só a latência (3) conta, 8 · N · 3 ciclos.
    assert all(value == pytest.approx(chain["padrao"], rel=0.01) for value in chain.values())
    assert chain["padrao"] == pytest.approx(8 * N * 3, rel=0.05)
    # Independentes: sem pipeline, uma por latência; duas unidades dividem a espera.
    assert lanes["padrao"] < 0.6 * chain["padrao"]
    assert lanes["np"] > 2 * lanes["padrao"]
    assert lanes["np2u"] < 0.6 * lanes["np"]
    if cpu == "o3-edge":
        # Unidades próprias livram a IntMultDiv única e aceitam duas por ciclo.
        assert lanes["2u"] < 0.85 * lanes["padrao"]


def test_o3_edge_unit_layout(tmp_path: Path) -> None:
    run(
        tmp_path,
        "layout",
        {
            "scenario": "l1-l2",
            "benchmark": {"name": "insn_latency", "args": [DOT8, 10, 1]},
            "cpu": {"model": "o3-edge", "custom_units": 2, "custom_pipelined": False},
        },
    )
    (run_dir,) = (tmp_path / "layout").iterdir()
    config = configparser.ConfigParser(strict=False, interpolation=None)
    config.read(run_dir / "gem5" / "config.ini")
    units = {
        name: section
        for name, section in config.items()
        if name.startswith("system.cpu.instQueues.fuPool.FUList") and "." not in name[35:]
    }
    ops = {
        name: [
            config[f"{name}.{child}"]["opClass"] for child in section.get("children", "").split()
        ]
        for name, section in units.items()
    }
    cnn = [name for name, classes in ops.items() if "CnnMult" in classes]
    # Uma unidade só de CnnMult, com 2 cópias e sem pipeline; a IntMultDiv sem ela.
    assert len(cnn) == 1 and ops[cnn[0]] == ["CnnMult"]
    assert config[cnn[0]]["count"] == "2"
    op = config[f"{cnn[0]}.{config[cnn[0]]['children']}"]
    assert (op["opLat"], op["pipelined"]) == ("3", "false")
    assert any(classes[:1] == ["IntMult"] for classes in ops.values())
