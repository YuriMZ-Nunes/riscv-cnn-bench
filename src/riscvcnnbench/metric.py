"""Métricas derivadas por execução e comparação entre execuções (RCB-17).

Parte das métricas brutas da ROI (parser.py, RCB-16) e da linha RESULT que os
benchmarks da base comum imprimem. Fórmulas, chave dos pares e motivos de
rejeição em docs/results.md, seção "Métricas derivadas e comparações".
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riscvcnnbench.config import MUL_LATENCY, CompilerConfig
from riscvcnnbench.parser import RegionStats, StatsError, Value
from riscvcnnbench.runs import Run, list_runs, read_text, region_stats

RESULT_LINE = re.compile(r"^RESULT (.*)$", re.MULTILINE)
RESULT_FIELDS = ("bench", "variant", "data", "checksum", "mismatches")
INTEGER = re.compile(r"^-?\d+$")
OPTIMIZATION = re.compile(r"^-O\w*$")
BASE_OPTIMIZATION = "-O2"
DEFAULT_VLEN = 256
VARIANT_PAIRS = (("ref", "custom"), ("ref", "rvv"), ("custom", "rvv"))
# Campos da configuração resolvida que não mudam o binário nem a simulação de uma
# variante: a VLEN só vale para a RVV, e a latência das instruções
# personalizadas (RCB-18), só para a custom.
IRRELEVANT: dict[str, set[tuple[str, str]]] = {
    "ref": {
        ("cpu", "vlen"),
        ("cpu", "custom_latency"),
        ("cpu", "custom_units"),
        ("cpu", "custom_pipelined"),
    },
    "custom": {("cpu", "vlen")},
    "rvv": {("cpu", "custom_latency"), ("cpu", "custom_units"), ("cpu", "custom_pipelined")},
}


@dataclass(frozen=True)
class Result:
    """Campos `chave=valor` da linha RESULT, como o programa os imprimiu."""

    fields: dict[str, str]

    @property
    def bench(self) -> str | None:
        return self.fields.get("bench")

    @property
    def variant(self) -> str | None:
        return self.fields.get("variant")

    @property
    def data(self) -> str | None:
        return self.fields.get("data")

    @property
    def checksum(self) -> str | None:
        return self.fields.get("checksum")

    @property
    def mismatches(self) -> int | None:
        value = self.fields.get("mismatches", "")
        return int(value) if INTEGER.match(value) else None

    @property
    def params(self) -> dict[str, int]:
        """Parâmetros da operação (H, W, Cin, ..., R), com os valores usados de fato."""
        return {
            key: int(value)
            for key, value in self.fields.items()
            if key not in RESULT_FIELDS and INTEGER.match(value)
        }


def parse_result(stdout: str) -> Result | None:
    """Última linha RESULT do stdout.log; None se o programa não imprimiu nenhuma."""
    lines = RESULT_LINE.findall(stdout)
    if not lines:
        return None
    return Result(dict(item.split("=", 1) for item in lines[-1].split() if "=" in item))


def _conv_macs(params: dict[str, int]) -> int:
    return params["H"] * params["W"] * 9 * params["Cin"] * params["Cout"]


# Operação -> (unidade, trabalho por repetição a partir dos parâmetros da linha
# RESULT). Convoluções e depthwise contam os MACs nominais, com os 9 taps de cada
# saída, inclusive os que caem no padding, como scope.md e kernels.md.
WORK: dict[str, tuple[str, Callable[[dict[str, int]], int]]] = {
    "conv3x3_direct": ("MAC", _conv_macs),
    "conv3x3_im2col": ("MAC", _conv_macs),
    "depthwise3x3": ("MAC", lambda p: p["H"] * p["W"] * 9 * p["C"]),
    "pointwise1x1": ("MAC", lambda p: p["H"] * p["W"] * p["Cin"] * p["Cout"]),
    "fc": ("MAC", lambda p: p["In"] * p["Out"]),
    "int8_base_example": ("MAC", lambda p: p["K"] * p["M"]),
    "maxpool2x2": ("elemento", lambda p: p["H"] * p["W"] * p["C"]),
    "requant_relu": ("elemento", lambda p: p["N"]),
}


_CONV = {
    "S": {"H": 16, "W": 16, "Cin": 8, "Cout": 16},
    "L": {"H": 32, "W": 32, "Cin": 16, "Cout": 32},
}
# Formas S e L de docs/scope.md, pelos parâmetros da linha RESULT (R não entra):
# os mesmos argumentos de experiments/<operação>_{s,l}.yaml.
SIZES: dict[str, dict[str, dict[str, int]]] = {
    "conv3x3_direct": _CONV,
    "conv3x3_im2col": _CONV,
    "depthwise3x3": {"S": {"H": 16, "W": 16, "C": 32}, "L": {"H": 32, "W": 32, "C": 64}},
    "pointwise1x1": {
        "S": {"H": 16, "W": 16, "Cin": 32, "Cout": 32},
        "L": {"H": 32, "W": 32, "Cin": 64, "Cout": 64},
    },
    "maxpool2x2": {"S": {"H": 32, "W": 32, "C": 16}, "L": {"H": 64, "W": 64, "C": 32}},
    "requant_relu": {"S": {"N": 4096}, "L": {"N": 32768}},
    "fc": {"S": {"In": 512, "Out": 32}, "L": {"In": 1024, "Out": 512}},
}


def size_of(bench: str | None, params: dict[str, int]) -> str | None:
    """S ou L, se os parâmetros (sem R) são uma das formas do escopo; senão None."""
    shape = {key: value for key, value in params.items() if key != "R"}
    for size, expected in SIZES.get(bench or "", {}).items():
        if shape == expected:
            return size
    return None


@dataclass(frozen=True)
class Ratio:
    """Métrica `scale · numerator / denominator`.

    Os operandos são chaves do parser (METRICS), de `repetitions`, `work` e
    `work_total` ou, nos pares, das duas execuções (`a.` base, `b.` outra).
    Nas unidades, "MAC" vira "elemento" no pooling e na requantização.
    """

    key: str
    unit: str
    description: str
    numerator: str
    denominator: str
    scale: int = 1

    @property
    def formula(self) -> str:
        scale = f"{self.scale} · " if self.scale != 1 else ""
        return f"{scale}{self.numerator} / {self.denominator}"


DERIVED: tuple[Ratio, ...] = (
    Ratio("cpi", "ciclos/inst", "Ciclos por instrução", "cycles", "insts"),
    Ratio(
        "l1i_mpki", "faltas/kinst", "Faltas na L1i por mil instruções", "l1i_misses", "insts", 1000
    ),
    Ratio(
        "l1d_mpki", "faltas/kinst", "Faltas na L1d por mil instruções", "l1d_misses", "insts", 1000
    ),
    Ratio("l2_mpki", "faltas/kinst", "Faltas na L2 por mil instruções", "l2_misses", "insts", 1000),
    Ratio("insts_per_rep", "instruções", "Instruções por repetição", "insts", "repetitions"),
    Ratio("ops_per_rep", "micro-ops", "Micro-operações por repetição", "ops", "repetitions"),
    Ratio("cycles_per_rep", "ciclos", "Ciclos por repetição", "cycles", "repetitions"),
    Ratio("insts_per_work", "inst/MAC", "Instruções por MAC", "insts", "work_total"),
    Ratio("cycles_per_work", "ciclos/MAC", "Ciclos por MAC", "cycles", "work_total"),
    Ratio("work_per_cycle", "MACs/ciclo", "MACs por ciclo", "work_total", "cycles"),
)
# Quantidades de base das razões, também mostradas por execução.
BASE_UNITS = {"repetitions": "repetições", "work": "MACs", "work_total": "MACs"}
BASE_DESCRIPTIONS = {
    "repetitions": "Repetições do kernel na ROI (R)",
    "work": "MACs de uma repetição (nominais)",
    "work_total": "MACs da ROI: work · repetitions",
}

PAIR_RATIOS: tuple[Ratio, ...] = (
    Ratio("r_i", "×", "Redução de instruções", "a.insts", "b.insts"),
    Ratio("r_i_ops", "×", "Redução de micro-operações", "a.ops", "b.ops"),
    Ratio("s_c", "×", "Speedup em ciclos", "a.cycles", "b.cycles"),
    Ratio("ipc_ratio", "×", "IPC de b ÷ IPC de a (S_C = R_I · ipc_ratio)", "s_c", "r_i"),
)


def unit_for(unit: str, work_unit: str | None) -> str:
    """Troca "MAC" pela unidade da operação (elemento no pooling e na requantização)."""
    if work_unit == "elemento":
        return unit.replace("MACs", "elementos").replace("MAC", "elemento")
    return unit


def _ratios(
    ratios: tuple[Ratio, ...], values: dict[str, Value], reasons: dict[str, str]
) -> tuple[dict[str, Value], dict[str, str]]:
    """Calcula as razões em ordem; cada uma pode usar as anteriores."""
    values = dict(values)
    out: dict[str, Value] = {}
    missing: dict[str, str] = {}
    for ratio in ratios:
        numerator, denominator = values.get(ratio.numerator), values.get(ratio.denominator)
        if numerator is None:
            missing[ratio.key] = reasons.get(ratio.numerator, f"{ratio.numerator} ausente")
        elif denominator is None:
            missing[ratio.key] = reasons.get(ratio.denominator, f"{ratio.denominator} ausente")
        elif denominator == 0:
            missing[ratio.key] = f"indefinida: {ratio.denominator} = 0"
        else:
            out[ratio.key] = ratio.scale * numerator / denominator
        values[ratio.key] = out.get(ratio.key)
        if ratio.key in missing:
            reasons = {**reasons, ratio.key: missing[ratio.key]}
    return {ratio.key: out.get(ratio.key) for ratio in ratios}, missing


def _work(result: Result | None) -> tuple[dict[str, Value], dict[str, str], str | None]:
    """Repetições e trabalho (MACs ou elementos) a partir da linha RESULT."""
    values: dict[str, Value] = {"repetitions": None, "work": None, "work_total": None}
    if result is None:
        reason = "o programa não imprimiu a linha RESULT"
        return values, dict.fromkeys(values, reason), None
    if result.bench is None:
        reason = "o benchmark não usa a base comum (sem bench= na linha RESULT)"
        return values, dict.fromkeys(values, reason), None
    missing: dict[str, str] = {}
    params = result.params
    values["repetitions"] = params.get("R")
    if values["repetitions"] is None:
        missing["repetitions"] = "a linha RESULT não tem R"
    unit = None
    if result.bench not in WORK:
        missing["work"] = f"sem contagem de MACs para {result.bench}"
    else:
        unit, formula = WORK[result.bench]
        try:
            values["work"] = formula(params)
        except KeyError as error:
            missing["work"] = f"a linha RESULT não tem {error.args[0]}"
    if values["work"] is not None and values["repetitions"] is not None:
        values["work_total"] = values["work"] * values["repetitions"]
    else:
        missing["work_total"] = missing.get("work") or missing["repetitions"]
    return values, missing, unit


@dataclass(frozen=True)
class RunMetrics:
    """Métricas brutas (stats) e derivadas de uma execução, com a linha RESULT."""

    run: Run
    stats: RegionStats
    result: Result | None
    derived: dict[str, Value]
    missing: dict[str, str]
    work_unit: str | None

    @property
    def problem(self) -> str | None:
        """Por que a execução não entra nas comparações; None se ela pode entrar."""
        status = self.run.metadata.get("status")
        if status != "completed":
            return f"execução não concluída (status {status})"
        result = self.result
        if result is None:
            return "o programa não imprimiu a linha RESULT"
        if result.bench is None or result.variant is None:
            return "o benchmark não usa a base comum (sem bench= e variant= na linha RESULT)"
        if result.checksum is None or result.mismatches is None:
            return "linha RESULT sem checksum ou mismatches"
        if result.mismatches:
            return f"resultado incorreto (mismatches={result.mismatches})"
        return None

    @property
    def variant(self) -> str:
        return (self.result.variant if self.result else None) or "?"

    @property
    def flags(self) -> list[str]:
        """Flags do experimento; sem a seção `compiler`, o padrão do YAML (-O2)."""
        compiler = self.run.resolved.get("compiler")
        return list(compiler["flags"] if compiler else CompilerConfig().flags)

    @property
    def optimization(self) -> str:
        """Nível de otimização: o último -O* das flags, como no GCC; -O0 se não há."""
        levels = [flag for flag in self.flags if OPTIMIZATION.match(flag)]
        return levels[-1] if levels else "-O0"

    def scenario(self) -> dict[str, Any]:
        """O que identifica a execução numa comparação. Os parâmetros vêm da linha
        RESULT (valores usados de fato, inclusive padrões), não de benchmark.args."""
        resolved = self.run.resolved
        result = self.result or Result({})
        return {
            "bench": result.bench,
            "params": result.params,
            "data": result.data,
            "variant": result.variant,
            "flags": self.flags,
            "cpu": dict(resolved.get("cpu") or {}),
            "cache": resolved.get("cache"),
            "memory": resolved.get("memory"),
            "cache_state": (resolved.get("benchmark") or {}).get("cache_state", "warm"),
            "gem5": self.run.metadata.get("gem5_sha256"),
        }


def derive(stats: RegionStats, result: Result | None) -> tuple[dict, dict, str | None]:
    """Métricas derivadas de uma execução, o motivo das ausentes e a unidade do trabalho."""
    base, base_missing, unit = _work(result)
    values = {**stats.metrics, **base}
    reasons = {**stats.missing, **base_missing}
    ratios, ratio_missing = _ratios(DERIVED, values, reasons)
    return {**base, **ratios}, {**base_missing, **ratio_missing}, unit


def load_metrics(run: Run) -> RunMetrics:
    """Métricas de uma execução; StatsError se o stats.txt não pôde ser lido."""
    stats = region_stats(run)
    result = parse_result(read_text(run.path / "stdout.log"))
    derived, missing, unit = derive(stats, result)
    return RunMetrics(run, stats, result, derived, missing, unit)


@dataclass(frozen=True)
class Pair:
    """Comparação da execução `a` (base) com `b`.

    `kind` é `variante` (mesmo cenário, variantes diferentes) ou `compilador`
    (mesma variante, nível de otimização diferente, base -O2). Um par com
    `problem` foi rejeitado e não tem valores.
    """

    kind: str
    a: RunMetrics
    b: RunMetrics
    values: dict[str, Value]
    missing: dict[str, str]
    problem: str | None = None

    @property
    def label(self) -> str:
        if self.kind == "compilador":
            return f"{self.a.variant}({self.a.optimization}→{self.b.optimization})"
        sides = []
        for item in (self.a, self.b):
            cpu = item.run.resolved.get("cpu") or {}
            vlen = cpu.get("vlen", DEFAULT_VLEN)
            qualifier = custom_qualifier(cpu)
            if item.variant == "rvv" and vlen != DEFAULT_VLEN:
                sides.append(f"rvv@vlen{vlen}")
            elif item.variant == "custom" and qualifier:
                sides.append(f"custom@{qualifier}")
            else:
                sides.append(item.variant)
        optimization = self.a.optimization
        suffix = f"({optimization})" if optimization != BASE_OPTIMIZATION else ""
        return "→".join(sides) + suffix


@dataclass(frozen=True)
class Comparison:
    """Pares formados (aceitos e rejeitados), execuções fora da comparação com o
    motivo e execuções repetidas que foram substituídas pela mais recente."""

    pairs: list[Pair]
    excluded: list[tuple[Path, str]]
    superseded: list[Path]


def _key(item: RunMetrics, drop: set[tuple[str, str]], axis: str | None = None) -> str:
    scenario = item.scenario()
    for section, name in drop:
        scenario[section].pop(name, None)
    if axis == "variant":
        scenario.pop("variant")
    elif axis == "optimization":
        scenario["flags"] = [flag for flag in scenario["flags"] if not OPTIMIZATION.match(flag)]
    return json.dumps(scenario, sort_keys=True)


def _pair(kind: str, a: RunMetrics, b: RunMetrics) -> Pair:
    assert a.result and b.result
    if a.result.checksum != b.result.checksum:
        problem = (
            f"checksums diferentes: {a.result.checksum} ({a.variant} {a.optimization}) × "
            f"{b.result.checksum} ({b.variant} {b.optimization})"
        )
        return Pair(kind, a, b, {}, {}, problem)
    values: dict[str, Value] = {}
    reasons: dict[str, str] = {}
    for prefix, item in (("a", a), ("b", b)):
        for key, value in item.stats.metrics.items():
            values[f"{prefix}.{key}"] = value
        for key, reason in item.stats.missing.items():
            reasons[f"{prefix}.{key}"] = reason
    ratios, missing = _ratios(PAIR_RATIOS, values, reasons)
    return Pair(kind, a, b, ratios, missing)


def compare(items: list[RunMetrics], excluded: list[tuple[Path, str]] | None = None) -> Comparison:
    """Forma os pares de variantes e de compilador entre execuções válidas."""
    excluded = list(excluded or [])
    excluded += [(item.run.path, item.problem) for item in items if item.problem]
    valid = [item for item in items if not item.problem]

    # Execuções repetidas (mesma identidade): vale a mais recente.
    latest: dict[str, RunMetrics] = {}
    superseded: list[Path] = []
    for item in sorted(valid, key=lambda item: item.run.metadata.get("run_id") or ""):
        key = _key(item, IRRELEVANT.get(item.variant, set()))
        if key in latest:
            superseded.append(latest[key].run.path)
        latest[key] = item
    runs = list(latest.values())

    pairs: list[Pair] = []
    for base, other in VARIANT_PAIRS:
        drop = IRRELEVANT[base] | IRRELEVANT[other]
        others = [item for item in runs if item.variant == other]
        for a in (item for item in runs if item.variant == base):
            key = _key(a, drop, "variant")
            pairs += [_pair("variante", a, b) for b in others if _key(b, drop, "variant") == key]
    for a in (item for item in runs if item.optimization == BASE_OPTIMIZATION):
        drop = IRRELEVANT.get(a.variant, set())
        key = _key(a, drop, "optimization")
        pairs += [
            _pair("compilador", a, b)
            for b in runs
            if b.optimization != BASE_OPTIMIZATION and _key(b, drop, "optimization") == key
        ]
    pairs.sort(
        key=lambda pair: (pair.kind == "compilador", _key(pair.a, set(), "variant"), pair.label)
    )
    return Comparison(pairs, excluded, superseded)


def collect(root: Path) -> tuple[list[RunMetrics], list[tuple[Path, str]]]:
    """Métricas das execuções concluídas sob `root` e as que ficaram de fora, com o motivo."""
    items: list[RunMetrics] = []
    excluded: list[tuple[Path, str]] = []
    for run in list_runs(root):
        status = run.metadata.get("status")
        if status != "completed":
            excluded.append((run.path, f"execução não concluída (status {status})"))
            continue
        try:
            items.append(load_metrics(run))
        except StatsError as error:
            excluded.append((run.path, str(error)))
    return items, excluded


def parameters_label(item: RunMetrics) -> str:
    """Parâmetros da linha RESULT e o conjunto de dados, se não for o padrão."""
    result = item.result
    params = ",".join(f"{key}={value}" for key, value in (result.params if result else {}).items())
    data = result.data if result else None
    return params + (f",data={data}" if data and data != "random" else "")


def custom_qualifier(cpu: dict) -> str:
    """O que muda nas unidades da custom, como lat6, 2u (unidades próprias) e np
    (sem pipeline), juntos por "+"; vazio com os padrões. Usado nos rótulos de
    pares, séries e nomes de combinação."""
    parts = []
    latency = cpu.get("custom_latency", MUL_LATENCY)
    if latency not in (None, "") and int(latency) != MUL_LATENCY:
        parts.append(f"lat{latency}")
    if cpu.get("custom_units") not in (None, ""):
        parts.append(f"{cpu['custom_units']}u")
    if cpu.get("custom_pipelined") in (False, "false"):
        parts.append("np")
    return "+".join(parts)


# Ajustes das caches (RCB-32) e o nome curto de cada um no rótulo do cenário.
CACHE_TUNING = (("latency", "lat"), ("mshrs", "mshrs"), ("targets", "tgts"), ("prefetcher", "pf"))


def cache_tuning(resolved: dict) -> str:
    """Os ajustes das caches que não são o padrão, como line=128,l1d.pf=stride.

    A configuração resolvida só tem esses campos quando mudam (config.CacheConfig).
    """
    cache = resolved.get("cache") or {}
    parts = [f"line={cache['line']}"] if cache.get("line") else []
    for level in ("l1i", "l1d", "l2"):
        values = cache.get(level) or {}
        parts += [
            f"{level}.{short}={values[key]}"
            for key, short in CACHE_TUNING
            if values.get(key) not in (None, "none")
        ]
    return ",".join(parts)


def scenario_label(resolved: dict, tuning: str | None = None) -> str:
    """Caches e memória numa palavra só: o nome do cenário, como l1-l2, ou os
    tamanhos, como l1i=32KiB,l1d=32KiB,ddr4, mais os ajustes das caches que não são
    o padrão (`tuning`, por padrão os da própria configuração); com caches frias,
    mais ",cold"."""
    if resolved.get("scenario"):
        label = resolved["scenario"]
    else:
        cache = resolved.get("cache") or {}
        levels = [
            f"{level}={cache[level]['size']}" for level in ("l1i", "l1d", "l2") if cache.get(level)
        ]
        memory = (resolved.get("memory") or {}).get("type", "?")
        extra = cache_tuning(resolved) if tuning is None else tuning
        label = ",".join([*(levels or ["sem-cache"]), memory, *([extra] if extra else [])])
    cold = (resolved.get("benchmark") or {}).get("cache_state") == "cold"
    return label + (",cold" if cold else "")
