"""Gráficos de comparação (RCB-21).

Lê runs.csv e pairs.csv do report (RCB-20) e grava três tipos de figura, em PDF
(vetorial, para o LaTeX) e PNG (300 dpi), prontas para a monografia: sem título
(a legenda vem do LaTeX), com hachuras e marcadores além da cor, para serem
legíveis em preto e branco, e com vírgula decimal.

- variantes: instruções e ciclos por unidade de trabalho e IPC por operação, uma
  barra por variante; uma figura por tamanho, CPU e cenário de memória;
- speedup: S_C por operação, uma barra por cenário de memória, um painel por CPU;
  uma figura por par e tamanho;
- ri_sc: R_I contra S_C com a diagonal S_C = R_I, um marcador por operação, um
  tom e um tamanho por cenário, um painel por CPU; uma figura por par e tamanho.

Entram só as execuções que valem (sem `problem`, `current`, checksum consistente)
e os pares aceitos, sempre com ciclos: a CPU atomic fica de fora. Os CSVs lidos
são copiados para a pasta das figuras, com figures.json: o contexto de cada
figura, as execuções usadas e uma legenda sugerida. Doc: docs/plots.md.
"""

import csv
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter

from riscvcnnbench import __version__
from riscvcnnbench.config import MUL_LATENCY, load_scenarios
from riscvcnnbench.metric import DEFAULT_VLEN, scenario_label
from riscvcnnbench.report import PAIRS_FILE, RUNS_FILE
from riscvcnnbench.runs import display

MANIFEST = "figures.json"
FORMATS = ("pdf", "png")
DPI = 300
# 16 cm: a largura do texto numa página A4 com as margens da ABNT (3 cm e 2 cm).
WIDTH = 16 / 2.54
# Valores que não entram no nome da figura nem na legenda sugerida.
BASE = {"clock": "1GHz", "flags": "-O2", "data": "random"}
NO_SIZE = "sem-tamanho"

# Ordem das operações nos gráficos e rótulo no eixo.
OPERATIONS = {
    "conv3x3_direct": "conv 3×3\ndireta",
    "conv3x3_im2col": "conv 3×3\nim2col",
    "depthwise3x3": "depthwise\n3×3",
    "pointwise1x1": "pointwise\n1×1",
    "maxpool2x2": "maxpool\n2×2",
    "requant_relu": "requant\n+ReLU",
    "fc": "FC",
}
VARIANTS = {"ref": "Referência", "custom": "Personalizada", "rvv": "RVV"}
VARIANT_HATCHES = {"ref": "", "custom": "///", "rvv": "..."}
# Latência ou VLEN fora do padrão: hachuras próprias de cada variante.
QUALIFIER_HATCHES = {"custom": ("xxx", "+++"), "rvv": ("\\\\\\", "ooo")}
HATCHES = ("", "///", "...", "xxx", "\\\\\\", "+++", "ooo", "---")
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "h", "*", "<", ">")
CPUS = ("timing", "minor", "o3-edge", "o3")

# Painéis da figura de variantes: coluna do runs.csv e rótulo do eixo.
VARIANT_PANELS = (
    ("insts_per_work", "Instruções por MAC"),
    ("cycles_per_work", "Ciclos por MAC"),
    ("ipc", "IPC (instruções\npor ciclo)"),
)

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
    "cycles",
    "ipc",
    "insts_per_work",
    "cycles_per_work",
)
PAIR_NEEDS = (
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
)

STYLE = {
    "font.size": 9,
    "axes.labelsize": 9,
    "axes.titlesize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "legend.title_fontsize": 8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.axisbelow": True,
    "hatch.linewidth": 0.6,
    # Fontes TrueType embutidas no PDF (texto selecionável e editável).
    "pdf.fonttype": 42,
}


class PlotError(Exception):
    """Problema que impede gerar as figuras."""


