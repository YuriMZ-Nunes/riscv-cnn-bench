import csv
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from riscvcnnbench.cli import app
from riscvcnnbench.config import PROJECT_ROOT
from riscvcnnbench.metric import SIZES, size_of
from riscvcnnbench.parser import METRICS
from riscvcnnbench.report import (
    PAIR_COLUMNS,
    RUN_COLUMNS,
    ReportError,
    build_rows,
    cell,
    write_report,
)
from test_kernels_e2e import OPS
from test_runs import ROI_STATS, make_run

ATOMIC_INI = "[system.cpu]\ntype=BaseAtomicSimpleCPU\n"
PROVENANCE = {
    "gem5_sha256": "hash",
    "project": {"commit": "abc", "dirty": False},
    "gem5_repository": {"commit": "def", "dirty": False},
    "gem5_build": {"matches_executable": True},
    "started_at": "2026-10-26T10:00:00+00:00",
    "finished_at": "2026-10-26T10:00:12.5+00:00",
}


def resolved(variant: str, cpu: str = "o3", flags: tuple[str, ...] = ("-O2",)) -> dict:
    return {
        "name": f"fc_{variant}",
        "description": "",
        "scenario": "l1-l2",
        "benchmark": {
            "name": "fc",
            "args": ["512", "32", "1"],
            "variant": variant,
            "cache_state": "warm",
        },
        "compiler": {"flags": list(flags)},
        "cpu": {"model": cpu, "clock": "1GHz", "vlen": 256, "custom_latency": 3},
        "cache": {
            "l1i": {"size": "32KiB", "assoc": 4},
            "l1d": {"size": "32KiB", "assoc": 4},
            "l2": {"size": "256KiB", "assoc": 8},
        },
        "memory": {"type": "ddr4", "size": "512MiB"},
        "output": {"dir": "/x"},
    }


def fc_run(
    root: Path,
    run_id: str,
    variant: str,
    checksum: str = "0x00ff",
    mismatches: int = 0,
    cpu: str = "o3",
    flags: tuple[str, ...] = ("-O2",),
    **metadata: object,
) -> Path:
    line = (
        f"RESULT bench=fc variant={variant} data=random In=512 Out=32 R=1 "
        f"checksum={checksum} mismatches={mismatches}\n"
    )
    return make_run(
        root,
        run_id=run_id,
        stdout=line,
        stats=ROI_STATS,
        config_ini=ATOMIC_INI if cpu == "atomic" else None,
        experiment={"resolved": resolved(variant, cpu, flags)},
        **{**PROVENANCE, **metadata},
    )


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def results(tmp_path: Path) -> Path:
    """fc S: ref e custom válidas (a custom repetida), rvv com checksum divergente, uma
    custom -O3 que falhou, uma ref atomic válida seguida de uma falha e um build quebrado."""
    root = tmp_path / "results"
    fc_run(root, "20261026T000001.000000Z-r", "ref")
    fc_run(root, "20261026T000002.000000Z-c", "custom")
    fc_run(root, "20261026T000003.000000Z-c", "custom")
    fc_run(root, "20261026T000004.000000Z-v", "rvv", checksum="0xbad")
    fc_run(
        root,
        "20261026T000005.000000Z-f",
        "custom",
        mismatches=3,
        flags=("-O3",),
        status="failed",
        failed_step="simulation",
        exit_code=1,
        program_exit_code=1,
    )
    fc_run(root, "20261026T000006.000000Z-a", "ref", cpu="atomic")
    fc_run(
        root,
        "20261026T000007.000000Z-a",
        "ref",
        cpu="atomic",
        status="failed",
        failed_step="simulation",
        exit_code=3,
        program_exit_code=None,
    )
    make_run(
        root,
        run_id="20261026T000008.000000Z-b",
        build_log="kernel.c:1: error: boom\n",
        status="failed",
        failed_step="build",
        exit_code=None,
        build={"command": ["make"], "exit_code": 2, "log": "build.log"},
        experiment={"resolved": resolved("ref")},
    )
    return root


