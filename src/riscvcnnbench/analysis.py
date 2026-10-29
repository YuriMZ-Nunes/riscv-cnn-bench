"""Tabelas da análise dos resultados (RCB-25).

`write_analysis` lê o runs.csv e o pairs.csv do `report`, com a mesma seleção do
`plot` (válidas, valendo, checksum consistente, com ciclos), e grava as tabelas
que sustentam docs/analysis.md: instruções e R_I, speedup e eficiência (S_C/R_I)
por CPU e cenário, IPC, ciclos e faltas por cenário de memória, sensibilidade à
latência das instruções personalizadas e o contraste -O2 × -O3. Cada tabela sai em
CSV (ponto decimal) e todas juntas em tables.md (vírgula decimal), com
analysis.json (hash das entradas). Doc: docs/analysis.md.
"""

import csv
import hashlib
import json
import statistics
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from riscvcnnbench import __version__
from riscvcnnbench.plot import (
    OPERATIONS,
    pair_skip,
    read_table,
    run_scenario,
    run_skip,
    scenario_order,
    series_of,
    series_order,
)
from riscvcnnbench.report import PAIRS_FILE, RUNS_FILE
from riscvcnnbench.runs import display

MANIFEST = "analysis.json"
MARKDOWN = "tables.md"
# Contexto comum a todas as tabelas; o resto do runs.csv fica de fora.
BASE = {"clock": "1GHz", "data": "random"}
BASE_FLAGS = "-O2"
CPUS = ("timing", "minor", "o3-edge", "o3")
SIZES = ("S", "L")
VARIANTS = ("ref", "custom", "rvv")
VARIANT_PAIRS = ("ref→custom", "ref→rvv", "custom→rvv")
LATENCY_SERIES = "custom@lat6"
LATENCY_PAIR = "ref→custom@lat6"
# Caches de referência dos tamanhos S e L (scope.md); as outras se comparam a elas.
REFERENCE_SCENARIO = "l1-l2"

RUN_NEEDS = (
    "run_id",
    "problem",
    "current",
    "checksum_consistent",
    "bench",
    "size",
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
    "l1d_misses",
    "l2_misses",
    "l1d_mpki",
    "l2_mpki",
    "dram_reads",
)
PAIR_NEEDS = (
    "kind",
    "pair",
    "problem",
    "bench",
    "size",
    "data",
    "cpu",
    "clock",
    "scenario",
    "flags_a",
    "run_id_a",
    "run_id_b",
    "r_i",
    "s_c",
    "ipc_ratio",
)


class AnalysisError(Exception):
    """Entrada ausente ou saída que já existe."""


@dataclass
class Table:
    """Uma tabela da análise: linhas para o CSV e seções do tables.md."""

    name: str
    columns: list[str]
    rows: list[dict[str, Any]]
    markdown: list[str] = field(default_factory=list)


# Leitura -------------------------------------------------------------------------


def number(text: str) -> float | None:
    return float(text) if text not in ("", None) else None


def _in_base(row: dict[str, str]) -> bool:
    return all(row[key] == value for key, value in BASE.items())


def latest(rows: Iterable[dict[str, str]], key: Callable, order: Callable) -> dict[tuple, dict]:
    """Uma linha por chave; havendo repetidas, a mais recente pela ordem `order`."""
    chosen: dict[tuple, dict] = {}
    for row in rows:
        k = key(row)
        if k not in chosen or order(row) > order(chosen[k]):
            chosen[k] = row
    return chosen


def run_points(rows: list[dict[str, str]]) -> dict[tuple, dict[str, str]]:
    """(operação, tamanho, CPU, cenário, série, flags) → execução."""
    valid = [row for row in rows if not run_skip(row) and _in_base(row)]
    return latest(
        valid,
        lambda r: (r["bench"], r["size"], r["cpu"], run_scenario(r), series_of(r), r["flags"]),
        lambda r: r["run_id"],
    )


def pair_points(rows: list[dict[str, str]]) -> dict[tuple, dict[str, str]]:
    """(par, operação, tamanho, CPU, cenário) → par de variantes com -O2 ou contraste."""
    valid = [row for row in rows if not pair_skip(row) and _in_base(row)]
    return latest(
        valid,
        lambda r: (r["pair"], r["bench"], r["size"], r["cpu"], r["scenario"]),
        lambda r: (r["run_id_a"], r["run_id_b"]),
    )


# Formatação ----------------------------------------------------------------------