@dataclass
class Plot:
    """Uma figura e o que vai para o figures.json."""

    name: str
    kind: str
    figure: Figure
    entry: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plots:
    """O que foi desenhado e de quais linhas, para o resumo da CLI."""

    kinds: Counter
    used_runs: int
    used_pairs: int
    skipped_runs: Counter
    skipped_pairs: Counter
    repeated: int
    output: Path | None = None


# Leitura e seleção -------------------------------------------------------------


def read_table(path: Path, needs: Iterable[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise PlotError(f"não encontrado: {display(path)}; gere os CSVs com riscvcnnbench report")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in needs if column not in (reader.fieldnames or [])]
        if missing:
            raise PlotError(
                f"{display(path)}: faltam as colunas {', '.join(missing)}; "
                "gere de novo com riscvcnnbench report"
            )
        return list(reader)


def run_skip(row: dict[str, str]) -> str | None:
    """Por que uma execução fica fora dos gráficos; None se entra."""
    if row["problem"]:
        return "inválida (problem)"
    if row["current"] != "true":
        return "substituída por outra mais recente"
    if row["checksum_consistent"] == "false":
        return "checksum divergente"
    if not row["cycles"]:
        return "sem ciclos (CPU atomic)"
    if not row["insts_per_work"]:
        return "sem unidade de trabalho"
    return None


def pair_skip(row: dict[str, str]) -> str | None:
    if row["problem"]:
        return "rejeitado"
    if not row["s_c"]:
        return "sem ciclos (CPU atomic)"
    return None


def select(
    rows: list[dict[str, str]], skip: Callable[[dict[str, str]], str | None]
) -> tuple[list[dict[str, str]], Counter]:
    chosen, skipped = [], Counter()
    for row in rows:
        reason = skip(row)
        if reason:
            skipped[reason] += 1
        else:
            chosen.append(row)
    return chosen, skipped


def run_scenario(row: dict[str, str]) -> str:
    """O mesmo rótulo de cenário do compare e do pairs.csv."""
    cache = {
        level: {"size": row[f"{level}_size"]}
        for level in ("l1i", "l1d", "l2")
        if row[f"{level}_size"]
    }
    return scenario_label(
        {
            "scenario": row["scenario"] or None,
            "cache": cache,
            "memory": {"type": row["memory"] or "?"},
            "benchmark": {"cache_state": row["cache_state"]},
        },
        # Coluna da RCB-32; um runs.csv anterior não a tem e não tem ajustes.
        tuning=row.get("cache_tuning") or "",
    )


def series_of(row: dict[str, str]) -> str:
    """Variante com a latência ou a VLEN quando não são as padrão, como no compare."""
    variant = row["variant"]
    if variant == "custom" and row["custom_latency"] and int(row["custom_latency"]) != MUL_LATENCY:
        return f"custom@lat{row['custom_latency']}"
    if variant == "rvv" and row["vlen"] and int(row["vlen"]) != DEFAULT_VLEN:
        return f"rvv@vlen{row['vlen']}"
    return variant


def series_label(series: str) -> str:
    variant, _, qualifier = series.partition("@")
    name = VARIANTS.get(variant, variant)
    if qualifier.startswith("lat"):
        return f"{name} (latência {qualifier[3:]})"
    if qualifier.startswith("vlen"):
        return f"{name} (VLEN {qualifier[4:]})"
    return name


# Ordens -------------------------------------------------------------------------


def ordered(values: Iterable[str], known: Iterable[str]) -> list[str]:
    known = list(known)
    return sorted(set(values), key=lambda v: (known.index(v) if v in known else len(known), v))


def series_order(values: Iterable[str]) -> list[str]:
    def key(series: str) -> tuple:
        variant, _, qualifier = series.partition("@")
        number = int(re.sub(r"\D", "", qualifier) or 0)
        rank = list(VARIANTS).index(variant) if variant in VARIANTS else len(VARIANTS)
        return (rank, variant, number, series)

    return sorted(set(values), key=key)


def scenario_order(values: Iterable[str]) -> list[str]:
    """Na ordem de configs/scenarios.yaml; rótulos com ",cold" logo depois do cenário."""
    known = list(load_scenarios())

    def key(label: str) -> tuple:
        base = label.split(",")[0]
        return (known.index(base) if base in known else len(known), label)

    return sorted(set(values), key=key)


# Estilo -------------------------------------------------------------------------


def palette(count: int, lighten: float) -> list[tuple[float, float, float]]:
    """Tons do viridis do claro para o escuro: a luminância cai sempre, e as cores
    continuam distintas em preto e branco. `lighten` mistura com branco, para a
    hachura preta aparecer sobre o tom mais escuro."""
    cmap = matplotlib.colormaps["viridis"]
    positions = [0.55] if count == 1 else [0.95 - 0.85 * i / (count - 1) for i in range(count)]
    return [tuple(lighten + (1 - lighten) * c for c in cmap(p)[:3]) for p in positions]


def variant_styles(series: list[str]) -> dict[str, tuple[Any, str]]:
    """Mesma cor e hachura para cada variante em todas as figuras: cor pela
    variante, hachura própria para a latência ou a VLEN não padrão."""
    colors = dict(zip(VARIANTS, palette(len(VARIANTS), 0.35), strict=True))
    styles, qualifiers, others = {}, Counter(), 0
    for name in series:
        variant, _, qualifier = name.partition("@")
        if variant not in VARIANTS:
            styles[name] = ("white", HATCHES[(others + 1) % len(HATCHES)])
            others += 1
        elif qualifier:
            hatches = QUALIFIER_HATCHES.get(variant, ("---",))
            styles[name] = (colors[variant], hatches[qualifiers[variant] % len(hatches)])
            qualifiers[variant] += 1
        else:
            styles[name] = (colors[variant], VARIANT_HATCHES[variant])
    return styles


def scenario_styles(scenarios: list[str]) -> dict[str, tuple[Any, str]]:
    colors = palette(len(scenarios), 0.35)
    return {name: (colors[i], HATCHES[i % len(HATCHES)]) for i, name in enumerate(scenarios)}


def decimal(value: float, _position: int | None = None) -> str:
    """Número com vírgula decimal, como no texto da monografia."""
    return f"{value:.6g}".replace(".", ",")


def log_ticks(low: float, high: float) -> list[float]:
    ticks: list[float] = []
    for steps in ((1, 2, 5), (1, 1.5, 2, 3, 5, 7)):
        exponents = range(math.floor(math.log10(low)), math.ceil(math.log10(high)) + 1)
        ticks = [s * 10.0**e for e in exponents for s in steps if low <= s * 10.0**e <= high]
        if len(ticks) >= 3:
            break
    return ticks


def operation_label(bench: str, unit: str | None = None) -> str:
    label = OPERATIONS.get(bench, bench)
    return label + ("\n(por elem.)" if unit == "elemento" else "")


def bars(
    ax: Axes,
    groups: list[str],
    series: list[str],
    values: dict[tuple[str, str], float],
    styles: dict[str, tuple[Any, str]],
) -> None:
    """Barras agrupadas: um grupo por item de `groups`, uma barra por série."""
    width = 0.8 / len(series)
    for index, name in enumerate(series):
        xs, heights = [], []
        for position, group in enumerate(groups):
            value = values.get((group, name))
            if value is not None:
                xs.append(position - 0.4 + width * (index + 0.5))
                heights.append(value)
        color, hatch = styles[name]
        ax.bar(xs, heights, width, color=color, hatch=hatch, edgecolor="black", linewidth=0.5)
    ax.set_xlim(-0.6, len(groups) - 0.4)
    ax.yaxis.set_major_formatter(FuncFormatter(decimal))
    ax.grid(axis="y", linewidth=0.4, color="0.85")


def legend_patches(names: list[str], styles: dict, label: Any = str) -> list[Patch]:
    return [
        Patch(facecolor=styles[n][0], hatch=styles[n][1], edgecolor="black", label=label(n))
        for n in names
    ]


# Figuras ------------------------------------------------------------------------


def variants_figure(points: dict[tuple[str, str], dict[str, str]]) -> Figure:
    """Instruções/MAC, ciclos/MAC e IPC por operação, uma barra por variante."""
    benches = ordered((bench for bench, _ in points), OPERATIONS)
    series = series_order(name for _, name in points)
    units = {bench: row["work_unit"] for (bench, _), row in points.items()}
    styles = variant_styles(series)
    figure = Figure(figsize=(WIDTH, 6.2), layout="constrained")
    axes = figure.subplots(len(VARIANT_PANELS), 1, sharex=True)
    for ax, (column, label) in zip(axes, VARIANT_PANELS, strict=True):
        values = {key: float(row[column]) for key, row in points.items() if row[column]}
        bars(ax, benches, series, values, styles)
        ax.set_ylabel(label)
    axes[-1].set_xticks(range(len(benches)), [operation_label(b, units[b]) for b in benches])
    figure.legend(
        handles=legend_patches(series, styles, series_label),
        loc="outside upper center",
        ncols=len(series),
        frameon=False,
    )
    return figure


def speedup_figure(points: dict[tuple[str, str, str], dict[str, str]]) -> Figure:
    """S_C por operação, uma barra por cenário de memória, um painel por CPU."""
    benches = ordered((bench for bench, _, _ in points), OPERATIONS)
    cpus = ordered((cpu for _, cpu, _ in points), CPUS)
    scenarios = scenario_order(scenario for _, _, scenario in points)
    styles = scenario_styles(scenarios)
    figure = Figure(figsize=(WIDTH, 0.9 + 1.9 * len(cpus)), layout="constrained")
    axes = figure.subplots(len(cpus), 1, sharex=True, sharey=True, squeeze=False)[:, 0]
    for ax, cpu in zip(axes, cpus, strict=True):
        values = {
            (bench, scenario): float(row["s_c"])
            for (bench, row_cpu, scenario), row in points.items()
            if row_cpu == cpu
        }
        bars(ax, benches, scenarios, values, styles)
        ax.axhline(1, color="black", linewidth=0.6, linestyle="--")
        ax.set_title(f"CPU {cpu}", loc="left")
        ax.set_ylabel("Speedup $S_C$ (×)")
    axes[-1].set_xticks(range(len(benches)), [operation_label(b) for b in benches])
    figure.legend(
        handles=legend_patches(scenarios, styles),
        title="Cenário de memória",
        loc="outside upper center",
        ncols=len(scenarios),
        frameon=False,
    )
    return figure


def ri_sc_figure(points: dict[tuple[str, str, str], dict[str, str]]) -> Figure:
    """R_I contra S_C em escala log, com a diagonal; um painel por CPU."""
    benches = ordered((bench for bench, _, _ in points), OPERATIONS)
    cpus = ordered((cpu for _, cpu, _ in points), CPUS)
    scenarios = scenario_order(scenario for _, _, scenario in points)
    colors = dict(zip(scenarios, palette(len(scenarios), 0.0), strict=True))
    # Cenários em tamanhos decrescentes, os menores por cima: pontos que coincidem
    # (a memória não mudou o ganho) aparecem como marcadores concêntricos.
    step = 50 / max(len(scenarios) - 1, 1)
    sizes = {scenario: 75 - step * i for i, scenario in enumerate(scenarios)}
    markers = {bench: MARKERS[i % len(MARKERS)] for i, bench in enumerate(benches)}
    values = [float(row[key]) for row in points.values() for key in ("r_i", "s_c")]
    low, high = min([*values, 1.0]) / 1.2, max([*values, 1.0]) * 1.2
    ticks = log_ticks(low, high)
    figure = Figure(figsize=(WIDTH, 3.4), layout="constrained")
    axes = figure.subplots(1, len(cpus), sharex=True, sharey=True, squeeze=False)[0]
    for ax, cpu in zip(axes, cpus, strict=True):
        ax.plot([low, high], [low, high], color="black", linewidth=0.7, linestyle="--")
        for (bench, row_cpu, scenario), row in points.items():
            if row_cpu == cpu:
                ax.scatter(
                    float(row["r_i"]),
                    float(row["s_c"]),
                    marker=markers[bench],
                    color=colors[scenario],
                    edgecolor="black",
                    linewidth=0.5,
                    s=sizes[scenario],
                    zorder=3 + scenarios.index(scenario),
                )
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(low, high)
        ax.set_ylim(low, high)
        ax.set_box_aspect(1)
        for axis in (ax.xaxis, ax.yaxis):
            axis.set_major_locator(FixedLocator(ticks))
            axis.set_major_formatter(FuncFormatter(decimal))
            axis.set_minor_formatter(NullFormatter())
        ax.grid(linewidth=0.4, color="0.85")
        ax.set_title(f"CPU {cpu}", loc="left")
        ax.set_xlabel("Redução de instruções $R_I$ (×)")
    axes[0].set_ylabel("Speedup $S_C$ (×)")
    diagonal = Line2D([], [], color="black", linewidth=0.7, linestyle="--", label="$S_C = R_I$")
    figure.legend(
        handles=[
            *(
                Line2D(
                    [],
                    [],
                    marker="o",
                    linestyle="",
                    markersize=math.sqrt(sizes[s]),
                    markerfacecolor=colors[s],
                    markeredgecolor="black",
                    markeredgewidth=0.5,
                    label=s,
                )
                for s in scenarios
            ),
            diagonal,
        ],
        title="Cenário de memória",
        loc="outside upper center",
        ncols=len(scenarios) + 1,
        frameon=False,
    )
    figure.legend(
        handles=[
            Line2D(
                [],
                [],
                marker=markers[bench],
                linestyle="",
                markerfacecolor="white",
                markeredgecolor="black",
                label=OPERATIONS.get(bench, bench).replace("\n", " "),
            )
            for bench in benches
        ],
        loc="outside lower center",
        ncols=min(len(benches), 4),
        frameon=False,
    )
    return figure


# Agrupamento --------------------------------------------------------------------


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._]+", "-", text).strip("-")


