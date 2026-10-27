"""Tabelas de resultados em CSV (RCB-20).

Junta as execuções sob uma pasta (results/, uma campanha...) em duas tabelas:
runs.csv, uma linha por execução, e pairs.csv, uma linha por par do compare.
Nada é descartado: execuções com falha, resultado inválido, checksum diferente
ou substituídas por outra mais recente ficam marcadas. Valor ausente é célula
vazia, nunca 0. Colunas em docs/report.md.
"""

import csv
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from riscvcnnbench.campaign import config_key
from riscvcnnbench.metric import (
    BASE_UNITS,
    DERIVED,
    OPTIMIZATION,
    PAIR_RATIOS,
    Pair,
    Result,
    RunMetrics,
    cache_tuning,
    collect,
    compare,
    load_metrics,
    parse_result,
    scenario_label,
    size_of,
)
from riscvcnnbench.parser import METRICS, StatsError
from riscvcnnbench.runs import Run, diagnose, display, list_runs, read_text

RUNS_FILE = "runs.csv"
PAIRS_FILE = "pairs.csv"
METRIC_KEYS = [metric.key for metric in METRICS]
DERIVED_KEYS = [*BASE_UNITS, *(ratio.key for ratio in DERIVED)]
PAIR_KEYS = [ratio.key for ratio in PAIR_RATIOS]

RUN_COLUMNS = [
    # Identificação e situação
    "run_id",
    "path",
    "campaign",
    "groups",
    "experiment",
    "status",
    "diagnosis",
    "problem",
    "current",
    "checksum_consistent",
    # Operação
    "bench",
    "size",
    "variant",
    "data",
    "params",
    "work_unit",
    # Configuração
    "flags",
    "optimization",
    "cpu",
    "clock",
    "vlen",
    "custom_latency",
    "scenario",
    "l1i_size",
    "l1i_assoc",
    "l1d_size",
    "l1d_assoc",
    "l2_size",
    "l2_assoc",
    "memory",
    "memory_size",
    "cache_state",
    "cache_tuning",
    # Linha RESULT
    "checksum",
    "mismatches",
    "program_exit_code",
    # Métricas da ROI (parser) e derivadas (metric)
    *METRIC_KEYS,
    *DERIVED_KEYS,
    # Proveniência
    "project_commit",
    "project_dirty",
    "gem5_commit",
    "gem5_dirty",
    "gem5_sha256",
    "gem5_matches_executable",
    "binary_sha256",
    "started_at",
    "finished_at",
    "duration_s",
]

PAIR_COLUMNS = [
    "kind",
    "pair",
    "problem",
    "campaign",
    "bench",
    "size",
    "params",
    "data",
    "cpu",
    "clock",
    "scenario",
    "cache_state",
    "variant_a",
    "variant_b",
    "flags_a",
    "flags_b",
    "custom_latency",
    "vlen",
    "run_id_a",
    "run_id_b",
    *(f"{key}_{side}" for key in ("insts", "ops", "cycles", "ipc") for side in "ab"),
    *PAIR_KEYS,
]


