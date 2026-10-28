"""Relatório HTML (RCB-35): os dados embutidos vêm do runs.csv e do pairs.csv com a
seleção do plot, e o JavaScript da página, rodando no QuickJS, resume, filtra,
compara configurações e monta o gráfico com os números esperados."""

import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
import quickjs
from typer.testing import CliRunner

from riscvcnnbench.analysis import write_analysis
from riscvcnnbench.cli import app
from riscvcnnbench.report import PAIR_COLUMNS, RUN_COLUMNS, write_csv
from riscvcnnbench.report_page import ReportPageError, page_data, script, write_page
from test_plot import pair, run

REDUCED = {"scenario": "reduzido", "l1d_size": "4KiB", "l2_size": "32KiB"}
MINOR = "minor|1GHz|l1-l2|-O2|random"
MINOR_REDUCED = "minor|1GHz|reduzido|-O2|random"
O3 = "o3-edge|1GHz|l1-l2|-O2|random"


def rid(number: int) -> str:
    return f"20261027T{number:06d}.000000Z-r"


RUNS = [
    run(rid(1), insts=8000, cycles=16000, params="In=512;Out=32;R=1"),
    run(rid(2), variant="custom", insts=1000, cycles=4000, params="In=512;Out=32;R=1"),
    run(rid(3), cycles=20000, params="In=512;Out=32;R=1", **REDUCED),
    run(rid(4), variant="custom", insts=1000, cycles=8000, params="In=512;Out=32;R=1", **REDUCED),
    run(rid(5), cpu="o3-edge", insts=8000, cycles=8000, params="In=512;Out=32;R=1"),
    run(
        rid(6), variant="custom", cpu="o3-edge", insts=1000, cycles=2000, params="In=512;Out=32;R=1"
    ),
    run(rid(7), bench="maxpool2x2", insts=7000, cycles=9000, params="H=32;W=32;C=16;R=1"),
    # Fora da análise: atomic sem ciclos, inválida.
    run(rid(8), cpu="atomic", cycles=None, params="In=512;Out=32;R=1"),
    run(rid(9), variant="rvv", problem="mismatches = 3", params="In=512;Out=32;R=1"),
]
PAIRS = [
    pair("fc", "minor", "l1-l2", 8, 4),
    pair("fc", "minor", "reduzido", 8, 2.5),
    pair("fc", "o3-edge", "l1-l2", 8, 4),
    pair("fc", "atomic", "l1-l2", 8, None),
]


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    root = tmp_path / "campanha"
    (root / "report").mkdir(parents=True)
    write_csv(root / "report/runs.csv", RUN_COLUMNS, RUNS)
    write_csv(root / "report/pairs.csv", PAIR_COLUMNS, PAIRS)
    return root


@pytest.fixture
def js() -> quickjs.Context:
    context = quickjs.Context()
    context.eval(script())
    return context


def call(context: quickjs.Context, function: str, *args: Any) -> Any:
    payload = ", ".join(json.dumps(arg, ensure_ascii=False) for arg in args)
    return json.loads(context.eval(f"JSON.stringify(REL.{function}({payload}))"))


def test_page_data(folder: Path) -> None:
    data = page_data(folder / "report")

    runs = {item["id"]: item for item in data["runs"]}
    assert len(runs) == 9
    first = runs[rid(1)]
    assert (first["bench"], first["series"], first["cpu"], first["scenario"]) == (
        "fc",
        "ref",
        "minor",
        "l1-l2",
    )
    assert (first["cycles"], first["inst_work"], first["skip"]) == (16000, 8, None)
    assert runs[rid(3)]["scenario"] == "reduzido"
    assert runs[rid(8)]["skip"] == "sem ciclos (CPU atomic)"
    assert runs[rid(9)]["skip"] == "inválida (problem)"
    assert [item["skip"] for item in data["pairs"]] == [None, None, None, "sem ciclos (CPU atomic)"]
    assert data["order"]["scenarios"] == ["l1-l2", "reduzido"]
    assert data["seriesLabels"]["custom"] == "Personalizada"
    assert data["analysis"] is None
    assert len(data["sources"]["runs"]["sha256"]) == 64


def test_numbers(js: quickjs.Context) -> None:
    assert call(js, "integer", 2499690) == "2.499.690"
    assert call(js, "integer", None) == "-"
    assert call(js, "decimal", 1.5) == "1,50"
    assert call(js, "metricText", "l1d_mpki", 29.94) == "29,9"
    assert call(js, "metricText", "cycles", 1234.4) == "1.234"
    assert call(js, "ratioText", 0.7543) == "0,75×"