def extras(context: dict[str, str]) -> list[str]:
    """Clock, flags e dados quando não são os da base."""
    return [context[key] for key in BASE if context.get(key) and context[key] != BASE[key]]


def extras_text(context: dict[str, str]) -> str:
    names = {"clock": "clock", "flags": "flags", "data": "dados"}
    return "".join(
        f", {names[key]} {context[key]}"
        for key in BASE
        if context.get(key) and context[key] != BASE[key]
    )


def size_text(size: str) -> str:
    return "fora de S e L" if size == NO_SIZE else size


def group_runs(rows: list[dict[str, str]]) -> tuple[dict[tuple, dict], int]:
    """Execuções por figura de variantes; no mesmo ponto, vale a mais recente."""
    groups: dict[tuple, dict[tuple[str, str], dict[str, str]]] = {}
    repeated = 0
    for row in rows:
        context = {
            "size": row["size"] or NO_SIZE,
            "cpu": row["cpu"],
            "scenario": run_scenario(row),
            "clock": row["clock"],
            "flags": row["flags"],
            "data": row["data"],
        }
        points = groups.setdefault(tuple(context.items()), {})
        point = (row["bench"], series_of(row))
        if point in points:
            repeated += 1
            if row["run_id"] < points[point]["run_id"]:
                continue
        points[point] = row
    return groups, repeated


