import json
from pathlib import Path

import pytest
from matplotlib.colors import to_rgb
from typer.testing import CliRunner

from riscvcnnbench.cli import app
from riscvcnnbench.metric import SIZES, scenario_label
from riscvcnnbench.plot import (
    MANIFEST,
    OPERATIONS,
    PlotError,
    build_plots,
    decimal,
    log_ticks,
    read_table,
    run_scenario,
    scenario_order,
    scenario_styles,
    series_label,
    series_order,
    variant_styles,
    write_plots,
)
from riscvcnnbench.report import PAIR_COLUMNS, RUN_COLUMNS, write_csv

MINOR = [
    "20261026T000001.000000Z-a",
    "20261026T000002.000000Z-a",
    "20261026T000003.000000Z-a",
    "20261026T000004.000000Z-a",
    "20261026T000005.000000Z-a",
    "20261026T000006.000000Z-a",
]


def run(
    run_id: str,
    bench: str = "fc",
    variant: str = "ref",
    cpu: str = "minor",
    insts: float = 8000,
    cycles: float | None = 16000,
    **extra: object,
) -> dict:
    """Uma linha de runs.csv com 1000 unidades de trabalho."""
    row = {
        "run_id": run_id,
        "current": True,
        "checksum_consistent": True,
        "bench": bench,
        "size": "S",
        "variant": variant,
        "data": "random",
        "work_unit": "elemento" if bench == "maxpool2x2" else "MAC",
        "flags": ["-O2"],
        "cpu": cpu,
        "clock": "1GHz",
        "vlen": 256,
        "custom_latency": 3,
        "scenario": "l1-l2",
        "l1i_size": "32KiB",
        "l1d_size": "32KiB",
        "l2_size": "256KiB",
        "memory": "ddr4",
        "cache_state": "warm",
        "insts": insts,
        "cycles": cycles,
        "ipc": insts / cycles if cycles else None,
        "insts_per_work": insts / 1000,
        "cycles_per_work": cycles / 1000 if cycles else None,
    }
    return {**row, **extra}


def pair(
    bench: str,
    cpu: str,
    scenario: str,
    r_i: float,
    s_c: float | None,
    label: str = "ref→custom",
    **extra: object,
) -> dict:
    row = {
        "kind": "variante",
        "pair": label,
        "bench": bench,
        "size": "S",
        "data": "random",
        "cpu": cpu,
        "clock": "1GHz",
        "scenario": scenario,
        "flags_a": ["-O2"],
        "flags_b": ["-O2"],
        "run_id_a": f"{label}-{bench}-{cpu}-{scenario}-a",
        "run_id_b": f"{label}-{bench}-{cpu}-{scenario}-b",
        "r_i": r_i,
        "s_c": s_c,
        "ipc_ratio": s_c / r_i if s_c else None,
    }
    return {**row, **extra}


RUNS = [
    run(MINOR[0]),
    run(MINOR[1], variant="custom", insts=1000, cycles=4000),
    run(MINOR[2], variant="custom", insts=1000, cycles=5000, custom_latency=6),
    run(MINOR[3], variant="rvv", insts=600, cycles=3000),
    run(MINOR[4], bench="maxpool2x2", insts=7000, cycles=9000),
    run(MINOR[5], bench="maxpool2x2", variant="custom", insts=3000, cycles=5000),
    run("20261026T000007.000000Z-t", cpu="timing", insts=8000, cycles=12000),
    # Fora: atomic, inválida, substituída, checksum divergente.
    run("20261026T000008.000000Z-x", cpu="atomic", cycles=None),
    run("20261026T000009.000000Z-x", variant="custom", problem="mismatches = 3"),
    run("20261026T000010.000000Z-x", current=False),
    run("20261026T000011.000000Z-x", variant="rvv", checksum_consistent=False),
]
PAIRS = [
    pair("fc", "minor", "l1-l2", 8, 4),
    pair("fc", "minor", "sem-cache", 8, 2),
    pair("maxpool2x2", "minor", "l1-l2", 7 / 3, 1.8),
    pair("fc", "timing", "l1-l2", 8, 6),
    pair("fc", "minor", "l1-l2", 40 / 3, 16 / 3, label="ref→rvv"),
    # Fora: atomic (sem S_C) e rejeitado.
    pair("fc", "atomic", "l1-l2", 8, None),
    pair("fc", "o3", "l1-l2", 8, 3, problem="checksums diferentes: 0x1 (ref -O2) × 0x2"),
]