def test_summary_and_filters(folder: Path, js: quickjs.Context) -> None:
    data = page_data(folder / "report")

    info = call(js, "summary", data)

    assert (info["runs"], info["valid"], info["used"], info["pairs"], info["pairsUsed"]) == (
        9,
        8,
        7,
        4,
        3,
    )
    assert info["ops"] == ["maxpool2x2", "fc"]
    assert info["cpus"] == ["minor", "o3-edge"]
    assert info["series"] == ["ref", "custom"]
    assert dict(info["skipped"]) == {"sem ciclos (CPU atomic)": 1, "inválida (problem)": 1}
    rows = call(js, "runsTable", data, {"cpus": ["o3-edge"]})
    assert [row["id"] for row in rows] == [rid(5), rid(6)]
    by_cycles = call(js, "runsTable", data, {"ops": ["fc"], "cpus": ["minor"]}, "cycles", True)
    assert [row["cycles"] for row in by_cycles] == [20000, 16000, 8000, 4000]


def test_compare_configurations(folder: Path, js: quickjs.Context) -> None:
    data = page_data(folder / "report")

    configs = call(js, "configs", data)
    assert [(item["key"], item["label"], item["runs"]) for item in configs] == [
        (MINOR, "minor · l1-l2", 3),
        (MINOR_REDUCED, "minor · reduzido", 2),
        (O3, "o3-edge · l1-l2", 2),
    ]

    result = call(js, "compare", data, [MINOR, MINOR_REDUCED, O3], "cycles", {"ops": ["fc"]})

    rows = {row["series"]: row for row in result["rows"]}
    assert set(rows) == {"ref", "custom"}
    assert rows["ref"]["values"] == [16000, 20000, 8000]
    assert rows["ref"]["ratios"] == pytest.approx([1, 1.25, 0.5])
    assert rows["custom"]["ratios"] == pytest.approx([1, 2, 0.5])
    geomean = [item["value"] for item in result["geomean"]]
    assert geomean == pytest.approx([1, math.sqrt(1.25 * 2), 0.5])
    # Sem o filtro, o maxpool só existe na base: as outras ficam vazias.
    everything = call(js, "compare", data, [MINOR, O3], "ipc")
    maxpool = [row for row in everything["rows"] if row["bench"] == "maxpool2x2"][0]
    assert maxpool["values"][1] is None and maxpool["ratios"][1] is None


def test_chart(folder: Path, js: quickjs.Context) -> None:
    data = page_data(folder / "report")

    assert call(js, "pairNames", data) == ["ref→custom"]
    panels = call(js, "chart", data, "ref→custom", {})
    assert [panel["cpu"] for panel in panels] == ["minor", "o3-edge"]
    [group] = panels[0]["groups"]
    assert (group["short"], group["size"], group["r_i"]) == ("FC", "S", 8)
    assert [(bar["scenario"], bar["color"], bar["s_c"]) for bar in group["bars"]] == [
        ("l1-l2", 0, 4),
        ("reduzido", 1, 2.5),
    ]
    # A cor segue o cenário, não a posição depois do filtro.
    filtered = call(js, "chart", data, "ref→custom", {"scenarios": ["reduzido"]})
    assert [bar["color"] for bar in filtered[0]["groups"][0]["bars"]] == [1]


def test_analysis_tables(folder: Path, js: quickjs.Context) -> None:
    write_analysis(folder / "report", folder / "analysis")

    data = page_data(folder / "report", folder / "analysis")
    html = call(js, "markdown", data["analysis"])

    assert data["analysis"].startswith("# Tabelas da análise")
    assert "<h2>Tabelas da análise</h2>" in html
    assert "<h3>Instruções da ROI e redução de instruções (R_I)</h3>" in html
    separators = [line for line in data["analysis"].splitlines() if line.startswith("| ---")]
    assert html.count("<table>") == len(separators) > 5
    assert "<code>fc</code>" in html
    assert "<script" not in call(js, "markdown", "| a <script> |\n| --- |\n| x |")


def test_write_page_and_cli(folder: Path) -> None:
    output = folder / "relatorio.html"

    data = write_page(folder / "report", output)

    html = output.read_text(encoding="utf-8")
    embedded = re.search(
        r'<script id="rcb-data" type="application/json">(.*?)</script>', html, re.S
    )
    assert embedded and json.loads(embedded.group(1)) == data
    assert script() in html and "__RCB_" not in html
    with pytest.raises(ReportPageError, match="já existe .*--force"):
        write_page(folder / "report", output)

    runner = CliRunner()
    write_analysis(folder / "report", folder / "analysis")
    result = runner.invoke(app, ["relatorio", str(folder), "--force"])
    assert result.exit_code == 0, result.output
    assert "9 execução(ões), 7 na análise; 4 par(es)" in result.output
    assert "tabelas do analyze: incluídas" in result.output
    again = runner.invoke(app, ["relatorio", str(folder)])
    assert again.exit_code == 1 and "use --force" in again.stderr
    missing = runner.invoke(app, ["relatorio", str(folder / "nada")])
    assert missing.exit_code == 1 and "gere os CSVs com riscvcnnbench report" in missing.stderr