def group_pairs(rows: list[dict[str, str]]) -> tuple[dict[tuple, dict], int]:
    """Pares por figura de speedup e de R_I × S_C; no mesmo ponto, vale o mais recente."""
    groups: dict[tuple, dict[tuple[str, str, str], dict[str, str]]] = {}
    repeated = 0
    for row in rows:
        context = {
            "pair": row["pair"],
            "size": row["size"] or NO_SIZE,
            "clock": row["clock"],
            "flags": row["flags_a"],
            "data": row["data"],
        }
        points = groups.setdefault(tuple(context.items()), {})
        point = (row["bench"], row["cpu"], row["scenario"])
        if point in points:
            repeated += 1
            latest = max(points[point]["run_id_a"], points[point]["run_id_b"])
            if max(row["run_id_a"], row["run_id_b"]) < latest:
                continue
        points[point] = row
    return groups, repeated


def variant_plot(context: dict[str, str], points: dict) -> Plot:
    series = series_order(name for _, name in points)
    name = "_".join(
        ["variantes", *(slug(p) for p in (context["size"], context["cpu"], context["scenario"]))]
        + [slug(e) for e in extras(context)]
    )
    caption = (
        "Instruções e ciclos por unidade de trabalho (MAC; elemento no maxpool e na "
        "requantização) e IPC por operação, nas variantes "
        f"{', '.join(series_label(s) for s in series)}. Tamanho {size_text(context['size'])}, "
        f"CPU {context['cpu']}, cenário de memória {context['scenario']}{extras_text(context)}."
    )
    entry = {
        "kind": "variantes",
        "context": context,
        "caption": caption,
        "operations": ordered((bench for bench, _ in points), OPERATIONS),
        "series": series,
        "runs": sorted(row["run_id"] for row in points.values()),
    }
    return Plot(name, "variantes", variants_figure(points), entry)