def integer(value: float | None) -> str:
    return "-" if value is None else f"{round(value):,}".replace(",", ".")


def decimal(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}".replace(".", ",")


def percent(value: float | None) -> str:
    if value is None:
        return "-"
    text = f"{value * 100:+.1f}%"
    return ("+0.0%" if text == "-0.0%" else text).replace(".", ",")


def markdown_table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def ordered_ops(values: Iterable[str]) -> list[str]:
    known = list(OPERATIONS)
    return sorted(set(values), key=lambda op: (known.index(op) if op in known else 99, op))


def ordered_sizes(values: Iterable[str]) -> list[str]:
    return sorted(set(values), key=lambda s: (SIZES.index(s) if s in SIZES else 99, s))


def ordered_cpus(values: Iterable[str]) -> list[str]:
    return sorted(set(values), key=lambda c: (CPUS.index(c) if c in CPUS else 99, c))


def ratio(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b else None


def change(new: float | None, old: float | None) -> float | None:
    """Variação relativa de `old` para `new`."""
    value = ratio(new, old)
    return value - 1 if value is not None else None


# Tabelas -------------------------------------------------------------------------


def instructions_table(runs: dict[tuple, dict[str, str]]) -> Table:
    """Instruções da ROI por variante e R_I. Elas não dependem de CPU nem de cenário;
    `invariant` diz se isso valeu em todas as execuções."""
    found: dict[tuple, dict[str, list[dict[str, str]]]] = {}
    for (op, size, _cpu, _scenario, series, flags), row in runs.items():
        if flags == BASE_FLAGS:
            variant = series.split("@")[0]
            found.setdefault((op, size), {}).setdefault(variant, []).append(row)
    rows = []
    for op in ordered_ops(op for op, _ in found):
        for size in ordered_sizes(s for o, s in found if o == op):
            groups = found[(op, size)]
            entry: dict[str, Any] = {"bench": op, "size": size, "invariant": True}
            for variant in VARIANTS:
                values = [number(row["insts"]) for row in groups.get(variant, [])]
                values = [v for v in values if v is not None]
                per_work = [number(row["insts_per_work"]) for row in groups.get(variant, [])]
                per_work = [v for v in per_work if v is not None]
                entry[f"insts_{variant}"] = statistics.median(values) if values else None
                entry[f"insts_per_work_{variant}"] = (
                    statistics.median(per_work) if per_work else None
                )
                entry[f"runs_{variant}"] = len(values)
                entry["invariant"] = entry["invariant"] and len(set(values)) <= 1
            entry["work_unit"] = next(
                (row["work_unit"] for rows_ in groups.values() for row in rows_), ""
            )
            entry["r_i_custom"] = ratio(entry["insts_ref"], entry["insts_custom"])
            entry["r_i_rvv"] = ratio(entry["insts_ref"], entry["insts_rvv"])
            entry["r_i_custom_rvv"] = ratio(entry["insts_custom"], entry["insts_rvv"])
            rows.append(entry)
    columns = [
        "bench",
        "size",
        "work_unit",
        *(f"insts_{v}" for v in VARIANTS),
        "r_i_custom",
        "r_i_rvv",
        "r_i_custom_rvv",
        *(f"insts_per_work_{v}" for v in VARIANTS),
        *(f"runs_{v}" for v in VARIANTS),
        "invariant",
    ]
    markdown = [
        "",
        "## Instruções da ROI e redução de instruções (R_I)",
        "",
        "Instruções da região de interesse (`numInsts`), iguais em todas as CPUs e cenários "
        "quando a coluna *invariante* diz sim. R_I = instruções da base / da outra variante.",
        "",
        *markdown_table(
            [
                "Operação",
                "Tam.",
                "ref",
                "custom",
                "rvv",
                "ref/custom",
                "ref/rvv",
                "custom/rvv",
                "ref por trabalho",
                "custom por trabalho",
                "rvv por trabalho",
                "Invariante",
            ],
            [
                [
                    f"`{row['bench']}`",
                    row["size"],
                    *(integer(row[f"insts_{v}"]) for v in VARIANTS),
                    decimal(row["r_i_custom"]),
                    decimal(row["r_i_rvv"]),
                    decimal(row["r_i_custom_rvv"]),
                    *(decimal(row[f"insts_per_work_{v}"]) for v in VARIANTS),
                    "sim" if row["invariant"] else "não",
                ]
                for row in rows
            ],
        ),
    ]
    return Table("instructions", columns, rows, markdown)


def speedup_table(pairs: dict[tuple, dict[str, str]]) -> Table:
    """S_C e eficiência S_C/R_I (= razão de IPC) de cada par de variantes com -O2."""
    rows = []
    for (pair, op, size, cpu, scenario), row in pairs.items():
        if row["kind"] != "variante" or row["flags_a"] != BASE_FLAGS:
            continue
        rows.append(
            {
                "pair": pair,
                "bench": op,
                "size": size,
                "cpu": cpu,
                "scenario": scenario,
                "r_i": number(row["r_i"]),
                "s_c": number(row["s_c"]),
                "efficiency": number(row["ipc_ratio"]),
            }
        )
    rows.sort(key=_pair_sort(rows))
    markdown: list[str] = []
    for pair in [*VARIANT_PAIRS, LATENCY_PAIR]:
        mine = [row for row in rows if row["pair"] == pair]
        for size in ordered_sizes(row["size"] for row in mine):
            markdown += _pivot(
                f"## Speedup em ciclos S_C, {pair}, tamanho {size}",
                [row for row in mine if row["size"] == size],
                "s_c",
                first=("R_I", "r_i"),
            )
    main = [row for row in rows if row["pair"] == VARIANT_PAIRS[0]]
    for size in ordered_sizes(row["size"] for row in main):
        markdown += _pivot(
            f"## Eficiência S_C/R_I, {VARIANT_PAIRS[0]}, tamanho {size}",
            [row for row in main if row["size"] == size],
            "efficiency",
            note="Quanto da redução de instruções vira redução de ciclos: 1 = toda; abaixo de 1, "
            "a outra variante executa com IPC menor que a base.",
        )
    columns = ["pair", "bench", "size", "cpu", "scenario", "r_i", "s_c", "efficiency"]
    return Table("speedup", columns, rows, markdown)


def _pair_sort(rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], tuple]:
    ops = ordered_ops(row["bench"] for row in rows)
    cpus = ordered_cpus(row["cpu"] for row in rows)
    scenarios = scenario_order(row["scenario"] for row in rows)
    pairs = [*VARIANT_PAIRS, LATENCY_PAIR]
    return lambda row: (
        pairs.index(row["pair"]) if row["pair"] in pairs else 99,
        row["pair"],
        ops.index(row["bench"]),
        ordered_sizes([row["size"], *SIZES]).index(row["size"]),
        cpus.index(row["cpu"]),
        scenarios.index(row["scenario"]),
    )


