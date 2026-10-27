"""Gerador de experimentos em HTML (RCB-31).

`write_page` grava uma página autônoma (sem servidor nem internet) para montar o
YAML de um experimento, ou a matriz de uma campanha, sem escrevê-lo à mão. As
opções vêm do código: operações e variantes de benchmarks/, tamanhos S e L de
experiments/, cenários de configs/scenarios.yaml, CPUs, VLEN e latências do
config.py. A lógica da página fica em web/gerador.js (funções puras testadas com o
QuickJS); com execuções medidas, a página estima o tempo pelo mesmo modelo do
`campaign estimate`. Doc: docs/generator.md.
"""

import json
import re
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

import yaml

from riscvcnnbench import __version__
from riscvcnnbench.config import (
    CACHE_LATENCY,
    CACHE_LINE,
    CACHE_MSHRS,
    CACHE_TARGETS,
    CLOCK_PATTERN,
    FORMAT_HINTS,
    MUL_LATENCY,
    NAME_PATTERN,
    NO_PREFETCHER,
    PROJECT_ROOT,
    SIZE_PATTERN,
    BenchmarkConfig,
    CacheConfig,
    CacheLevelConfig,
    CompilerConfig,
    CpuConfig,
    MemoryConfig,
    available_variants,
    load_scenarios,
    size_bytes,
)
from riscvcnnbench.estimate import fit, samples
from riscvcnnbench.metric import scenario_label
from riscvcnnbench.plot import OPERATIONS
from riscvcnnbench.runs import display

WEB_DIR = Path(__file__).parent / "web"
BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
DATA_HEADER = BENCHMARKS_DIR / "common" / "rcb_data.h"
# Memória personalizada começa igual ao cenário de referência.
CUSTOM_BASE = "l1-l2"
SIZES = ("S", "L")
FLAGS = ("-O2", "-O3")
# Latências oferecidas: a do mul e a pessimista da matriz final (docs/scenarios.md).
LATENCIES = {MUL_LATENCY: "igual à do mul (padrão)", 2 * MUL_LATENCY: "o dobro (pessimista)"}
# Unidades próprias oferecidas para as instruções personalizadas (RCB-33).
UNIT_OPTIONS = (1, 2, 4)

CPU_DESCRIPTIONS = {
    "atomic": "só confere o resultado, sem ciclos (rápida)",
    "timing": "uma instrução por vez, com o tempo da memória",
    "minor": "em ordem, com pipeline",
    "o3-edge": "fora de ordem estreita, de borda (MediumBOOM)",
    "o3": "fora de ordem larga, padrão do gem5",
}
VARIANTS = {
    "ref": ("ref", "código escalar de referência (rv64gc)"),
    "custom": ("custom", "instruções personalizadas (cnn.dot8 e outras)"),
    "rvv": ("rvv", "extensão vetorial V (RVV 1.0)"),
}
NO_SCENARIO = "sem caches e memória simple, o padrão; serve para a CPU atomic"
DATASET_DETAILS = {
    "random": "aleatórios na faixa de cada tensor (padrão, usado nas medições)",
    "satpos": "extremos: os acumuladores saturam em 127 (validação)",
    "satneg": "extremos negativos: o ReLU dá 0 (validação)",
}
DATASET = re.compile(r'RCB_DATA == (\d+)\s*\n#define RCB_DATA_NAME "(\w+)"')

