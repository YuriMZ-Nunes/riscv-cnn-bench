"""Relatório de resultados em HTML (RCB-35).

`write_page` grava uma página autônoma (sem servidor nem internet) com os
resultados de uma pasta: visão geral, resultados com filtros e o gráfico de
speedup, comparação entre configurações escolhidas e as tabelas do `analyze`. Os
dados vêm do runs.csv e do pairs.csv do `report`, com a mesma seleção do `plot` e
do `analyze`; a lógica da página fica em web/relatorio.js (funções puras testadas
com o QuickJS). Doc: docs/html_report.md.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from riscvcnnbench import __version__
from riscvcnnbench.analysis import MARKDOWN as ANALYSIS_TABLES
from riscvcnnbench.plot import (
    CPUS,
    OPERATIONS,
    pair_skip,
    read_table,
    run_scenario,
    run_skip,
    scenario_order,
    series_label,
    series_of,
    series_order,
)
from riscvcnnbench.report import PAIRS_FILE, RUNS_FILE
from riscvcnnbench.runs import display

WEB_DIR = Path(__file__).parent / "web"
DEFAULT_NAME = "relatorio.html"
# Nomes curtos das operações no eixo do gráfico.
SHORT_OPERATIONS = {
    "conv3x3_direct": "conv dir.",
    "conv3x3_im2col": "im2col",
    "depthwise3x3": "depthwise",
    "pointwise1x1": "pointwise",
    "maxpool2x2": "maxpool",
    "requant_relu": "requant",
    "fc": "FC",
}

RUN_NEEDS = (
    "run_id",
    "experiment",
    "campaign",
    "problem",
    "current",
    "checksum_consistent",
    "bench",
    "size",
    "params",
    "variant",
    "data",
    "work_unit",
    "flags",
    "cpu",
    "clock",
    "vlen",
    "custom_latency",
    "scenario",
    "l1i_size",
    "l1d_size",
    "l2_size",
    "memory",
    "cache_state",
    "insts",
    "cycles",
    "ipc",
    "insts_per_work",
    "cycles_per_work",
)
PAIR_NEEDS = (
    "kind",
    "pair",
    "problem",
    "bench",
    "size",
    "params",
    "data",
    "cpu",
    "clock",
    "scenario",
    "flags_a",
    "r_i",
    "s_c",
    "ipc_ratio",
)
# Métricas por execução levadas para a página: coluna do runs.csv → chave curta.
RUN_METRICS = {
    "insts": "insts",
    "cycles": "cycles",
    "ipc": "ipc",
    "insts_per_work": "inst_work",
    "cycles_per_work": "cyc_work",
    "l1d_mpki": "l1d_mpki",
    "l2_mpki": "l2_mpki",
    "l1d_misses": "l1d_misses",
    "l2_misses": "l2_misses",
    "dram_reads": "dram_reads",
}


class ReportPageError(Exception):
    """Saída que já existe."""


def number(text: str | None) -> float | None:
    return float(text) if text not in ("", None) else None


def run_record(row: dict[str, str]) -> dict[str, Any]:
    """Uma execução como a página a usa; `skip` diz por que fica fora da análise."""
    record: dict[str, Any] = {
        "id": row["run_id"],
        "experiment": row["experiment"],
        "campaign": row["campaign"],
        "bench": row["bench"],
        "size": row["size"],
        "params": row["params"],
        "variant": row["variant"],
        "series": series_of(row) if row["variant"] else "",
        "data": row["data"],
        "workUnit": row["work_unit"],
        "flags": row["flags"],
        "cpu": row["cpu"],
        "clock": row["clock"],
        "scenario": run_scenario(row),
        "current": row["current"] == "true",
        "problem": row["problem"] or None,
        "skip": None,
    }
    for column, key in RUN_METRICS.items():
        record[key] = number(row.get(column))
    record["skip"] = run_skip(row)
    return record


def pair_record(row: dict[str, str]) -> dict[str, Any]:
    return {
        "kind": row["kind"],
        "pair": row["pair"],
        "bench": row["bench"],
        "size": row["size"],
        "params": row["params"],
        "data": row["data"],
        "cpu": row["cpu"],
        "clock": row["clock"],
        "scenario": row["scenario"],
        "flags": row["flags_a"],
        "r_i": number(row["r_i"]),
        "s_c": number(row["s_c"]),
        "eff": number(row["ipc_ratio"]),
        "problem": row["problem"] or None,
        "skip": pair_skip(row),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def page_data(source: Path, analysis: Path | None = None) -> dict[str, Any]:
    """Os dados embutidos: execuções, pares, ordens e as tabelas da análise."""
    runs_path, pairs_path = source / RUNS_FILE, source / PAIRS_FILE
    runs = [run_record(row) for row in read_table(runs_path, RUN_NEEDS)]
    pairs = [pair_record(row) for row in read_table(pairs_path, PAIR_NEEDS)]
    series = series_order(run["series"] for run in runs if run["series"])
    tables = analysis / ANALYSIS_TABLES if analysis else None
    return {
        "version": __version__,
        "sources": {
            "runs": {"path": display(runs_path), "sha256": _sha256(runs_path)},
            "pairs": {"path": display(pairs_path), "sha256": _sha256(pairs_path)},
        },
        "operations": {name: label.replace("\n", " ") for name, label in OPERATIONS.items()},
        "shortOperations": SHORT_OPERATIONS,
        "order": {
            "cpus": list(CPUS),
            "scenarios": scenario_order(
                [run["scenario"] for run in runs] + [pair["scenario"] for pair in pairs]
            ),
            "series": series,
        },
        "seriesLabels": {name: series_label(name) for name in series},
        "runs": runs,
        "pairs": pairs,
        "analysis": tables.read_text(encoding="utf-8") if tables and tables.is_file() else None,
    }


def script() -> str:
    return (WEB_DIR / "relatorio.js").read_text(encoding="utf-8")


def render(data: dict[str, Any]) -> str:
    template = (WEB_DIR / "relatorio.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("__RCB_DATA__", payload).replace("__RCB_SCRIPT__", script())


def write_page(
    source: Path, output: Path, analysis: Path | None = None, force: bool = False
) -> dict[str, Any]:
    """Grava o relatório de `source` (pasta com runs.csv e pairs.csv) em `output`."""
    if output.exists() and not force:
        raise ReportPageError(f"já existe {display(output)}; use --force para regravar")
    data = page_data(source, analysis)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(data), encoding="utf-8")
    return data