def _pivot(
    title: str,
    rows: list[dict[str, Any]],
    value: str,
    first: tuple[str, str] | None = None,
    note: str | None = None,
) -> list[str]:
    """Operações nas linhas, CPU × cenário nas colunas."""
    if not rows:
        return []
    cpus = ordered_cpus(row["cpu"] for row in rows)
    scenarios = scenario_order(row["scenario"] for row in rows)
    cells = {(row["bench"], row["cpu"], row["scenario"]): row for row in rows}
    header = ["Operação", *([first[0]] if first else [])]
    header += [f"{cpu} {scenario}" for cpu in cpus for scenario in scenarios]
    body = []
    for op in ordered_ops(row["bench"] for row in rows):
        mine = [row for row in rows if row["bench"] == op]
        line = [f"`{op}`"]
        if first:
            line.append(decimal(mine[0][first[1]]))
        for cpu in cpus:
            for scenario in scenarios:
                cell = cells.get((op, cpu, scenario))
                line.append(decimal(cell[value]) if cell else "-")
        body.append(line)
    return ["", title, "", *([note, ""] if note else []), *markdown_table(header, body)]


def variants_table(runs: dict[tuple, dict[str, str]]) -> Table:
    """Ciclos, IPC e faltas por execução; ciclos relativos ao cenário de referência."""
    rows = []
    for (op, size, cpu, scenario, series, flags), row in runs.items():
        if flags != BASE_FLAGS:
            continue
        reference = runs.get((op, size, cpu, REFERENCE_SCENARIO, series, flags))
        cycles = number(row["cycles"])
        rows.append(
            {
                "bench": op,
                "size": size,
                "cpu": cpu,
                "scenario": scenario,
                "series": series,
                "insts": number(row["insts"]),
                "cycles": cycles,
                "ipc": number(row["ipc"]),
                "cycles_per_work": number(row["cycles_per_work"]),
                "l1d_misses": number(row["l1d_misses"]),
                "l2_misses": number(row["l2_misses"]),
                "l1d_mpki": number(row["l1d_mpki"]),
                "l2_mpki": number(row["l2_mpki"]),
                "dram_reads": number(row["dram_reads"]),
                "cycles_vs_reference": ratio(cycles, number(reference["cycles"]))
                if reference
                else None,
            }
        )
    ops = ordered_ops(row["bench"] for row in rows)
    cpus = ordered_cpus(row["cpu"] for row in rows)
    scenarios = scenario_order(row["scenario"] for row in rows)
    all_series = series_order(row["series"] for row in rows)
    rows.sort(
        key=lambda r: (
            ops.index(r["bench"]),
            ordered_sizes([r["size"], *SIZES]).index(r["size"]),
            cpus.index(r["cpu"]),
            scenarios.index(r["scenario"]),
            all_series.index(r["series"]),
        )
    )
    cells = {(r["bench"], r["size"], r["cpu"], r["scenario"], r["series"]): r for r in rows}
    markdown: list[str] = []
    for size in ordered_sizes(row["size"] for row in rows):
        header = ["Operação", *(f"{cpu} {s}" for cpu in cpus for s in all_series)]
        body = []
        for op in ops:
            line = [f"`{op}`"]
            for cpu in cpus:
                for series in all_series:
                    cell = cells.get((op, size, cpu, REFERENCE_SCENARIO, series))
                    line.append(decimal(cell["ipc"]) if cell else "-")
            body.append(line)
        markdown += ["", f"## IPC no cenário {REFERENCE_SCENARIO}, tamanho {size}", ""]
        markdown += markdown_table(header, body)
    others = [s for s in scenarios if s != REFERENCE_SCENARIO]
    for size in ordered_sizes(row["size"] for row in rows):
        header = ["Operação", "Série", *(f"{cpu} {s}" for cpu in cpus for s in others)]
        body = []
        for op in ops:
            for series in VARIANTS:
                line = [f"`{op}`", series]
                for cpu in cpus:
                    for scenario in others:
                        cell = cells.get((op, size, cpu, scenario, series))
                        line.append(decimal(cell["cycles_vs_reference"]) if cell else "-")
                body.append(line)
        markdown += [
            "",
            f"## Ciclos relativos ao {REFERENCE_SCENARIO}, tamanho {size}",
            "",
            f"Ciclos no cenário / ciclos no {REFERENCE_SCENARIO}, mesma CPU e variante.",
            "",
            *markdown_table(header, body),
        ]
    for size in ordered_sizes(row["size"] for row in rows):
        header = ["Operação", "CPU", "Cenário"]
        header += [f"L1d {v}" for v in VARIANTS] + [f"L2 {v}" for v in VARIANTS]
        header += [f"DRAM {v}" for v in VARIANTS] + [f"L1d MPKI {v}" for v in VARIANTS]
        body = []
        for op in ops:
            for cpu in cpus:
                for scenario in scenarios:
                    found = [cells.get((op, size, cpu, scenario, v)) for v in VARIANTS]
                    measured = ("l1d_misses", "dram_reads")
                    if not any(c and any(c[k] is not None for k in measured) for c in found):
                        continue
                    line = [f"`{op}`", cpu, scenario]
                    line += [integer(c["l1d_misses"]) if c else "-" for c in found]
                    line += [integer(c["l2_misses"]) if c else "-" for c in found]
                    line += [integer(c["dram_reads"]) if c else "-" for c in found]
                    line += [decimal(c["l1d_mpki"], 1) if c else "-" for c in found]
                    body.append(line)
        markdown += [
            "",
            f"## Faltas e leituras da DRAM na ROI, tamanho {size}",
            "",
            "Faltas de dados na L1d e na L2 e leituras da DRAM (absolutas; sem cache, as "
            "leituras incluem a busca de instruções), e faltas na L1d por mil instruções.",
            "",
            *markdown_table(header, body),
        ]
    columns = [
        "bench",
        "size",
        "cpu",
        "scenario",
        "series",
        "insts",
        "cycles",
        "ipc",
        "cycles_per_work",
        "l1d_misses",
        "l2_misses",
        "l1d_mpki",
        "l2_mpki",
        "dram_reads",
        "cycles_vs_reference",
    ]
    return Table("variants", columns, rows, markdown)


