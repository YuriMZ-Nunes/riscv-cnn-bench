import copy
import csv
from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench.campaign import Plan, build_plan, load_campaign
from riscvcnnbench.cli import app
from riscvcnnbench.config import check_experiment
from riscvcnnbench.estimate import (
    CSV_COLUMNS,
    MEASURED,
    MISSING,
    MODEL,
    estimate,
    fit,
    makespan,
    simulated,
    write_csv,
)
from riscvcnnbench.runs import load_run
from test_runs import make_run

MATRIX = """\
name: pequena
output:
  dir: OUT
set:
  scenario: l1-l2
groups:
  - name: variantes
    experiments: [fc_s]
    vary:
      benchmark.variant: [ref, custom, rvv]
      cpu.model: [timing, minor]
"""


def stats(*insts: int) -> str:
    """stats.txt com um bloco por valor de numInsts (ROI e verificação)."""
    return "".join(
        "---------- Begin Simulation Statistics ----------\n"
        f"system.cpu.commitStats0.numInsts {value} # Instruções\n"
        "---------- End Simulation Statistics   ----------\n"
        for value in insts
    )


def measured(
    root: Path, number: int, resolved: dict, insts: tuple[int, ...], seconds: float
) -> Path:
    return make_run(
        root,
        run_id=f"20261027T0000{number:02d}.000000Z-m",
        stats=stats(*insts),
        experiment={"resolved": resolved},
        started_at="2026-10-27T10:00:00+00:00",
        finished_at=f"2026-10-27T10:{int(seconds) // 60:02d}:{seconds % 60:04.1f}+00:00",
    )


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Plan, Path, Path]:
    """Plano de 6 combinações (fc S × ref/custom/rvv × timing/minor) e as medições:

    - ref timing medida (10 s, W = 1 M) e repetida depois (12 s: vale a mais recente);
    - outra ref na timing, com R = 4 (W = 3 M, 20 s): com as duas anteriores, a reta
      da timing é 6,5 s + 4,5 µs · W;
    - custom na atomic (W = 4 M): dá o W da custom em qualquer CPU;
    - ref minor medida (30 s), a única na minor: não há reta para a minor.
    """
    matrix = tmp_path / "matriz.yaml"
    matrix.write_text(MATRIX.replace("OUT", str(tmp_path / "campanha")), encoding="utf-8")
    plan = build_plan(load_campaign(matrix), tmp_path / "campanha", matrix)
    resolved = {
        run.name: check_experiment(run.data, matrix).model_dump(mode="json") for run in plan.runs
    }
    ref_timing = resolved["fc_s__ref__timing__l1-l2"]
    other = copy.deepcopy(ref_timing)
    other["benchmark"]["args"] = ["512", "32", "4"]
    custom_atomic = copy.deepcopy(resolved["fc_s__custom__timing__l1-l2"])
    custom_atomic["cpu"]["model"] = "atomic"
    root = tmp_path / "medidas"
    measured(root, 1, ref_timing, (400_000, 600_000), 10)
    measured(root, 2, other, (1_000_000, 2_000_000), 20)
    measured(root, 3, custom_atomic, (1_000_000, 3_000_000), 3)
    measured(root, 4, resolved["fc_s__ref__minor__l1-l2"], (400_000, 600_000), 30)
    measured(root, 5, ref_timing, (400_000, 600_000), 12)
    return plan, matrix, root


def test_fit_and_makespan() -> None:
    line = fit([(1e6, 10), (3e6, 20), (2e6, 15)])
    assert line is not None
    assert (line.a, line.b * 1e6, line.points, line(4e6)) == pytest.approx((5, 5, 3, 25))
    assert fit([(1e6, 10), (1e6, 12)]) is None
    # O pool da campanha: cada combinação, na ordem, para a primeira tarefa livre.
    assert makespan([10, 30, 25, 0], 2) == 35
    assert makespan([5, 5, 5, 5], 2) == 10
    assert makespan([5, 5, 5], 1) == 15


