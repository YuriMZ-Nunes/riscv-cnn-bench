from pathlib import Path

import pytest

from riscvcnnbench.config import PROJECT_ROOT, uses_roi
from riscvcnnbench.parser import (
    METRICS,
    StatsError,
    cpu_model,
    extract,
    read_region,
    select_block,
    split_blocks,
)

# Recortes de stats.txt reais do gem5 25.1 (fc S na o3 com L1/L2/DDR4, e
# hello_riscv_param na atomic sem cache), com as linhas usadas pelo parser.
DATA = Path(__file__).parent / "data" / "stats"
BEGIN = "---------- Begin Simulation Statistics ----------"
END = "---------- End Simulation Statistics   ----------"
CPU_LINES = """\
simTicks                                     5000                       # (Tick)
hostSeconds                                  0.01                       # (Second)
system.cpu.numCycles                            5                       # (Cycle)
system.cpu.ipc                                0.8                       # ((Count/Cycle))
system.cpu.commitStats0.numInsts                4                       # (Count)
system.cpu.commitStats0.numOps                  4                       # (Count)
system.cpu.commitStats0.numMemRefs              2                       # (Count)
system.cpu.commitStats0.numLoadInsts            1                       # (Count)
system.cpu.commitStats0.numStoreInsts           1                       # (Count)
"""


def stats_text(*bodies: str) -> str:
    return "".join(f"\n{BEGIN}\n{body}\n{END}\n" for body in bodies)


def block(extra: str = "") -> dict[str, str]:
    (only,) = split_blocks(stats_text(CPU_LINES + extra))
    return only


def test_split_blocks_keeps_order_and_first_value() -> None:
    blocks = split_blocks((DATA / "roi_o3_l2_ddr4.txt").read_text(encoding="utf-8"))

    assert len(blocks) == 2
    assert blocks[0]["simInsts"] == "115270"
    assert blocks[1]["simInsts"] == "126213"
    # Linhas de vetor e distribuição: só o primeiro valor, sem as porcentagens.
    assert blocks[0]["system.cpu.commitStats0.committedInstType::IntAlu"] == "66012"
    assert blocks[0]["system.cpu.dcache.tags.avgRefs"] == "nan"


def test_roi_of_o3_with_caches_and_ddr4() -> None:
    stats = read_region(DATA / "roi_o3_l2_ddr4.txt", has_roi=True, cpu="o3")

    assert (stats.region, stats.blocks, stats.cpu) == ("roi", 2, "o3")
    assert stats.metrics == {
        "insts": 115270,
        "ops": 115270,
        "cycles": 66214,
        "ipc": 1.740871,
        "sim_ticks": 66214000,
        "loads": 32805,
        "stores": 37,
        "mem_refs": 32842,
        "branch_mispredicts": 46,
        "l1i_accesses": 32967,
        "l1i_misses": 5,
        "l1i_miss_rate": 0.000152,
        "l1i_avg_miss_latency": 79000.0,
        "l1d_accesses": 32867,
        # Sem faltas na ROI: o gem5 omite as linhas (nozero/nonan).
        "l1d_misses": 0,
        "l1d_miss_rate": 0.0,
        "l1d_avg_miss_latency": None,
        "l2_accesses": 3,
        "l2_misses": 3,
        "l2_miss_rate": 1.0,
        "l2_avg_miss_latency": 92000.0,
        "dram_reads": 3,
        "dram_writes": 0,
        "dram_bandwidth": 2899689,
        "dram_avg_latency": 17492.0,
        "simple_bytes_read": None,
        "simple_bytes_written": None,
        "simple_reads": None,
        "simple_writes": None,
        "host_seconds": 0.37,
    }
    assert stats.missing == {
        "l1d_avg_miss_latency": "indefinida: média sem eventos (0/0)",
        "simple_bytes_read": "system.memory não existe nesta configuração",
        "simple_bytes_written": "system.memory não existe nesta configuração",
        "simple_reads": "system.memory não existe nesta configuração",
        "simple_writes": "system.memory não existe nesta configuração",
    }
    assert isinstance(stats.metrics["l2_miss_rate"], float)


