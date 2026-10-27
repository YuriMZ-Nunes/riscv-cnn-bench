import csv
import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench.analysis import (
    AnalysisError,
    build_tables,
    decimal,
    integer,
    percent,
    write_analysis,
)
from riscvcnnbench.cli import app
from riscvcnnbench.report import PAIR_COLUMNS, RUN_COLUMNS, write_csv
from test_plot import pair, run

REDUCED = {"scenario": "reduzido", "l1d_size": "4KiB", "l2_size": "32KiB"}
MISSES = {"l1d_misses": 10, "l2_misses": 2, "l1d_mpki": 1.25, "l2_mpki": 0.25}


def rid(number: int) -> str:
    return f"20261027T{number:06d}.000000Z-a"


RUNS = [
    run(rid(1), **MISSES),
    run(rid(2), variant="custom", insts=1000, cycles=4000, **MISSES),
    run(rid(3), variant="custom", insts=1000, cycles=5000, custom_latency=6),
    run(rid(4), variant="rvv", insts=600, cycles=3000),
    run(rid(5), cycles=17600, **REDUCED),
    run(rid(6), variant="custom", insts=1000, cycles=6000, **REDUCED),
    run(rid(7), variant="custom", insts=1000, cycles=6600, custom_latency=6, **REDUCED),
    run(rid(8), flags=["-O3"], insts=8000, cycles=16000),
    run(rid(9), variant="custom", flags=["-O3"], insts=900, cycles=4400),
    run(rid(10), cpu="o3-edge", insts=8000, cycles=8000),
    # Fora: atomic, inválida e outro conjunto de dados.
    run(rid(11), cpu="atomic", cycles=None),
    run(rid(12), variant="custom", problem="mismatches = 3"),
    run(rid(13), variant="rvv", data="satpos"),
]
PAIRS = [
    pair("fc", "minor", "l1-l2", 8, 4),
    pair("fc", "minor", "reduzido", 8, 17600 / 6000),
    pair("fc", "minor", "l1-l2", 8, 3.2, label="ref→custom@lat6"),
    pair("fc", "minor", "reduzido", 8, 17600 / 6600, label="ref→custom@lat6"),
    pair("fc", "minor", "l1-l2", 40 / 3, 16 / 3, label="ref→rvv"),
    pair("fc", "minor", "l1-l2", 5 / 3, 4 / 3, label="custom→rvv"),
    pair(
        "fc", "minor", "l1-l2", 8000 / 900, 16000 / 4400, label="ref→custom(-O3)", flags_a=["-O3"]
    ),
    pair("fc", "minor", "l1-l2", 1, 1, label="ref(-O2→-O3)", kind="compilador"),
    # Fora: rejeitado.
    pair("fc", "o3-edge", "l1-l2", 8, 3, problem="checksums diferentes"),
]


@pytest.fixture
def campaign(tmp_path: Path) -> Path:
    root = tmp_path / "campanha"
    (root / "report").mkdir(parents=True)
    write_csv(root / "report/runs.csv", RUN_COLUMNS, RUNS)
    write_csv(root / "report/pairs.csv", PAIR_COLUMNS, PAIRS)
    return root


def tables_of(root: Path) -> dict:
    def read(name: str) -> list[dict[str, str]]:
        with (root / "report" / name).open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    return {table.name: table for table in build_tables(read("runs.csv"), read("pairs.csv"))}


def test_numbers() -> None:
    assert integer(2499690) == "2.499.690"
    assert integer(None) == "-"
    assert decimal(1.5) == "1,50"
    assert decimal(29.94, 1) == "29,9"
    assert percent(0.25) == "+25,0%"
    assert percent(-0.069) == "-6,9%"
    assert percent(-0.00001) == "+0,0%"


def test_instructions(campaign: Path) -> None:
    [row] = tables_of(campaign)["instructions"].rows

    assert (row["bench"], row["size"], row["work_unit"]) == ("fc", "S", "MAC")
    assert (row["insts_ref"], row["insts_custom"], row["insts_rvv"]) == (8000, 1000, 600)
    assert row["r_i_custom"] == 8
    assert row["r_i_rvv"] == pytest.approx(40 / 3)
    assert row["r_i_custom_rvv"] == pytest.approx(5 / 3)
    assert (row["runs_ref"], row["runs_custom"], row["runs_rvv"]) == (3, 4, 1)
    assert row["invariant"] is True

    changed = [*RUNS, run(rid(14), variant="rvv", cpu="o3-edge", insts=610, cycles=1000)]
    [row] = build_tables([{k: _cell(v) for k, v in r.items()} | _blank(r) for r in changed], [])[
        0
    ].rows
    assert row["invariant"] is False
    assert row["insts_rvv"] == 605


