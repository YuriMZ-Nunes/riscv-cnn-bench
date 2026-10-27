"""A matriz final da campanha (campaigns/final.yaml, RCB-22), as medições da
estimativa (campaigns/medicao.yaml) e o piloto (campaigns/piloto.yaml, RCB-23):
número de execuções, parâmetros fixados e cobertura."""

from pathlib import Path

import pytest

from riscvcnnbench.campaign import Plan, build_plan, load_campaign
from riscvcnnbench.config import MUL_LATENCY, PROJECT_ROOT, check_experiment
from test_kernels_e2e import OPS

FINAL = PROJECT_ROOT / "campaigns/final.yaml"
MEDICAO = PROJECT_ROOT / "campaigns/medicao.yaml"


def plan_of(path: Path, tmp_path: Path) -> Plan:
    return build_plan(load_campaign(path), tmp_path / path.stem, path)


@pytest.fixture(scope="module")
def final(tmp_path_factory: pytest.TempPathFactory) -> tuple[Plan, dict[str, dict]]:
    plan = plan_of(FINAL, tmp_path_factory.mktemp("final"))
    resolved = {
        run.name: check_experiment(run.data, FINAL).model_dump(mode="json") for run in plan.runs
    }
    return plan, resolved


def test_groups_and_counts(final: tuple[Plan, dict]) -> None:
    plan, _ = final
    campaign = plan.campaign

    assert campaign.validate_first
    assert [group.name for group in campaign.groups] == ["principal", "latencia", "compilador"]
    # Cada grupo diz o objetivo e a variável que isola.
    for group in campaign.groups:
        assert "Isola" in group.description or "Cada comparação muda um fator" in group.description
    new = {g.name: sum(1 for run in plan.runs if run.groups[0] == g.name) for g in campaign.groups}
    assert new == {"principal": 504, "latencia": 112, "compilador": 4}
    assert len(plan.runs) == 620 and not plan.invalid
    principal = campaign.groups[0]
    assert principal.experiments == [f"{op}_{size}" for op in OPS for size in "sl"]


def test_fixed_parameters(final: tuple[Plan, dict]) -> None:
    plan, resolved = final
    for run in plan.runs:
        config = resolved[run.name]
        cpu, benchmark = config["cpu"], config["benchmark"]
        assert benchmark["cache_state"] == "warm", run.name
        assert str(benchmark["args"][-1]) == "1", run.name  # R = 1
        assert (cpu["clock"], cpu["vlen"]) == ("1GHz", 256), run.name
        assert cpu["model"] in ("timing", "minor", "o3-edge"), run.name
        assert config["scenario"] in ("sem-cache", "l1", "l1-l2", "reduzido"), run.name
        latency = cpu["custom_latency"]
        if benchmark["variant"] == "custom" and cpu["model"] != "timing":
            assert latency in (MUL_LATENCY, 6), run.name
        else:
            assert latency == MUL_LATENCY, run.name
        flags = config["compiler"]["flags"]
        assert flags == ["-O2"] or (flags == ["-O3"] and run.groups == ["compilador"]), run.name


def test_measurements_cover_all_of_s(final: tuple[Plan, dict], tmp_path: Path) -> None:
    # Cada combinação S da matriz com -O2 tem uma igual em campaigns/medicao.yaml,
    # então a estimativa usa a duração medida, não o modelo.
    plan, resolved = final
    medicao = plan_of(MEDICAO, tmp_path)
    measured = {run.key for run in medicao.runs}
    s_runs = [
        run
        for run in plan.runs
        if run.base.endswith("_s") and resolved[run.name]["compiler"]["flags"] == ["-O2"]
    ]
    assert len(s_runs) == 308
    assert all(run.key in measured for run in s_runs)
    assert len(medicao.runs) == 381


def test_pilot_is_part_of_the_final_matrix(final: tuple[Plan, dict], tmp_path: Path) -> None:
    # O piloto (RCB-23) roda só combinações da matriz final: o que ele mede vale nela.
    plan, _ = final
    pilot = plan_of(PROJECT_ROOT / "campaigns/piloto.yaml", tmp_path)
    assert len(pilot.runs) == 64 and not pilot.invalid
    assert {run.key for run in pilot.runs} <= {run.key for run in plan.runs}