# Bytes que a operação lê e escreve na região de interesse, pelos argumentos de
# experiments/ (entrada, pesos, bias, saída e o buffer da im2col), como em
# docs/scenarios.md, "O que cabe em cada nível".
Footprint = Callable[[list[int]], int]
FOOTPRINT: dict[str, Footprint] = {
    "conv3x3_direct": lambda a: (
        a[0] * a[1] * a[2] + 9 * a[2] * a[3] + 4 * a[3] + a[0] * a[1] * a[3]
    ),
    "conv3x3_im2col": lambda a: (
        a[0] * a[1] * a[2]
        + 9 * a[2] * a[3]
        + 4 * a[3]
        + a[0] * a[1] * a[3]
        + 9 * a[0] * a[1] * a[2]
    ),
    "depthwise3x3": lambda a: 2 * a[0] * a[1] * a[2] + 9 * a[2] + 4 * a[2],
    "pointwise1x1": lambda a: a[0] * a[1] * a[2] + a[2] * a[3] + 4 * a[3] + a[0] * a[1] * a[3],
    "maxpool2x2": lambda a: a[0] * a[1] * a[2] + (a[0] // 2) * (a[1] // 2) * a[2],
    "requant_relu": lambda a: 5 * a[0],
    "fc": lambda a: a[0] + a[0] * a[1] + 4 * a[1] + a[1],
}
ARG_NAMES = re.compile(r"#\s*args:\s*\[([^\]]*)\]")


class GeneratorError(Exception):
    """Saída que já existe ou pasta de medições ausente."""


def _choices(model: type, field: str) -> list[Any]:
    return list(get_args(model.model_fields[field].annotation))


def operations() -> list[dict[str, Any]]:
    """As operações com experimentos S e L em experiments/, na ordem dos gráficos."""
    known = list(OPERATIONS)
    names = sorted(
        {path.stem.rsplit("_", 1)[0] for path in EXPERIMENTS_DIR.glob("*_[sl].yaml")},
        key=lambda name: (known.index(name) if name in known else len(known), name),
    )
    found = []
    for name in names:
        folder = BENCHMARKS_DIR / name
        if not (folder / "Makefile").is_file():
            continue
        sizes = {}
        for size in SIZES:
            path = EXPERIMENTS_DIR / f"{name}_{size.lower()}.yaml"
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text) or {}
            benchmark = data.get("benchmark") or {}
            if benchmark.get("name") != name or set(data) - {"name", "description", "benchmark"}:
                continue
            args = [int(arg) for arg in benchmark.get("args", [])]
            match = ARG_NAMES.search(text)
            footprint = FOOTPRINT.get(name)
            sizes[size] = {
                "experiment": data["name"],
                "args": args,
                "names": [n.strip() for n in match.group(1).split(",")] if match else [],
                "bytes": footprint(args) if footprint else None,
            }
        if sizes:
            label = OPERATIONS.get(name, name).replace("\n", " ")
            found.append(
                {"id": name, "label": label, "variants": available_variants(folder), "sizes": sizes}
            )
    return found


def scenarios() -> list[dict[str, Any]]:
    """Os cenários nomeados e, em primeiro, a opção sem cenário."""
    found = [{"id": "", "description": NO_SCENARIO, "l1d": None, "l2": None, "memory": "simple"}]
    for name, scenario in load_scenarios().items():
        cache = scenario.cache
        found.append(
            {
                "id": name,
                "description": " ".join(scenario.description.split()),
                "l1d": size_bytes(cache.l1d.size) if cache.l1d else None,
                "l2": size_bytes(cache.l2.size) if cache.l2 else None,
                "memory": scenario.memory.type,
            }
        )
    return found


def datasets() -> list[dict[str, Any]]:
    """Os conjuntos de dados de rcb_data.h (-DRCB_DATA=<n>); o 0 é o padrão, sem flag."""
    found = []
    for number, name in DATASET.findall(DATA_HEADER.read_text(encoding="utf-8")):
        flag = None if number == "0" else f"-DRCB_DATA={number}"
        found.append({"id": name, "flag": flag, "detail": DATASET_DETAILS.get(name, "")})
    return found


def memory_options() -> dict[str, Any]:
    default = MemoryConfig()
    base = load_scenarios()[CUSTOM_BASE]
    levels = {
        level: {
            "size": getattr(base.cache, level).size,
            "assoc": getattr(base.cache, level).assoc,
            "latency": CACHE_LATENCY[level],
            "mshrs": CACHE_MSHRS,
            "targets": CACHE_TARGETS,
        }
        for level in ("l1i", "l1d", "l2")
    }
    fields = CacheLevelConfig.model_fields
    bounds = {
        name: {
            type(m).__name__: getattr(m, type(m).__name__.lower()) for m in fields[name].metadata
        }
        for name in ("latency", "mshrs", "targets")
    }
    # cache.line é Literal[...] | None: as opções estão no Literal.
    literal = next(arg for arg in _choices(CacheConfig, "line") if get_args(arg))
    line_options = list(get_args(literal))
    return {
        "default": {"type": default.type, "size": default.size},
        "types": _choices(MemoryConfig, "type"),
        "line": CACHE_LINE,
        "lines": sorted(line_options),
        "prefetchers": _choices(CacheLevelConfig, "prefetcher"),
        "noPrefetcher": NO_PREFETCHER,
        "bounds": {name: [b["Ge"], b["Le"]] for name, b in bounds.items()},
        "custom": {**levels, "type": base.memory.type},
    }