def latency_table(runs: dict[tuple, dict[str, str]], pairs: dict[tuple, dict[str, str]]) -> Table:
    """Ciclos da custom com a latência padrão e com a pessimista, e o S_C de cada uma."""
    rows = []
    for (op, size, cpu, scenario, series, flags), slow in runs.items():
        if series != LATENCY_SERIES or flags != BASE_FLAGS:
            continue
        fast = runs.get((op, size, cpu, scenario, "custom", flags))
        if not fast:
            continue
        base = pairs.get((VARIANT_PAIRS[0], op, size, cpu, scenario))
        pessimist = pairs.get((LATENCY_PAIR, op, size, cpu, scenario))
        rows.append(
            {
                "bench": op,
                "size": size,
                "cpu": cpu,
                "scenario": scenario,
                "cycles_lat3": number(fast["cycles"]),
                "cycles_lat6": number(slow["cycles"]),
                "increase": change(number(slow["cycles"]), number(fast["cycles"])),
                "s_c_lat3": number(base["s_c"]) if base else None,
                "s_c_lat6": number(pessimist["s_c"]) if pessimist else None,
            }
        )
    rows.sort(key=_run_sort(rows))
    cpus = ordered_cpus(row["cpu"] for row in rows)
    body = []
    for op in ordered_ops(row["bench"] for row in rows):
        for size in ordered_sizes(row["size"] for row in rows if row["bench"] == op):
            line = [f"`{op}`", size]
            for cpu in cpus:
                mine = [r for r in rows if (r["bench"], r["size"], r["cpu"]) == (op, size, cpu)]
                at_reference = [r for r in mine if r["scenario"] == REFERENCE_SCENARIO]
                increases = [r["increase"] for r in mine if r["increase"] is not None]
                if not increases:
                    line += ["-", "-", "-"]
                    continue
                ref_row = at_reference[0] if at_reference else None
                spread = f"{percent(min(increases))} a {percent(max(increases))}"
                line.append(f"{percent(ref_row['increase'])}" if ref_row else "-")
                line.append(spread)
                line.append(
                    f"{decimal(ref_row['s_c_lat3'])} → {decimal(ref_row['s_c_lat6'])}"
                    if ref_row
                    else "-"
                )
            body.append(line)
    header = ["Operação", "Tam."]
    for cpu in cpus:
        header += [
            f"{cpu}: ciclos lat 6/3 ({REFERENCE_SCENARIO})",
            f"{cpu}: faixa nos cenários",
            f"{cpu}: S_C ref→custom ({REFERENCE_SCENARIO})",
        ]
    markdown = [
        "",
        "## Sensibilidade à latência das instruções personalizadas",
        "",
        "Aumento de ciclos da custom com latência 6 em relação à latência 3 (a do `mul`), e o "
        "S_C ref→custom com cada latência.",
        "",
        *(markdown_table(header, body) if body else ["Sem execuções da custom com latência 6."]),
    ]
    columns = [
        "bench",
        "size",
        "cpu",
        "scenario",
        "cycles_lat3",
        "cycles_lat6",
        "increase",
        "s_c_lat3",
        "s_c_lat6",
    ]
    return Table("latency", columns, rows, markdown)


