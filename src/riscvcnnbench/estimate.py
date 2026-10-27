"""Estimativa do tempo de uma campanha a partir de execuções medidas (RCB-22).

Para cada combinação do plano:
- se uma execução concluída tem a mesma configuração (a chave da campanha), vale
  a duração dela ("medida");
- senão, duração = a + b · W ("modelo"): W são as instruções simuladas (numInsts
  somado nos blocos do stats.txt, região de interesse e verificação) e a, b vêm
  de uma regressão linear sobre as execuções medidas na mesma CPU, clock e
  cenário de memória. W vem de qualquer execução medida do mesmo binário com os
  mesmos argumentos (operação, argumentos, variante, flags e, na rvv, VLEN), em
  qualquer CPU: o número de instruções não depende da CPU.

Sem W ou sem regressão para a CPU e o cenário, a combinação fica sem estimativa,
com o motivo. O tempo com N tarefas simula o pool de `campaign run`: as
combinações saem na ordem do plano, cada uma para a primeira tarefa livre.
Doc: docs/matrix.md.
"""

import csv
import heapq
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riscvcnnbench.campaign import Plan, config_key
from riscvcnnbench.config import ConfigError, check_experiment
from riscvcnnbench.metric import scenario_label
from riscvcnnbench.parser import StatsError, split_blocks
from riscvcnnbench.report import duration
from riscvcnnbench.runs import Run, display, list_runs, read_text

INSTS = "system.cpu.commitStats0.numInsts"
MEASURED = "medida"
MODEL = "modelo"
MISSING = "sem estimativa"
CSV_COLUMNS = [
    "name",
    "groups",
    "base",
    "variant",
    "cpu",
    "scenario",
    "custom_latency",
    "flags",
    "work",
    "seconds",
    "source",
    "detail",
]


def binary_key(resolved: dict[str, Any]) -> tuple:
    """O que determina as instruções simuladas: o binário e os argumentos."""
    benchmark = resolved.get("benchmark") or {}
    variant = benchmark.get("variant", "ref")
    cpu = resolved.get("cpu") or {}
    return (
        benchmark.get("name"),
        tuple(str(arg) for arg in benchmark.get("args", [])),
        variant,
        tuple((resolved.get("compiler") or {}).get("flags", [])),
        cpu.get("vlen") if variant == "rvv" else None,
    )


def speed_key(resolved: dict[str, Any]) -> tuple[str, str, str]:
    """CPU, clock e cenário de memória: o que muda a velocidade da simulação."""
    cpu = resolved.get("cpu") or {}
    return (cpu.get("model", "atomic"), cpu.get("clock", "1GHz"), scenario_label(resolved))


def simulated(run: Run) -> float | None:
    """Instruções simuladas em todos os blocos do stats.txt (ROI e verificação)."""
    try:
        blocks = split_blocks(read_text(run.path / "gem5" / "stats.txt"))
        return sum(float(block[INSTS]) for block in blocks) if blocks else None
    except (StatsError, KeyError, ValueError):
        return None


@dataclass
class Sample:
    """Uma execução medida: chave, binário, velocidade, W e duração."""

    path: Path
    key: str
    binary: tuple
    speed: tuple[str, str, str]
    work: float
    seconds: float


def samples(roots: list[Path]) -> list[Sample]:
    """Execuções concluídas com configuração resolvida, stats.txt legível e duração,
    das mais antigas para as mais recentes em todas as pastas."""
    runs = sorted(
        (run for root in roots for run in list_runs(root)),
        key=lambda run: run.metadata.get("run_id") or run.path.name,
    )
    found = []
    for run in runs:
        seconds = duration(run.metadata)
        if run.metadata.get("status") != "completed" or not run.resolved or seconds is None:
            continue
        work = simulated(run)
        if work is None:
            continue
        resolved = run.resolved
        found.append(
            Sample(
                run.path,
                config_key(resolved),
                binary_key(resolved),
                speed_key(resolved),
                work,
                seconds,
            )
        )
    return found


@dataclass
class Fit:
    """duração = a + b · W, ajustada em `points` execuções com W entre low e high."""

    a: float
    b: float
    points: int
    low: float
    high: float

    def __call__(self, work: float) -> float:
        return self.a + self.b * work