def pair_plots(context: dict[str, str], points: dict) -> list[Plot]:
    cpus = ordered((cpu for _, cpu, _ in points), CPUS)
    common = {
        "context": context,
        "operations": ordered((bench for bench, _, _ in points), OPERATIONS),
        "cpus": cpus,
        "scenarios": scenario_order(scenario for _, _, scenario in points),
        "pairs": sorted([row["run_id_a"], row["run_id_b"]] for row in points.values()),
    }
    suffix = "_".join(
        [slug(context["size"]), slug(context["pair"]), *(slug(e) for e in extras(context))]
    )
    where = f"Tamanho {size_text(context['size'])}{extras_text(context)}."
    speedup = (
        f"Speedup em ciclos (S_C) do par {context['pair']} por operação e cenário de "
        f"memória, nas CPUs {', '.join(cpus)}. {where}"
    )
    ri_sc = (
        f"Redução de instruções (R_I) e speedup em ciclos (S_C) do par {context['pair']}, "
        f"por operação (marcador), cenário de memória (tom e tamanho) e CPU (painel). {where} "
        "Abaixo da diagonal S_C = R_I, o IPC da variante comparada é menor que o da base."
    )
    return [
        Plot(
            f"speedup_{suffix}",
            "speedup",
            speedup_figure(points),
            {"kind": "speedup", "caption": speedup, **common},
        ),
        Plot(
            f"ri_sc_{suffix}",
            "ri_sc",
            ri_sc_figure(points),
            {"kind": "ri_sc", "caption": ri_sc, **common},
        ),
    ]