def _cell(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return " ".join(value)
    return "" if value is None else str(value)


def _blank(row: dict) -> dict:
    return {column: "" for column in RUN_COLUMNS if column not in row}


def test_speedup_and_efficiency(campaign: Path) -> None:
    table = tables_of(campaign)["speedup"]

    pairs = [(row["pair"], row["scenario"]) for row in table.rows]
    assert pairs == [
        ("ref→custom", "l1-l2"),
        ("ref→custom", "reduzido"),
        ("ref→rvv", "l1-l2"),
        ("custom→rvv", "l1-l2"),
        ("ref→custom@lat6", "l1-l2"),
        ("ref→custom@lat6", "reduzido"),
    ]
    assert table.rows[1]["efficiency"] == pytest.approx(17600 / 6000 / 8)
    text = "\n".join(table.markdown)
    assert "## Speedup em ciclos S_C, ref→custom, tamanho S" in text
    assert "| Operação | R_I | minor l1-l2 | minor reduzido |" in text
    assert "| `fc` | 8,00 | 4,00 | 2,93 |" in text
    assert "## Eficiência S_C/R_I, ref→custom, tamanho S" in text
    assert "| `fc` | 0,50 | 0,37 |" in text


def test_variants_relative_cycles_and_misses(campaign: Path) -> None:
    table = tables_of(campaign)["variants"]

    cells = {(r["cpu"], r["scenario"], r["series"]): r for r in table.rows}
    assert cells["minor", "reduzido", "ref"]["cycles_vs_reference"] == pytest.approx(1.1)
    assert cells["minor", "reduzido", "custom"]["cycles_vs_reference"] == pytest.approx(1.5)
    assert cells["minor", "l1-l2", "custom"]["cycles_vs_reference"] == 1
    assert cells["o3-edge", "l1-l2", "ref"]["ipc"] == 1
    text = "\n".join(table.markdown)
    assert "## IPC no cenário l1-l2, tamanho S" in text
    assert "| `fc` | 0,50 | 0,25 | 0,20 | 0,20 | 1,00 | - | - | - |" in text
    assert "| `fc` | custom | 1,50 | - |" in text
    assert "| `fc` | minor | l1-l2 | 10 | 10 | - | 2 | 2 | - | - | - | - | 1,2 | 1,2 | - |" in text


def test_latency(campaign: Path) -> None:
    table = tables_of(campaign)["latency"]

    increases = {row["scenario"]: row["increase"] for row in table.rows}
    assert increases == pytest.approx({"l1-l2": 0.25, "reduzido": 0.1})
    assert table.rows[0]["s_c_lat3"] == 4
    assert table.rows[0]["s_c_lat6"] == 3.2
    assert "| `fc` | S | +25,0% | +10,0% a +25,0% | 4,00 → 3,20 |" in "\n".join(table.markdown)


def test_compiler(campaign: Path) -> None:
    table = tables_of(campaign)["compiler"]

    rows = {row["series"]: row for row in table.rows}
    assert set(rows) == {"ref", "custom"}
    custom = rows["custom"]
    assert (custom["insts_base"], custom["insts_flags"]) == (1000, 900)
    assert (custom["cycles_base"], custom["cycles_flags"]) == (4000, 4400)
    assert custom["r_i_flags_custom"] == pytest.approx(8000 / 900)
    text = "\n".join(table.markdown)
    assert "| `fc` | S | minor | l1-l2 | custom | -O3 | 1.000 | 900 | -10,0% | 4.000 | 4.400 |" in (
        text
    )
    assert "| 8,00 → 8,89 | 4,00 → 3,64 |" in text


def test_write_analysis(campaign: Path) -> None:
    output = campaign / "analysis"

    tables = write_analysis(campaign / "report", output)

    names = sorted(path.name for path in output.iterdir())
    assert names == sorted([f"{t.name}.csv" for t in tables] + ["tables.md", "analysis.json"])
    with (output / "speedup.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["s_c"] == "4.0" and rows[0]["pair"] == "ref→custom"
    manifest = json.loads((output / "analysis.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256((campaign / "report/runs.csv").read_bytes()).hexdigest()
    assert manifest["inputs"]["runs.csv"]["sha256"] == digest
    assert manifest["tables"]["speedup"] == 6
    markdown = (output / "tables.md").read_text(encoding="utf-8")
    assert markdown.startswith("# Tabelas da análise\n")
    assert "\n\n## Instruções da ROI" in markdown

    with pytest.raises(AnalysisError, match="já existe .*use --force"):
        write_analysis(campaign / "report", output)
    write_analysis(campaign / "report", output, force=True)


def test_cli_analyze(campaign: Path, tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["analyze", str(campaign)])
    assert result.exit_code == 0, result.output
    assert "  speedup.csv: 6 linha(s)" in result.output
    assert (campaign / "analysis" / "tables.md").is_file()

    again = runner.invoke(app, ["analyze", str(campaign)])
    assert again.exit_code == 1 and "use --force" in again.stderr
    missing = runner.invoke(app, ["analyze", str(tmp_path / "nada")])
    assert missing.exit_code == 1 and "gere os CSVs com riscvcnnbench report" in missing.stderr