def fit(points: list[tuple[float, float]]) -> Fit | None:
    """Reta por mínimos quadrados; None com menos de dois valores distintos de W."""
    if len({x for x, _ in points}) < 2:
        return None
    mx = statistics.fmean(x for x, _ in points)
    my = statistics.fmean(y for _, y in points)
    b = sum((x - mx) * (y - my) for x, y in points) / sum((x - mx) ** 2 for x, _ in points)
    xs = [x for x, _ in points]
    return Fit(my - b * mx, b, len(points), min(xs), max(xs))


@dataclass
class Estimate:
    """Uma combinação do plano com o tempo estimado e de onde ele veio."""

    name: str
    groups: list[str]
    base: str
    resolved: dict[str, Any]
    work: float | None = None
    seconds: float | None = None
    source: str = MISSING
    detail: str | None = None
    extrapolated: bool = False


@dataclass
class CampaignEstimate:
    estimates: list[Estimate]
    fits: dict[tuple, Fit]
    samples: int
    roots: list[Path]
    jobs: int
    makespan: float

    @property
    def serial(self) -> float:
        return sum(item.seconds or 0.0 for item in self.estimates)

    @property
    def longest(self) -> Estimate | None:
        timed = [item for item in self.estimates if item.seconds is not None]
        return max(timed, key=lambda item: item.seconds or 0.0, default=None)

    def count(self, source: str) -> int:
        return sum(1 for item in self.estimates if item.source == source)


def makespan(seconds: list[float], jobs: int) -> float:
    """Fim da última combinação com `jobs` tarefas, na ordem dada (o pool da campanha)."""
    workers = [0.0] * max(1, jobs)
    for value in seconds:
        heapq.heappush(workers, heapq.heappop(workers) + value)
    return max(workers)


def estimate(plan: Plan, source: Path, roots: list[Path], jobs: int) -> CampaignEstimate:
    """Tempo de cada combinação de `plan` a partir das execuções sob `roots`."""
    found = samples(roots)
    by_key: dict[str, Sample] = {}
    work_of: dict[tuple, float] = {}
    by_speed: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    for sample in found:  # das mais antigas às mais recentes: vale a última
        by_key[sample.key] = sample
        work_of[sample.binary] = sample.work
        by_speed[sample.speed].append((sample.work, sample.seconds))
    fits = {key: line for key, points in by_speed.items() if (line := fit(points))}

    estimates = []
    for planned in plan.runs:
        try:
            resolved = check_experiment(planned.data, source).model_dump(mode="json")
        except ConfigError as error:
            problems = "; ".join(error.problems)
            item = Estimate(planned.name, planned.groups, planned.base, {}, detail=problems)
            estimates.append(item)
            continue
        item = Estimate(planned.name, planned.groups, planned.base, resolved)
        item.work = work_of.get(binary_key(resolved))
        line = fits.get(speed_key(resolved))
        if (sample := by_key.get(config_key(resolved))) is not None:
            item.seconds, item.source, item.detail = sample.seconds, MEASURED, display(sample.path)
        elif item.work is None:
            item.detail = "nenhuma execução medida do mesmo binário com os mesmos argumentos"
        elif line is None:
            cpu, clock, scenario = speed_key(resolved)
            item.detail = (
                f"menos de duas execuções medidas, com W diferentes, na CPU {cpu} a {clock} "
                f"no cenário {scenario}"
            )
        else:
            item.seconds, item.source = line(item.work), MODEL
            item.extrapolated = not line.low <= item.work <= line.high
            if item.extrapolated:
                item.detail = "W fora da faixa medida nesta CPU e cenário"
        estimates.append(item)

    timed = [item.seconds or 0.0 for item in estimates]
    return CampaignEstimate(estimates, fits, len(found), roots, jobs, makespan(timed, jobs))


def write_csv(path: Path, result: CampaignEstimate) -> None:
    """Uma linha por combinação do plano, com o tempo estimado e a origem dele."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for item in result.estimates:
            cpu = item.resolved.get("cpu") or {}
            variant = (item.resolved.get("benchmark") or {}).get("variant")
            writer.writerow(
                [
                    item.name,
                    " ".join(item.groups),
                    item.base,
                    variant or "",
                    cpu.get("model", ""),
                    scenario_label(item.resolved) if item.resolved else "",
                    cpu.get("custom_latency", "") if variant == "custom" else "",
                    " ".join((item.resolved.get("compiler") or {}).get("flags", [])),
                    "" if item.work is None else f"{item.work:.0f}",
                    "" if item.seconds is None else f"{item.seconds:.1f}",
                    item.source,
                    item.detail or "",
                ]
            )