# Gravação -----------------------------------------------------------------------


def save(figure: Figure, base: Path) -> list[str]:
    """PDF e PNG sem data de criação: a mesma entrada gera os mesmos bytes."""
    files = []
    for fmt in FORMATS:
        path = base.with_name(f"{base.name}.{fmt}")
        metadata = {"CreationDate": None} if fmt == "pdf" else {}
        figure.savefig(path, format=fmt, dpi=DPI, metadata=metadata)
        files.append(path.name)
    return files


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_plots(
    run_rows: list[dict[str, str]], pair_rows: list[dict[str, str]]
) -> tuple[list[Plot], Plots]:
    """Figuras das linhas de runs.csv e pairs.csv que valem (desenhar dentro de
    `matplotlib.rc_context(STYLE)`)."""
    runs, skipped_runs = select(run_rows, run_skip)
    pairs, skipped_pairs = select(pair_rows, pair_skip)
    if not runs and not pairs:
        reasons = "; ".join(
            f"{count} {reason}" for reason, count in (skipped_runs + skipped_pairs).most_common()
        )
        raise PlotError(f"nenhuma execução ou par para os gráficos ({reasons or 'CSVs vazios'})")
    run_groups, repeated_runs = group_runs(runs)
    pair_groups, repeated_pairs = group_pairs(pairs)
    plots = [variant_plot(dict(key), points) for key, points in run_groups.items()]
    for key, points in pair_groups.items():
        plots.extend(pair_plots(dict(key), points))
    names = Counter(plot.name for plot in plots)
    seen: Counter = Counter()
    for plot in plots:  # nomes que colidem depois do slug ganham um número
        if names[plot.name] > 1:
            seen[plot.name] += 1
            plot.name = f"{plot.name}_{seen[plot.name]}"
    order = {"variantes": 0, "speedup": 1, "ri_sc": 2}
    plots.sort(key=lambda plot: (order[plot.kind], plot.name))
    summary = Plots(
        kinds=Counter(plot.kind for plot in plots),
        used_runs=len(runs),
        used_pairs=len(pairs),
        skipped_runs=skipped_runs,
        skipped_pairs=skipped_pairs,
        repeated=repeated_runs + repeated_pairs,
    )
    return plots, summary