@pytest.fixture
def campaign(tmp_path: Path) -> Path:
    root = tmp_path / "campanha"
    (root / "report").mkdir(parents=True)
    write_csv(root / "report/runs.csv", RUN_COLUMNS, RUNS)
    write_csv(root / "report/pairs.csv", PAIR_COLUMNS, PAIRS)
    return root


def tables(root: Path) -> tuple[list[dict], list[dict]]:
    return (
        read_table(root / "report/runs.csv", RUN_COLUMNS),
        read_table(root / "report/pairs.csv", PAIR_COLUMNS),
    )


def luminance(color: object) -> float:
    r, g, b = to_rgb(color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_operations_are_the_scope() -> None:
    assert list(OPERATIONS) == list(SIZES)


def test_orders_and_labels() -> None:
    assert series_order(["rvv", "custom@lat6", "ref", "rvv@vlen512", "custom"]) == [
        "ref",
        "custom",
        "custom@lat6",
        "rvv",
        "rvv@vlen512",
    ]
    assert scenario_order(["reduzido", "l1-l2,cold", "sem-cache", "l1d=4KiB,ddr4", "l1-l2"]) == [
        "sem-cache",
        "l1-l2",
        "l1-l2,cold",
        "reduzido",
        "l1d=4KiB,ddr4",
    ]
    assert [series_label(s) for s in ("ref", "custom@lat6", "rvv@vlen512")] == [
        "Referência",
        "Personalizada (latência 6)",
        "RVV (VLEN 512)",
    ]
    explicit = {key: "" for key in RUN_COLUMNS} | {
        "l1i_size": "32KiB",
        "l1d_size": "16KiB",
        "memory": "simple",
        "cache_state": "cold",
    }
    resolved = {
        "cache": {"l1i": {"size": "32KiB"}, "l1d": {"size": "16KiB"}},
        "memory": {"type": "simple"},
        "benchmark": {"cache_state": "cold"},
    }
    assert run_scenario(explicit) == scenario_label(resolved) == "l1i=32KiB,l1d=16KiB,simple,cold"


def test_styles_readable_in_black_and_white() -> None:
    # Cada série tem hachura própria, e o tom escurece sempre (cores distintas em cinza).
    series = ["ref", "custom", "custom@lat6", "rvv", "rvv@vlen512"]
    styles = variant_styles(series)
    assert len({hatch for _, hatch in styles.values()}) == len(series)
    tones = [luminance(styles[name][0]) for name in ("ref", "custom", "rvv")]
    assert tones == sorted(tones, reverse=True) and min(tones) > 0.4  # hachura preta visível
    assert styles["custom@lat6"][0] == styles["custom"][0]
    scenarios = scenario_styles(["sem-cache", "l1", "l1-l2", "reduzido"])
    assert len({hatch for _, hatch in scenarios.values()}) == 4
    tones = [luminance(color) for color, _ in scenarios.values()]
    assert tones == sorted(tones, reverse=True) and len(set(tones)) == 4


def test_numbers() -> None:
    assert [decimal(1.5), decimal(10.0), decimal(0.30000000000000004)] == ["1,5", "10", "0,3"]
    assert log_ticks(0.8, 25) == [1, 2, 5, 10, 20]
    assert log_ticks(1.1, 3.5) == pytest.approx([1.5, 2, 3])


def test_variants_figure(campaign: Path) -> None:
    plots, summary = build_plots(*tables(campaign))
    figure = {plot.name: plot for plot in plots}["variantes_S_minor_l1-l2"].figure

    assert (summary.used_runs, summary.repeated) == (7, 0)
    axes = figure.axes
    assert [ax.get_ylabel() for ax in axes] == [
        "Instruções por MAC",
        "Ciclos por MAC",
        "IPC (instruções\npor ciclo)",
    ]
    # Grupos na ordem das operações (maxpool antes da FC); barras por série.
    assert [t.get_text() for t in axes[-1].get_xticklabels()] == [
        "maxpool\n2×2\n(por elem.)",
        "FC",
    ]
    heights = [bar.get_height() for bar in axes[0].patches]
    assert heights == pytest.approx([7, 8, 3, 1, 1, 0.6])
    assert [bar.get_hatch() for bar in axes[0].patches] == ["", "", "///", "///", "xxx", "..."]
    assert [bar.get_height() for bar in axes[2].patches] == pytest.approx(
        [7 / 9, 0.5, 0.6, 0.25, 0.2, 0.2]
    )
    (legend,) = figure.legends
    assert [t.get_text() for t in legend.get_texts()] == [
        "Referência",
        "Personalizada",
        "Personalizada (latência 6)",
        "RVV",
    ]
    assert axes[0].yaxis.get_major_formatter()(2.5, 0) == "2,5"


def test_pair_figures(campaign: Path) -> None:
    plots = {plot.name: plot.figure for plot in build_plots(*tables(campaign))[0]}

    speedup = plots["speedup_S_ref-custom"]
    assert [ax.get_title(loc="left") for ax in speedup.axes] == ["CPU timing", "CPU minor"]
    # minor: sem-cache (fc) e l1-l2 (maxpool, fc).
    assert [bar.get_height() for bar in speedup.axes[1].patches] == pytest.approx([2, 1.8, 4])
    assert [t.get_text() for t in speedup.legends[0].get_texts()] == ["sem-cache", "l1-l2"]

    ri_sc = plots["ri_sc_S_ref-custom"]
    minor = ri_sc.axes[1]
    assert (minor.get_xscale(), minor.get_yscale()) == ("log", "log")
    points = sorted(tuple(c.get_offsets()[0]) for c in minor.collections)
    assert points == pytest.approx(sorted([(8, 4), (8, 2), (7 / 3, 1.8)]))
    diagonal = minor.lines[0]
    assert list(diagonal.get_xdata()) == list(diagonal.get_ydata())
    assert [t.get_text() for t in ri_sc.legends[1].get_texts()] == ["maxpool 2×2", "FC"]
    # Sem título na figura: a legenda vem do LaTeX.
    assert all(figure.get_suptitle() == "" for figure in plots.values())


def test_write_plots(campaign: Path) -> None:
    written = write_plots(campaign / "report", campaign / "figures")

    output = campaign / "figures"
    manifest = json.loads((output / MANIFEST).read_text(encoding="utf-8"))
    names = [item["name"] for item in manifest["figures"]]
    assert names == [
        "variantes_S_minor_l1-l2",
        "variantes_S_timing_l1-l2",
        "speedup_S_ref-custom",
        "speedup_S_ref-rvv",
        "ri_sc_S_ref-custom",
        "ri_sc_S_ref-rvv",
    ]
    for name in names:
        assert (output / f"{name}.pdf").read_bytes().startswith(b"%PDF")
        assert (output / f"{name}.png").read_bytes().startswith(b"\x89PNG")
    # O CSV usado fica junto das figuras.
    for table in ("runs.csv", "pairs.csv"):
        assert (output / table).read_bytes() == (campaign / "report" / table).read_bytes()
    minor = manifest["figures"][0]
    assert minor["context"] == {
        "size": "S",
        "cpu": "minor",
        "scenario": "l1-l2",
        "clock": "1GHz",
        "flags": "-O2",
        "data": "random",
    }
    assert minor["runs"] == MINOR
    assert minor["series"] == ["ref", "custom", "custom@lat6", "rvv"]
    assert minor["caption"] == (
        "Instruções e ciclos por unidade de trabalho (MAC; elemento no maxpool e na "
        "requantização) e IPC por operação, nas variantes Referência, Personalizada, "
        "Personalizada (latência 6), RVV. Tamanho S, CPU minor, cenário de memória l1-l2."
    )
    assert manifest["figures"][2]["cpus"] == ["timing", "minor"]
    assert manifest["skipped"] == {
        "runs": {
            "sem ciclos (CPU atomic)": 1,
            "inválida (problem)": 1,
            "substituída por outra mais recente": 1,
            "checksum divergente": 1,
        },
        "pairs": {"sem ciclos (CPU atomic)": 1, "rejeitado": 1},
    }
    assert (written.used_runs, written.used_pairs, written.repeated) == (7, 5, 0)


def test_same_input_same_bytes(campaign: Path, tmp_path: Path) -> None:
    write_plots(campaign / "report", tmp_path / "um")
    write_plots(campaign / "report", tmp_path / "dois")

    files = sorted(path.name for path in (tmp_path / "um").iterdir())
    assert len(files) == 6 * 2 + 3
    for name in files:
        assert (tmp_path / "um" / name).read_bytes() == (tmp_path / "dois" / name).read_bytes()


def test_repeated_point_keeps_the_latest(tmp_path: Path) -> None:
    # Outra forma da FC (R diferente) no mesmo ponto: vale a execução mais recente.
    root = tmp_path / "report"
    root.mkdir()
    rows = [run(MINOR[0]), run("20261026T000099.000000Z-r", insts=4000)]
    write_csv(root / "runs.csv", RUN_COLUMNS, rows)
    write_csv(root / "pairs.csv", PAIR_COLUMNS, [])

    written = write_plots(root, tmp_path / "figures")

    manifest = json.loads((tmp_path / "figures" / MANIFEST).read_text(encoding="utf-8"))
    assert written.repeated == 1
    assert manifest["figures"][0]["runs"] == ["20261026T000099.000000Z-r"]


def test_existing_figures_need_force(campaign: Path) -> None:
    write_plots(campaign / "report", campaign / "figures")

    with pytest.raises(PlotError, match=r"já existe .*variantes_S_minor_l1-l2.pdf.* e mais 1"):
        write_plots(campaign / "report", campaign / "figures")
    # Com --force, figuras que não saem mais (aqui, as dos pares) são apagadas.
    write_csv(campaign / "report/pairs.csv", PAIR_COLUMNS, [])
    write_plots(campaign / "report", campaign / "figures", force=True)
    names = sorted(path.name for path in (campaign / "figures").iterdir())
    assert names == [
        "figures.json",
        "pairs.csv",
        "runs.csv",
        "variantes_S_minor_l1-l2.pdf",
        "variantes_S_minor_l1-l2.png",
        "variantes_S_timing_l1-l2.pdf",
        "variantes_S_timing_l1-l2.png",
    ]


def test_errors(tmp_path: Path) -> None:
    root = tmp_path / "report"
    root.mkdir()
    with pytest.raises(PlotError, match="não encontrado: .*runs.csv; gere os CSVs com"):
        write_plots(root, tmp_path / "figures")
    (root / "runs.csv").write_text("run_id,problem\n", encoding="utf-8")
    with pytest.raises(PlotError, match="runs.csv: faltam as colunas current, checksum_consis"):
        write_plots(root, tmp_path / "figures")
    write_csv(root / "runs.csv", RUN_COLUMNS, [RUNS[7]])
    write_csv(root / "pairs.csv", PAIR_COLUMNS, [])
    with pytest.raises(PlotError) as error:
        write_plots(root, tmp_path / "figures")
    assert str(error.value) == (
        "nenhuma execução ou par para os gráficos (1 sem ciclos (CPU atomic))"
    )
    assert not (tmp_path / "figures").exists()


def test_cli_plot(campaign: Path) -> None:
    runner = CliRunner()

    first = runner.invoke(app, ["plot", str(campaign)])
    again = runner.invoke(app, ["plot", str(campaign)])
    other = runner.invoke(
        app, ["plot", "--input", str(campaign / "figures"), "--output", str(campaign / "b")]
    )
    missing = runner.invoke(app, ["plot", str(campaign / "nao")])

    assert first.exit_code == 0, first.output
    assert first.stdout.splitlines()[1:] == [
        "  2 de variantes, 2 de speedup, 2 de R_I × S_C",
        "  runs.csv: 7 execução(ões) usada(s); fora: 1 sem ciclos (CPU atomic), "
        "1 inválida (problem), 1 substituída por outra mais recente, 1 checksum divergente",
        "  pairs.csv: 5 par(es) usado(s); fora: 1 sem ciclos (CPU atomic), 1 rejeitado",
        "  figures.json: contexto, execuções e legenda sugerida de cada figura",
    ]
    assert again.exit_code == 1 and "use --force" in again.stderr
    # As cópias dos CSVs junto das figuras bastam para refazê-las.
    assert other.exit_code == 0, other.output
    for name in ("ri_sc_S_ref-rvv.pdf", "variantes_S_minor_l1-l2.png"):
        assert (campaign / "b" / name).read_bytes() == (campaign / "figures" / name).read_bytes()
    assert missing.exit_code == 1 and "gere os CSVs com riscvcnnbench report" in missing.stderr