def _run_sort(rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], tuple]:
    ops = ordered_ops(row["bench"] for row in rows)
    cpus = ordered_cpus(row["cpu"] for row in rows)
    scenarios = scenario_order(row["scenario"] for row in rows)
    return lambda row: (
        ops.index(row["bench"]),
        ordered_sizes([row["size"], *SIZES]).index(row["size"]),
        cpus.index(row["cpu"]),
        scenarios.index(row["scenario"]),
    )


def compiler_table(runs: dict[tuple, dict[str, str]], pairs: dict[tuple, dict[str, str]]) -> Table:
    """-O2 × -O3: instruções e ciclos de cada variante, e o par ref→custom com cada flag."""
    rows = []
    for (op, size, cpu, scenario, series, flags), other in runs.items():
        if flags == BASE_FLAGS:
            continue
        base = runs.get((op, size, cpu, scenario, series, BASE_FLAGS))
        if not base:
            continue
        variant_pair = pairs.get((VARIANT_PAIRS[0], op, size, cpu, scenario))
        flagged_pair = pairs.get((f"{VARIANT_PAIRS[0]}({flags})", op, size, cpu, scenario))
        rows.append(
            {
                "bench": op,
                "size": size,
                "cpu": cpu,
                "scenario": scenario,
                "series": series,
                "flags": flags,
                "insts_base": number(base["insts"]),
                "insts_flags": number(other["insts"]),
                "cycles_base": number(base["cycles"]),
                "cycles_flags": number(other["cycles"]),
                "r_i_base_custom": number(variant_pair["r_i"]) if variant_pair else None,
                "r_i_flags_custom": number(flagged_pair["r_i"]) if flagged_pair else None,
                "s_c_base_custom": number(variant_pair["s_c"]) if variant_pair else None,
                "s_c_flags_custom": number(flagged_pair["s_c"]) if flagged_pair else None,
            }
        )
    run_key = _run_sort(rows)
    rows.sort(key=lambda r: (*run_key(r), r["series"], r["flags"]))
    body = [
        [
            f"`{r['bench']}`",
            r["size"],
            r["cpu"],
            r["scenario"],
            r["series"],
            r["flags"],
            integer(r["insts_base"]),
            integer(r["insts_flags"]),
            percent(change(r["insts_flags"], r["insts_base"])),
            integer(r["cycles_base"]),
            integer(r["cycles_flags"]),
            percent(change(r["cycles_flags"], r["cycles_base"])),
            f"{decimal(r['r_i_base_custom'])} → {decimal(r['r_i_flags_custom'])}",
            f"{decimal(r['s_c_base_custom'])} → {decimal(r['s_c_flags_custom'])}",
        ]
        for r in rows
    ]
    header = [
        "Operação",
        "Tam.",
        "CPU",
        "Cenário",
        "Série",
        "Flags",
        f"Instr. {BASE_FLAGS}",
        "Instr. flags",
        "Δ instr.",
        f"Ciclos {BASE_FLAGS}",
        "Ciclos flags",
        "Δ ciclos",
        f"R_I ref→custom {BASE_FLAGS} → flags",
        f"S_C ref→custom {BASE_FLAGS} → flags",
    ]
    markdown = ["", f"## Compilador: {BASE_FLAGS} × outras flags", ""]
    markdown += markdown_table(header, body) if body else ["Sem execuções com outras flags."]
    columns = [
        "bench",
        "size",
        "cpu",
        "scenario",
        "series",
        "flags",
        "insts_base",
        "insts_flags",
        "cycles_base",
        "cycles_flags",
        "r_i_base_custom",
        "r_i_flags_custom",
        "s_c_base_custom",
        "s_c_flags_custom",
    ]
    return Table("compiler", columns, rows, markdown)