def previous_files(output: Path) -> list[Path]:
    """Arquivos gravados por um plot anterior, segundo o figures.json."""
    manifest = output / MANIFEST
    if not manifest.is_file():
        return []
    data = json.loads(manifest.read_text(encoding="utf-8"))
    names = [name for item in data.get("figures", []) for name in item.get("files", [])]
    return [output / name for name in [*names, *data.get("inputs", {}), MANIFEST]]


def write_plots(source: Path, output: Path, force: bool = False) -> Plots:
    """Gera as figuras de `source` (pasta com runs.csv e pairs.csv) em `output`."""
    tables = {name: source / name for name in (RUNS_FILE, PAIRS_FILE)}
    runs_rows = read_table(tables[RUNS_FILE], RUN_NEEDS)
    pair_rows = read_table(tables[PAIRS_FILE], PAIR_NEEDS)
    contents = {name: path.read_bytes() for name, path in tables.items()}
    with matplotlib.rc_context(STYLE):
        plots, summary = build_plots(runs_rows, pair_rows)
        targets = [output / f"{plot.name}.{fmt}" for plot in plots for fmt in FORMATS]
        conflicts = [path for path in [*targets, output / MANIFEST] if path.exists()]
        conflicts += [
            output / name
            for name, data in contents.items()
            if (output / name).is_file() and (output / name).read_bytes() != data
        ]
        if conflicts and not force:
            names = ", ".join(display(path) for path in conflicts[:3])
            more = f" e mais {len(conflicts) - 3}" if len(conflicts) > 3 else ""
            raise PlotError(f"já existe {names}{more}; use --force para regravar ou --output")
        for path in previous_files(output):
            path.unlink(missing_ok=True)
        output.mkdir(parents=True, exist_ok=True)
        figures = []
        for plot in plots:
            files = save(plot.figure, output / plot.name)
            figures.append({"name": plot.name, "files": files, **plot.entry})
    for name, data in contents.items():
        (output / name).write_bytes(data)
    manifest = {
        "generated_by": f"riscvcnnbench plot {__version__}",
        "matplotlib": matplotlib.__version__,
        "inputs": {
            name: {"source": display(path), "sha256": sha256(contents[name])}
            for name, path in tables.items()
        },
        "skipped": {"runs": dict(summary.skipped_runs), "pairs": dict(summary.skipped_pairs)},
        "figures": figures,
    }
    (output / MANIFEST).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary.output = output
    return summary