def test_sizes_match_the_operation_experiments() -> None:
    for op, (names, *_) in OPS.items():
        for size, suffix in (("S", "s"), ("L", "l")):
            data = yaml.safe_load((PROJECT_ROOT / f"experiments/{op}_{suffix}.yaml").read_text())
            params = dict(
                zip(names.split(), (int(a) for a in data["benchmark"]["args"]), strict=True)
            )
            assert size_of(op, params) == size, (op, size)
            assert {k: v for k, v in params.items() if k != "R"} == SIZES[op][size]


def test_size_of() -> None:
    assert size_of("fc", {"In": 512, "Out": 32, "R": 4}) == "S"
    assert size_of("fc", {"In": 136, "Out": 16, "R": 1}) is None
    assert size_of("hello_riscv_param", {"N": 4096}) is None
    assert size_of(None, {}) is None


def test_cells() -> None:
    assert [cell(None), cell(True), cell(False), cell(["-O2", "-g"]), cell(0), cell(0.5)] == [
        "",
        "true",
        "false",
        "-O2 -g",
        "0",
        "0.5",
    ]


def test_runs_table(results: Path) -> None:
    write_report(results)

    # Chave: o número da execução no run_id (01 a 08).
    rows = {row["run_id"][13:15]: row for row in read(results / "report/runs.csv")}
    with (results / "report/runs.csv").open(encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == RUN_COLUMNS
    assert len(rows) == 8

    ref = rows["01"]
    assert (ref["bench"], ref["size"], ref["variant"], ref["data"]) == ("fc", "S", "ref", "random")
    assert (ref["params"], ref["work_unit"], ref["flags"], ref["optimization"]) == (
        "In=512;Out=32;R=1",
        "MAC",
        "-O2",
        "-O2",
    )
    assert (ref["cpu"], ref["scenario"], ref["l2_size"], ref["memory"]) == (
        "o3",
        "l1-l2",
        "256KiB",
        "ddr4",
    )
    assert (ref["status"], ref["problem"], ref["current"], ref["checksum_consistent"]) == (
        "completed",
        "",
        "true",
        "true",
    )
    assert (ref["insts"], ref["cycles"], ref["repetitions"], ref["work"]) == (
        "115270",
        "66214",
        "1",
        "16384",
    )
    assert float(ref["cpi"]) == pytest.approx(66214 / 115270)
    assert ref["l1d_avg_miss_latency"] == ""  # média 0/0: ausente, não 0
    assert (ref["project_commit"], ref["gem5_commit"], ref["gem5_matches_executable"]) == (
        "abc",
        "def",
        "true",
    )
    assert (ref["project_dirty"], ref["duration_s"]) == ("false", "12.5")
    assert ref["cache_tuning"] == ""

    # Repetida: só a mais recente vale.
    assert (rows["02"]["current"], rows["03"]["current"]) == ("false", "true")
    # Checksum diferente da ref na mesma operação, forma e dados.
    assert rows["04"]["checksum_consistent"] == "false"
    # Falha do benchmark: fica, marcada, com a linha RESULT.
    failed = rows["05"]
    assert (failed["status"], failed["diagnosis"], failed["problem"]) == (
        "failed",
        "benchmark",
        "execução não concluída (status failed)",
    )
    assert (failed["mismatches"], failed["optimization"], failed["insts"]) == ("3", "-O3", "115270")
    # Na atomic, os ciclos ficam vazios; a ref atomic válida vale sobre a falha posterior.
    assert rows["06"]["cycles"] == "" and rows["06"]["insts"] == "115270"
    assert (rows["06"]["current"], rows["07"]["current"]) == ("true", "false")
    # Build quebrado: sem métricas nem RESULT, com o diagnóstico.
    build = rows["08"]
    assert (build["diagnosis"], build["bench"], build["size"], build["insts"]) == (
        "build",
        "fc",
        "",
        "",
    )
    assert all(build[metric.key] == "" for metric in METRICS)


def test_cache_tuning_column(tmp_path: Path) -> None:
    tuned = resolved("custom")
    tuned["scenario"] = None
    tuned["cache"]["line"] = 128
    tuned["cache"]["l1d"] = {"size": "32KiB", "assoc": 4, "prefetcher": "stride"}
    make_run(
        tmp_path,
        run_id="20261027T000001.000000Z-t",
        stdout="RESULT bench=fc variant=custom data=random In=512 Out=32 R=1 "
        "checksum=0x00ff mismatches=0\n",
        stats=ROI_STATS,
        experiment={"resolved": tuned},
        **PROVENANCE,
    )

    write_report(tmp_path)

    [row] = read(tmp_path / "report/runs.csv")
    assert row["cache_tuning"] == "line=128,l1d.pf=stride"
    assert row["scenario"] == ""


def test_pairs_table(results: Path) -> None:
    write_report(results)

    rows = read(results / "report/pairs.csv")
    with (results / "report/pairs.csv").open(encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == PAIR_COLUMNS
    by_label = {row["pair"]: row for row in rows}

    assert sorted(by_label) == ["custom→rvv", "ref→custom", "ref→rvv"]
    pair = by_label["ref→custom"]
    assert (pair["kind"], pair["problem"], pair["size"], pair["scenario"]) == (
        "variante",
        "",
        "S",
        "l1-l2",
    )
    assert (pair["run_id_a"], pair["run_id_b"]) == (
        "20261026T000001.000000Z-r",
        "20261026T000003.000000Z-c",
    )
    assert (pair["custom_latency"], pair["vlen"], pair["insts_a"]) == ("3", "", "115270")
    assert float(pair["r_i"]) == 1.0 and float(pair["s_c"]) == 1.0
    # Checksums diferentes: o par fica, sem valores, com o motivo.
    rejected = by_label["ref→rvv"]
    assert rejected["problem"].startswith("checksums diferentes")
    assert rejected["r_i"] == "" and rejected["vlen"] == "256"


def test_campaign_columns(tmp_path: Path) -> None:
    root = tmp_path / "campanha"
    plan = {
        "campaign": "piloto",
        "runs": [{"name": "fc_s__ref", "groups": ["variantes", "compilador"]}],
    }
    (root / "runs" / "fc_s__ref").mkdir(parents=True)
    (root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    run = fc_run(root / "runs", "20261026T000001.000000Z-r", "ref")
    run.rename(root / "runs" / "fc_s__ref" / run.name)

    runs, _ = build_rows(root)

    assert (runs[0]["campaign"], runs[0]["groups"]) == ("piloto", ["variantes", "compilador"])


def test_existing_report_needs_force(results: Path, tmp_path: Path) -> None:
    first = write_report(results)
    # current: uma por identidade (a custom repetida e a falha atomic posterior não).
    assert (first.runs, first.valid, first.current, first.inconsistent) == (8, 5, 6, 1)
    assert (first.pairs, first.rejected) == (3, 2)

    with pytest.raises(ReportError, match="já existe .*runs.csv.*pairs.csv; use --force"):
        write_report(results)
    write_report(results, force=True)
    other = write_report(results, tmp_path / "outro")
    assert other.output == tmp_path / "outro" and (other.output / "pairs.csv").is_file()


def test_cli_report(results: Path) -> None:
    runner = CliRunner()

    first = runner.invoke(app, ["report", str(results)])
    again = runner.invoke(app, ["report", str(results)])
    missing = runner.invoke(app, ["report", str(results / "nao")])

    assert first.exit_code == 0, first.output
    lines = first.stdout.splitlines()
    assert lines[1:] == [
        "  runs.csv: 8 execução(ões), 5 válida(s), 6 valendo (current), 1 com checksum divergente",
        "  pairs.csv: 3 par(es), 2 rejeitado(s)",
    ]
    assert again.exit_code == 1 and "use --force" in again.stderr
    assert missing.exit_code == 1 and "pasta não encontrada" in missing.stderr