# Saída ---------------------------------------------------------------------------


def csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(round(value, 6))
    return str(value)


def build_tables(run_rows: list[dict[str, str]], pair_rows: list[dict[str, str]]) -> list[Table]:
    runs = run_points(run_rows)
    pairs = pair_points(pair_rows)
    return [
        instructions_table(runs),
        speedup_table(pairs),
        variants_table(runs),
        latency_table(runs, pairs),
        compiler_table(runs, pairs),
    ]


def write_analysis(source: Path, output: Path, force: bool = False) -> list[Table]:
    """Grava as tabelas de `source` (pasta com runs.csv e pairs.csv) em `output`."""
    inputs = {name: source / name for name in (RUNS_FILE, PAIRS_FILE)}
    run_rows = read_table(inputs[RUNS_FILE], RUN_NEEDS)
    pair_rows = read_table(inputs[PAIRS_FILE], PAIR_NEEDS)
    tables = build_tables(run_rows, pair_rows)
    targets = [output / f"{table.name}.csv" for table in tables]
    targets += [output / MARKDOWN, output / MANIFEST]
    existing = [path for path in targets if path.exists()]
    if existing and not force:
        names = ", ".join(display(path) for path in existing[:3])
        more = f" e mais {len(existing) - 3}" if len(existing) > 3 else ""
        raise AnalysisError(f"já existe {names}{more}; use --force para regravar ou --output")
    output.mkdir(parents=True, exist_ok=True)
    for table in tables:
        with (output / f"{table.name}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(table.columns)
            for row in table.rows:
                writer.writerow([csv_cell(row.get(column)) for column in table.columns])
    sources = {
        name: {
            "source": display(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in inputs.items()
    }
    lines = [
        "# Tabelas da análise",
        "",
        f"Geradas por `riscvcnnbench analyze` {__version__} a partir de "
        + " e ".join(f"`{info['source']}`" for info in sources.values())
        + ". Interpretação em docs/analysis.md.",
    ]
    for table in tables:
        lines += table.markdown
    (output / MARKDOWN).write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        "generated_by": f"riscvcnnbench analyze {__version__}",
        "inputs": sources,
        "tables": {table.name: len(table.rows) for table in tables},
    }
    (output / MANIFEST).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return tables