def test_program_on_atomic_without_cache() -> None:
    stats = read_region(DATA / "program_atomic_simple.txt", has_roi=False, cpu="atomic")
    cache_keys = [metric.key for metric in METRICS if metric.group == "Caches"]
    dram_keys = [metric.key for metric in METRICS if metric.key.startswith("dram_")]

    assert (stats.region, stats.blocks) == ("program", 1)
    assert {key: stats.metrics[key] for key in ("insts", "ops", "loads", "stores")} == {
        "insts": 127769,
        "ops": 127816,
        "loads": 21124,
        "stores": 7681,
    }
    assert stats.metrics["simple_bytes_read"] == 702385
    assert stats.metrics["simple_writes"] == 7668
    # O gem5 imprime numCycles e ipc na atomic, mas ela não modela tempo.
    for key in ("cycles", "ipc", "sim_ticks"):
        assert stats.metrics[key] is None
        assert stats.missing[key] == "a CPU atomic não modela tempo"
    assert all(stats.metrics[key] is None for key in [*cache_keys, *dram_keys])
    assert stats.missing["l2_misses"] == "system.l2cache não existe nesta configuração"
    assert stats.missing["branch_mispredicts"] == (
        "system.cpu.branchPred não existe nesta configuração"
    )


def test_unknown_cpu_keeps_time_metrics() -> None:
    stats = read_region(DATA / "program_atomic_simple.txt", has_roi=False)

    # Sem config.ini ao lado e sem `cpu`, não há como saber que era a atomic.
    assert stats.cpu is None
    assert stats.metrics["cycles"] == 150902


@pytest.mark.parametrize(
    ("count", "has_roi", "region"),
    [(2, True, "roi"), (1, False, "program"), (2, None, "roi"), (1, None, "program")],
)
def test_select_block(count: int, has_roi: bool | None, region: str) -> None:
    blocks = split_blocks(stats_text(*[CPU_LINES] * count))

    assert select_block(blocks, has_roi) == (region, blocks[0])


@pytest.mark.parametrize(
    ("count", "has_roi", "message"),
    [
        (
            1,
            True,
            "1 bloco, mas o benchmark marca a região de interesse e deveria ter 2 "
            "(a ROI e o resto do programa)",
        ),
        (
            3,
            True,
            "3 blocos, mas o benchmark marca a região de interesse e deveria ter 2 "
            "(a ROI e o resto do programa)",
        ),
        (
            2,
            False,
            "2 blocos, mas o benchmark não marca região de interesse e deveria ter 1 "
            "(o programa inteiro)",
        ),
        (
            3,
            None,
            "3 blocos; esperado 1 (programa inteiro) ou 2 (região de interesse e resto "
            "do programa)",
        ),
        (0, True, "nenhum bloco de estatísticas (o gem5 terminou antes de gravá-las?)"),
    ],
)
def test_unexpected_number_of_blocks(count: int, has_roi: bool | None, message: str) -> None:
    blocks = split_blocks(stats_text(*[CPU_LINES] * count))

    with pytest.raises(StatsError) as error:
        select_block(blocks, has_roi)

    assert str(error.value) == message


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            f"{BEGIN}\nsimTicks 1\n{END}\n{BEGIN}\nsimTicks 2\n",
            "o bloco 2 está incompleto: o arquivo termina antes do fim do bloco "
            "(a simulação foi interrompida?)",
        ),
        (f"{BEGIN}\nsimTicks 1\n{BEGIN}\n", "linha 3: o bloco 1 não terminou antes do seguinte"),
        (f"simTicks 1\n{END}\n", "linha 2: fim de bloco sem início"),
    ],
)
def test_malformed_file(text: str, message: str) -> None:
    with pytest.raises(StatsError) as error:
        split_blocks(text)

    assert str(error.value) == message


def test_missing_cpu_statistic_is_an_error() -> None:
    broken = block()
    del broken["system.cpu.commitStats0.numInsts"]

    with pytest.raises(StatsError) as error:
        extract(broken, "o3")

    assert str(error.value) == (
        "estatística system.cpu.commitStats0.numInsts não encontrada "
        "(o nome mudou nesta versão do gem5?)"
    )