def estimate_data(roots: list[Path]) -> dict[str, Any] | None:
    """W por binário e a reta a + b · W por CPU, clock e cenário, das execuções medidas."""
    found = samples(roots)
    if not found:
        return None
    works: dict[str, float] = {}
    points: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    for sample in found:
        works[_binary(sample.binary)] = sample.work
        points[sample.speed].append((sample.work, sample.seconds))
    fits = {}
    for speed, values in points.items():
        line = fit(values)
        if line:
            fits["|".join(speed)] = [line.a, line.b, line.low, line.high, line.points]
    return {"works": works, "fits": fits, "samples": len(found)}


def _binary(key: tuple) -> str:
    """A chave de `estimate.binary_key` no formato de `RCB.binaryKey` (gerador.js)."""
    name, args, variant, flags, vlen = key
    return "|".join(
        [name, ",".join(args), variant, " ".join(flags), "" if vlen is None else str(vlen)]
    )


def page_data(measured: list[Path] | None = None) -> dict[str, Any]:
    cpu_models = _choices(CpuConfig, "model")
    latency = CpuConfig.model_fields["custom_latency"]
    bounds = {type(m).__name__: m for m in latency.metadata}
    no_scenario = scenario_label({"memory": {"type": "simple"}})
    return {
        "version": __version__,
        "ops": operations(),
        "variants": [
            {"value": v, "title": VARIANTS[v][0], "detail": VARIANTS[v][1]}
            for v in _choices(BenchmarkConfig, "variant")
        ],
        "cpus": [
            {
                "id": model,
                "description": CPU_DESCRIPTIONS.get(model, ""),
                "latency": model not in ("atomic", "timing"),
            }
            for model in sorted(cpu_models, key=lambda m: list(CPU_DESCRIPTIONS).index(m))
        ],
        "scenarios": scenarios(),
        "noScenarioLabel": no_scenario,
        "memory": memory_options(),
        "datasets": datasets(),
        "latency": {
            "default": MUL_LATENCY,
            "min": bounds["Ge"].ge,
            "max": bounds["Le"].le,
            "options": [{"value": value, "detail": text} for value, text in LATENCIES.items()],
        },
        "units": {
            "options": [None, *UNIT_OPTIONS],
            "default": "1 própria na minor; dividida com o mul nas O3",
            "max": {type(m).__name__: m for m in CpuConfig.model_fields["custom_units"].metadata}[
                "Le"
            ].le,
        },
        "vlen": {"default": CpuConfig().vlen, "options": _choices(CpuConfig, "vlen")},
        "flags": {"default": CompilerConfig().flags[0], "options": list(FLAGS)},
        "clock": {"default": CpuConfig().clock},
        "patterns": {"name": NAME_PATTERN, "clock": CLOCK_PATTERN, "size": SIZE_PATTERN},
        "hints": {
            "name": FORMAT_HINTS[NAME_PATTERN],
            "clock": FORMAT_HINTS[CLOCK_PATTERN],
            "size": FORMAT_HINTS[SIZE_PATTERN],
        },
        "estimate": estimate_data(measured) if measured else None,
    }


def script() -> str:
    return (WEB_DIR / "gerador.js").read_text(encoding="utf-8")


def render(data: dict[str, Any]) -> str:
    """A página com os dados e o script embutidos."""
    template = (WEB_DIR / "gerador.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("__RCB_DATA__", payload).replace("__RCB_SCRIPT__", script())


def write_page(output: Path, measured: list[Path] | None = None, force: bool = False) -> dict:
    """Grava a página em `output`; devolve os dados embutidos."""
    for root in measured or []:
        if not root.is_dir():
            raise GeneratorError(f"pasta não encontrada: {display(root)}")
    if output.exists() and not force:
        raise GeneratorError(f"já existe {display(output)}; use --force para regravar")
    data = page_data(measured)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(data), encoding="utf-8")
    return data
