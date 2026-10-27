"""Teste de ponta a ponta dos ajustes das caches (RCB-32).

Executado apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisa da toolchain RISC-V e do gem5 do fork compilado.

Confere que cada ajuste do YAML (cache.line e, por nível, latency, mshrs,
targets e prefetcher) chega ao config.ini do gem5; que, sem ajustes, as caches
explícitas montam o mesmo sistema do cenário l1-l2 e os padrões de antes; e que
o prefetcher muda o resultado num percurso sequencial.
"""

import configparser
import re
from pathlib import Path

import pytest

from test_scenarios_e2e import FC_S, run

pytestmark = pytest.mark.e2e

L1_L2 = {
    "l1i": {"size": "32KiB", "assoc": 4},
    "l1d": {"size": "32KiB", "assoc": 4},
    "l2": {"size": "256KiB", "assoc": 8},
}
# Caminho, executável e saídas mudam de uma execução para outra.
PATHS = re.compile(r"^(cmd|executable|cwd|input|output|errout|outdir)=", re.M)


def config_ini(tmp_path: Path, name: str) -> configparser.ConfigParser:
    (run_dir,) = (tmp_path / name).iterdir()
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.read(run_dir / "gem5" / "config.ini")
    return parser


def config_text(tmp_path: Path, name: str) -> str:
    (run_dir,) = (tmp_path / name).iterdir()
    text = (run_dir / "gem5" / "config.ini").read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not PATHS.match(line))


def test_tuning_reaches_gem5(tmp_path: Path) -> None:
    cache = {
        "line": 128,
        "l1i": {"size": "32KiB", "assoc": 4},
        "l1d": {
            "size": "32KiB",
            "assoc": 4,
            "latency": 3,
            "mshrs": 4,
            "targets": 8,
            "prefetcher": "stride",
        },
        "l2": {"size": "256KiB", "assoc": 8, "latency": 20, "prefetcher": "tagged"},
    }
    _, stdout = run(
        tmp_path,
        "ajustes",
        {"benchmark": FC_S, "cpu": {"model": "minor"}, "cache": cache, "memory": {"type": "ddr4"}},
    )

    assert "linha=128 l1d.latência=3 l1d.mshrs=4 l1d.alvos=8 l1d.prefetcher=stride" in stdout
    assert "l2.latência=20 l2.prefetcher=tagged" in stdout
    config = config_ini(tmp_path, "ajustes")
    assert config["system"]["cache_line_size"] == "128"
    dcache = config["system.cpu.dcache"]
    assert (dcache["tag_latency"], dcache["data_latency"], dcache["response_latency"]) == (
        "3",
        "3",
        "3",
    )
    assert (dcache["mshrs"], dcache["tgts_per_mshr"]) == ("4", "8")
    assert config["system.cpu.dcache.prefetcher"]["type"] == "StridePrefetcher"
    l2 = config["system.l2cache"]
    assert (l2["tag_latency"], l2["mshrs"]) == ("20", "16")
    assert config["system.l2cache.prefetcher"]["type"] == "TaggedPrefetcher"
    icache = config["system.cpu.icache"]
    assert (icache["tag_latency"], icache["mshrs"], icache["prefetcher"]) == ("2", "16", "Null")


def test_explicit_caches_match_the_scenario_and_the_old_defaults(tmp_path: Path) -> None:
    base = {"benchmark": FC_S, "cpu": {"model": "timing"}}
    run(tmp_path, "cenario", {**base, "scenario": "l1-l2"})
    run(tmp_path, "explicito", {**base, "cache": L1_L2, "memory": {"type": "ddr4"}})

    assert config_text(tmp_path, "cenario") == config_text(tmp_path, "explicito")
    config = config_ini(tmp_path, "cenario")
    assert config["system"]["cache_line_size"] == "64"
    for name, latency in (
        ("system.cpu.icache", "2"),
        ("system.cpu.dcache", "2"),
        ("system.l2cache", "10"),
    ):
        section = config[name]
        assert (section["tag_latency"], section["mshrs"], section["tgts_per_mshr"]) == (
            latency,
            "16",
            "20",
        )
        assert section["prefetcher"] == "Null"


def test_prefetcher_speeds_up_a_sequential_walk(tmp_path: Path) -> None:
    """Maxpool L custom sem L2: os 160KiB da entrada vêm da DRAM em ordem, e o
    prefetcher stride na L1d antecipa as faltas (docs/analysis.md, memória)."""
    base = {
        "benchmark": {"name": "maxpool2x2", "args": [64, 64, 32, 1], "variant": "custom"},
        "cpu": {"model": "timing"},
        "memory": {"type": "ddr4"},
    }
    cycles = {}
    for prefetcher in ("none", "stride"):
        cache = {
            "l1i": {"size": "32KiB", "assoc": 4},
            "l1d": {"size": "32KiB", "assoc": 4, "prefetcher": prefetcher},
        }
        measured, _ = run(tmp_path, prefetcher, {**base, "cache": cache})
        cycles[prefetcher] = measured.stats.metrics["cycles"]

    assert cycles["stride"] < 0.9 * cycles["none"], cycles