def test_simulated_sums_the_blocks(tmp_path: Path) -> None:
    with_stats = make_run(tmp_path, run_id="a", stats=stats(100, 250))
    without = make_run(tmp_path, run_id="b")

    assert simulated(load_run(with_stats)) == 350
    assert simulated(load_run(without)) is None


def test_estimate(setup: tuple[Plan, Path, Path]) -> None:
    plan, matrix, root = setup

    result = estimate(plan, matrix, [root], jobs=2)

    rows = {item.name: item for item in result.estimates}
    assert [item.name for item in result.estimates] == [run.name for run in plan.runs]
    assert result.samples == 5
    ref = rows["fc_s__ref__timing__l1-l2"]
    assert (ref.source, ref.seconds, ref.work) == (MEASURED, 12, 1_000_000)
    assert ref.detail is not None and ref.detail.endswith("20261027T000005.000000Z-m")
    custom = rows["fc_s__custom__timing__l1-l2"]
    assert (custom.source, custom.work, custom.extrapolated) == (MODEL, 4_000_000, True)
    assert custom.seconds == pytest.approx(6.5 + 4.5e-6 * 4_000_000)
    assert rows["fc_s__ref__minor__l1-l2"].seconds == 30
    no_line = rows["fc_s__custom__minor__l1-l2"]
    assert (no_line.source, no_line.detail) == (
        MISSING,
        "menos de duas execuções medidas, com W diferentes, na CPU minor a 1GHz no cenário l1-l2",
    )
    no_work = rows["fc_s__rvv__timing__l1-l2"]
    assert (no_work.source, no_work.detail) == (
        MISSING,
        "nenhuma execução medida do mesmo binário com os mesmos argumentos",
    )
    assert (result.count(MEASURED), result.count(MODEL), result.count(MISSING)) == (2, 1, 3)
    assert result.longest is rows["fc_s__ref__minor__l1-l2"]


def test_estimate_csv(setup: tuple[Plan, Path, Path], tmp_path: Path) -> None:
    plan, matrix, root = setup
    path = tmp_path / "tabela.csv"

    write_csv(path, estimate(plan, matrix, [root], jobs=4))

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == CSV_COLUMNS
    custom = next(row for row in rows if row["name"] == "fc_s__custom__minor__l1-l2")
    assert {k: custom[k] for k in ("variant", "cpu", "scenario", "custom_latency", "flags")} == {
        "variant": "custom",
        "cpu": "minor",
        "scenario": "l1-l2",
        "custom_latency": "3",
        "flags": "-O2",
    }
    assert (custom["work"], custom["seconds"], custom["source"]) == ("4000000", "", MISSING)


def test_cli_estimate(setup: tuple[Plan, Path, Path], tmp_path: Path) -> None:
    _, matrix, root = setup
    runner = CliRunner()

    table = tmp_path / "t.csv"
    result = runner.invoke(
        app,
        ["campaign", "estimate", str(matrix), "-m", str(root), "-j", "2", "--csv", str(table)],
    )
    missing = runner.invoke(app, ["campaign", "estimate", str(matrix), "-m", str(tmp_path / "x")])

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[:2] == [
        "Campanha pequena: 6 combinação(ões); estimativa a partir de 5 execução(ões) medida(s) "
        "em 1 pasta(s)",
        "  medida: 2, modelo: 1 (1 fora da faixa de W medida), sem estimativa: 3",
    ]
    # Em série: 12 + 24,5 + 30 s; com 2 tarefas na ordem do plano, termina em 36,5 s.
    assert "  variantes: 6 combinação(ões), 1.1 min em série" in lines
    assert "Total: 1.1 min em série; com 2 tarefa(s), ≈ 0.6 min na ordem do plano" in lines
    assert "Maior combinação: fc_s__ref__minor__l1-l2, ≈ 0.5 min (medida)" in lines
    reason = "nenhuma execução medida do mesmo binário com os mesmos argumentos"
    assert f"  fc_s__rvv__minor__l1-l2: {reason}" in lines
    assert table.is_file()
    assert missing.exit_code == 1 and "pasta não encontrada" in missing.stderr