def test_invalid_value_is_an_error() -> None:
    broken = block()
    broken["system.cpu.numCycles"] = "abc"

    with pytest.raises(StatsError) as error:
        extract(broken, "o3")

    assert str(error.value) == "valor inválido em system.cpu.numCycles: 'abc'"


def test_component_without_events() -> None:
    # Cache configurada que não recebeu acessos: só linhas sem flag aparecem.
    metrics, missing = extract(
        block(
            "system.cpu.dcache.replacements                  0      # (Count)\n"
            "system.mem_ctrl.readReqs                        0      # (Count)\n"
            "system.mem_ctrl.dram.avgMemAccLat             nan      # ((Tick/Count))\n"
        ),
        "timing",
    )

    assert {key: metrics[key] for key in metrics if key.startswith(("l1d_", "dram_"))} == {
        "l1d_accesses": 0,
        "l1d_misses": 0,
        "l1d_miss_rate": None,
        "l1d_avg_miss_latency": None,
        "dram_reads": 0,
        "dram_writes": 0,
        "dram_bandwidth": 0,
        "dram_avg_latency": None,
    }
    assert missing["l1d_miss_rate"] == "indefinida: l1d_accesses = 0"
    assert missing["l1d_avg_miss_latency"] == "indefinida: média sem eventos (0/0)"
    assert missing["dram_avg_latency"] == "indefinida: média sem eventos (0/0)"
    assert missing["l1i_accesses"] == "system.cpu.icache não existe nesta configuração"


def test_metric_table_is_consistent() -> None:
    keys = [metric.key for metric in METRICS]
    stats = [metric.stat for metric in METRICS]

    assert len(set(keys)) == len(keys)
    assert len(set(stats)) == len(stats)
    for metric in METRICS:
        if metric.component:
            assert metric.stat.startswith(metric.component), metric.key
        if metric.omitted == "ratio":
            denominator = next(item for item in METRICS if item.key == metric.denominator)
            assert denominator.component == metric.component, metric.key
            assert denominator.omitted == "zero", metric.key


@pytest.mark.parametrize(
    ("cpu_type", "model"),
    [
        ("BaseAtomicSimpleCPU", "atomic"),
        ("BaseTimingSimpleCPU", "timing"),
        ("BaseMinorCPU", "minor"),
        ("BaseO3CPU", "o3"),
        ("BaseKvmCPU", None),
    ],
)
def test_cpu_model_from_config_ini(tmp_path: Path, cpu_type: str, model: str | None) -> None:
    config = tmp_path / "config.ini"
    config.write_text(
        f"[root]\ntype=Root\n\n[system.cpu]\ntype={cpu_type}\nchildren=isa\n"
        "\n[system.cpu.isa]\ntype=RiscvISA\n",
        encoding="utf-8",
    )

    assert cpu_model(config) == model


def test_cpu_model_without_config_ini(tmp_path: Path) -> None:
    broken = tmp_path / "broken.ini"
    broken.write_text("sem seção\n", encoding="utf-8")

    assert cpu_model(tmp_path / "config.ini") is None
    assert cpu_model(broken) is None


def test_read_region_finds_cpu_in_config_ini(tmp_path: Path) -> None:
    gem5 = tmp_path / "gem5"
    gem5.mkdir()
    (gem5 / "stats.txt").write_text(
        (DATA / "program_atomic_simple.txt").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (gem5 / "config.ini").write_text("[system.cpu]\ntype=BaseAtomicSimpleCPU\n", encoding="utf-8")

    stats = read_region(gem5 / "stats.txt", has_roi=False)

    assert stats.cpu == "atomic"
    assert stats.metrics["cycles"] is None


@pytest.mark.parametrize(
    ("benchmark", "expected"),
    [
        ("fc", True),
        ("conv3x3_direct", True),
        ("int8_base_example", True),
        ("hello_riscv", False),
        ("hello_riscv_param", False),
        ("cnn_insn_semantics", False),
    ],
)
def test_uses_roi(benchmark: str, expected: bool) -> None:
    assert uses_roi(PROJECT_ROOT / "benchmarks" / benchmark) is expected