def cell(value: Any) -> str:
    """Valor de uma célula: vazio para ausente, true/false, listas com espaço."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple):
        return " ".join(str(item) for item in value)
    return str(value)


def optimization_of(flags: list[str] | None) -> str | None:
    """Último -O* das flags, como no GCC; -O0 se não há; None sem flags registradas."""
    if flags is None:
        return None
    levels = [flag for flag in flags if OPTIMIZATION.match(flag)]
    return levels[-1] if levels else "-O0"


def params_text(result: Result | None) -> str | None:
    if result is None or not result.params:
        return None
    return ";".join(f"{key}={value}" for key, value in result.params.items())


@dataclass
class Entry:
    """Uma execução com o que foi possível ler dela."""

    run: Run
    result: Result | None
    measured: RunMetrics | None
    stats_error: str | None


def load_entry(run: Run) -> Entry:
    try:
        measured = load_metrics(run)
        return Entry(run, measured.result, measured, None)
    except StatsError as error:
        result = parse_result(read_text(run.path / "stdout.log"))
        return Entry(run, result, None, str(error))


def problem_of(entry: Entry) -> str | None:
    """Por que a execução não vale como resultado; None se vale."""
    status = entry.run.metadata.get("status")
    if status != "completed":
        return f"execução não concluída (status {status})"
    if entry.stats_error:
        return entry.stats_error
    assert entry.measured is not None
    return entry.measured.problem


def identity(run: Run) -> str | None:
    """Mesma configuração resolvida e mesmo executável do gem5."""
    if not run.resolved:
        return None
    return f"{config_key(run.resolved)}:{run.metadata.get('gem5_sha256')}"


def current_runs(entries: list[Entry]) -> set[Path]:
    """A execução que vale para cada identidade: a mais recente válida ou, sem nenhuma
    válida, a mais recente. Execuções sem configuração resolvida valem sozinhas."""
    chosen: dict[str, Entry] = {}
    alone: set[Path] = set()
    for entry in entries:  # das mais antigas para as mais recentes
        key = identity(entry.run)
        if key is None:
            alone.add(entry.run.path)
            continue
        previous = chosen.get(key)
        if previous is None or problem_of(entry) is None or problem_of(previous) is not None:
            chosen[key] = entry
    return alone | {entry.run.path for entry in chosen.values()}


def checksum_reference(entries: list[Entry]) -> dict[tuple, str]:
    """Checksum esperado de cada operação, forma e dados: o mais frequente entre as
    execuções ref concluídas com mismatches=0 ou, sem nenhuma, entre todas elas."""
    groups: dict[tuple, list[tuple[str, str]]] = {}
    for entry in entries:
        result = entry.result
        if problem_of(entry) or result is None or result.checksum is None:
            continue
        group = (result.bench, tuple(sorted(result.params.items())), result.data)
        groups.setdefault(group, []).append((result.variant or "", result.checksum))
    reference = {}
    for group, found in groups.items():
        refs = [checksum for variant, checksum in found if variant == "ref"]
        pool = refs or [checksum for _, checksum in found]
        reference[group] = Counter(pool).most_common(1)[0][0]
    return reference


def campaign_of(run: Run, plans: dict[Path, dict]) -> tuple[str | None, list[str] | None]:
    """Campanha e grupos de uma execução em <campanha>/runs/<nome>/<run_id>."""
    if len(run.path.parents) < 3 or run.path.parents[1].name != "runs":
        return None, None
    root = run.path.parents[2]
    if root not in plans:
        path = root / "plan.json"
        plans[root] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    plan = plans[root]
    if not plan:
        return None, None
    groups = next(
        (item["groups"] for item in plan.get("runs", []) if item["name"] == run.path.parent.name),
        None,
    )
    return plan.get("campaign"), groups


def duration(metadata: dict) -> float | None:
    try:
        started = datetime.fromisoformat(metadata["started_at"])
        finished = datetime.fromisoformat(metadata["finished_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return round((finished - started).total_seconds(), 3)


def run_row(
    entry: Entry, current: set[Path], reference: dict[tuple, str], plans: dict[Path, dict]
) -> dict[str, Any]:
    run, result, measured = entry.run, entry.result, entry.measured
    metadata, resolved = run.metadata, run.resolved
    benchmark = resolved.get("benchmark") or {}
    cpu = resolved.get("cpu") or {}
    cache = resolved.get("cache") or {}
    memory = resolved.get("memory") or {}
    problem = problem_of(entry)
    diagnosis = diagnose(run)
    campaign, groups = campaign_of(run, plans)
    params = result.params if result else {}
    bench = (result.bench if result else None) or benchmark.get("name") or run.benchmark
    consistent = None
    if result is not None and result.checksum is not None:
        group = (result.bench, tuple(sorted(params.items())), result.data)
        if group in reference:
            consistent = result.checksum == reference[group]
    project = metadata.get("project") or {}
    repository = metadata.get("gem5_repository") or {}
    flags = (resolved.get("compiler") or {}).get("flags")
    row: dict[str, Any] = {
        "run_id": metadata.get("run_id") or run.path.name,
        "path": display(run.path),
        "campaign": campaign,
        "groups": groups,
        "experiment": resolved.get("name"),
        "status": metadata.get("status"),
        "diagnosis": diagnosis.kind if diagnosis else None,
        "problem": problem,
        "current": run.path in current,
        "checksum_consistent": consistent,
        "bench": bench,
        "size": size_of(bench, params) if result else None,
        "variant": (result.variant if result else None) or benchmark.get("variant"),
        "data": result.data if result else None,
        "params": params_text(result),
        "work_unit": measured.work_unit if measured else None,
        "flags": flags,
        "optimization": optimization_of(flags),
        "cpu": cpu.get("model"),
        "clock": cpu.get("clock"),
        "vlen": cpu.get("vlen"),
        "custom_latency": cpu.get("custom_latency"),
        "scenario": resolved.get("scenario"),
        "memory": memory.get("type"),
        "memory_size": memory.get("size"),
        "cache_state": benchmark.get("cache_state"),
        "cache_tuning": cache_tuning(resolved) or None,
        "checksum": result.checksum if result else None,
        "mismatches": result.mismatches if result else None,
        "program_exit_code": metadata.get("program_exit_code"),
        "project_commit": project.get("commit"),
        "project_dirty": project.get("dirty"),
        "gem5_commit": repository.get("commit"),
        "gem5_dirty": repository.get("dirty"),
        "gem5_sha256": metadata.get("gem5_sha256"),
        "gem5_matches_executable": (metadata.get("gem5_build") or {}).get("matches_executable"),
        "binary_sha256": metadata.get("binary_sha256"),
        "started_at": metadata.get("started_at"),
        "finished_at": metadata.get("finished_at"),
        "duration_s": duration(metadata),
    }
    for level in ("l1i", "l1d", "l2"):
        config = cache.get(level) or {}
        row[f"{level}_size"] = config.get("size")
        row[f"{level}_assoc"] = config.get("assoc")
    if measured is not None:
        row.update(measured.stats.metrics)
        row.update(measured.derived)
    return row


def pair_row(pair: Pair) -> dict[str, Any]:
    a, b = pair.a, pair.b
    cpu = a.run.resolved.get("cpu") or {}
    custom = next((item for item in (a, b) if item.variant == "custom"), None)
    rvv = next((item for item in (a, b) if item.variant == "rvv"), None)
    result = a.result or Result({})
    row: dict[str, Any] = {
        "kind": pair.kind,
        "pair": pair.label,
        "problem": pair.problem,
        "campaign": None,
        "bench": result.bench,
        "size": size_of(result.bench, result.params),
        "params": params_text(result),
        "data": result.data,
        "cpu": cpu.get("model"),
        "clock": cpu.get("clock"),
        "scenario": scenario_label(a.run.resolved),
        "cache_state": (a.run.resolved.get("benchmark") or {}).get("cache_state"),
        "variant_a": a.variant,
        "variant_b": b.variant,
        "flags_a": a.flags,
        "flags_b": b.flags,
        "custom_latency": (custom.run.resolved.get("cpu") or {}).get("custom_latency")
        if custom
        else None,
        "vlen": (rvv.run.resolved.get("cpu") or {}).get("vlen") if rvv else None,
        "run_id_a": a.run.metadata.get("run_id"),
        "run_id_b": b.run.metadata.get("run_id"),
    }
    for key in ("insts", "ops", "cycles", "ipc"):
        row[f"{key}_a"] = a.stats.metrics.get(key)
        row[f"{key}_b"] = b.stats.metrics.get(key)
    row.update(pair.values)
    return row


def write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([cell(row.get(column)) for column in columns])


class ReportError(Exception):
    """Problema que impede gravar o relatório."""


@dataclass
class Report:
    """O que foi gravado, para o resumo da CLI."""

    output: Path
    runs: int
    valid: int
    current: int
    inconsistent: int
    pairs: int
    rejected: int


def build_rows(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Linhas de runs.csv e de pairs.csv para as execuções sob `root`."""
    entries = [load_entry(run) for run in list_runs(root)]
    current = current_runs(entries)
    reference = checksum_reference(entries)
    plans: dict[Path, dict] = {}
    runs = [run_row(entry, current, reference, plans) for entry in entries]
    campaigns = {row["path"]: row["campaign"] for row in runs}
    pairs = []
    for pair in compare(*collect(root)).pairs:
        row = pair_row(pair)
        names = {campaigns.get(display(item.run.path)) for item in (pair.a, pair.b)}
        row["campaign"] = names.pop() if len(names) == 1 else None
        pairs.append(row)
    return runs, pairs


def write_report(root: Path, output: Path | None = None, force: bool = False) -> Report:
    """Grava runs.csv e pairs.csv em `output` (padrão: <root>/report/)."""
    output = output or root / "report"
    targets = [output / RUNS_FILE, output / PAIRS_FILE]
    existing = [path for path in targets if path.exists()]
    if existing and not force:
        names = ", ".join(display(path) for path in existing)
        raise ReportError(f"já existe {names}; use --force para regravar ou --output")
    runs, pairs = build_rows(root)
    output.mkdir(parents=True, exist_ok=True)
    write_csv(targets[0], RUN_COLUMNS, runs)
    write_csv(targets[1], PAIR_COLUMNS, pairs)
    return Report(
        output=output,
        runs=len(runs),
        valid=sum(1 for row in runs if row["problem"] is None),
        current=sum(1 for row in runs if row["current"]),
        inconsistent=sum(1 for row in runs if row["checksum_consistent"] is False),
        pairs=len(pairs),
        rejected=sum(1 for row in pairs if row["problem"]),
    )
