import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench.cli import app
from riscvcnnbench.metric import (
    WORK,
    Result,
    RunMetrics,
    cache_tuning,
    collect,
    compare,
    custom_qualifier,
    derive,
    parse_result,
    scenario_label,
)
from riscvcnnbench.parser import METRICS, RegionStats
from riscvcnnbench.runs import Run
from test_runs import FC_O3, ROI_STATS, make_run

FC_LINE = "RESULT bench=fc variant=ref data=random In=512 Out=32 R=2 checksum=0x00ff mismatches=0"
ABSENT = "componente não existe nesta configuração"


def region(cpu: str = "o3", **values: float) -> RegionStats:
    """RegionStats com as métricas dadas; as outras ausentes, como sem cache."""
    metrics = {metric.key: values.get(metric.key) for metric in METRICS}
    missing = {key: ABSENT for key, value in metrics.items() if value is None}
    if cpu == "atomic":
        for key in ("cycles", "ipc", "sim_ticks"):
            metrics[key] = None
            missing[key] = "a CPU atomic não modela tempo"
    return RegionStats("roi", 2, cpu, metrics, missing)


def measured(
    variant: str = "ref",
    insts: int = 1000,
    cycles: int = 2000,
    ops: int | None = None,
    run_id: str = "20261023T000000.000000Z-aaaaaaaa",
    status: str = "completed",
    cpu: str = "o3",
    vlen: int = 256,
    flags: tuple[str, ...] = ("-O2",),
    memory: str = "simple",
    checksum: str = "0x00ff",
    mismatches: str = "0",
    data: str = "random",
    gem5: str = "hash",
    bench: str | None = "fc",
    latency: int = 3,
    cache_state: str = "warm",
    units: dict | None = None,
) -> RunMetrics:
    """Execução sintética: fc 512×32 R=1 com as métricas e o cenário dados."""
    resolved = {
        "name": f"fc_{variant}",
        "scenario": None,
        "benchmark": {"name": "fc", "args": [], "variant": variant, "cache_state": cache_state},
        "compiler": {"flags": list(flags)},
        "cpu": {
            "model": cpu,
            "clock": "1GHz",
            "vlen": vlen,
            "custom_latency": latency,
            **(units or {}),
        },
        "cache": {"l1i": None, "l1d": {"size": "32KiB", "assoc": 4}, "l2": None},
        "memory": {"type": memory, "size": "512MiB"},
        "output": {"dir": f"/x/{variant}"},
    }
    metadata = {
        "run_id": run_id,
        "status": status,
        "experiment": {"resolved": resolved},
        "gem5_sha256": gem5,
    }
    fields = {"In": "512", "Out": "32", "R": "1", "checksum": checksum, "mismatches": mismatches}
    if bench:
        fields = {"bench": bench, "variant": variant, "data": data, **fields}
    stats = region(cpu, insts=insts, ops=ops or insts, cycles=cycles, ipc=insts / cycles)
    result = Result(fields)
    derived, missing, unit = derive(stats, result)
    return RunMetrics(
        Run(Path(f"exp/{variant}-{run_id}"), metadata), stats, result, derived, missing, unit
    )


def test_parse_result_of_the_common_base() -> None:
    result = parse_result(f"Sistema: cpu=o3\nRESULT bench=fc antigo=1\n{FC_LINE}\nSimulação...\n")

    assert result is not None
    assert (result.bench, result.variant, result.data) == ("fc", "ref", "random")
    assert (result.checksum, result.mismatches) == ("0x00ff", 0)
    # Parâmetros na ordem impressa; só a última linha RESULT vale.
    assert result.params == {"In": 512, "Out": 32, "R": 2}


def test_parse_result_without_the_common_base() -> None:
    hello = parse_result("RESULT n=1024 repeat=1 sum=523776\n")

    assert hello is not None
    assert (hello.bench, hello.variant, hello.checksum, hello.mismatches) == (None,) * 4
    assert parse_result("sem linha de resultado\n") is None
    assert parse_result("RESULT bench=fc mismatches=x\n").mismatches is None


@pytest.mark.parametrize(
    ("bench", "params", "work"),
    [
        # Tamanhos S e L de docs/scope.md.
        ("conv3x3_direct", {"H": 16, "W": 16, "Cin": 8, "Cout": 16}, 294912),
        ("conv3x3_direct", {"H": 32, "W": 32, "Cin": 16, "Cout": 32}, 4718592),
        ("conv3x3_im2col", {"H": 16, "W": 16, "Cin": 8, "Cout": 16}, 294912),
        ("depthwise3x3", {"H": 16, "W": 16, "C": 32}, 73728),
        ("depthwise3x3", {"H": 32, "W": 32, "C": 64}, 589824),
        ("pointwise1x1", {"H": 16, "W": 16, "Cin": 32, "Cout": 32}, 262144),
        ("pointwise1x1", {"H": 32, "W": 32, "Cin": 64, "Cout": 64}, 4194304),
        ("maxpool2x2", {"H": 32, "W": 32, "C": 16}, 16384),
        ("maxpool2x2", {"H": 64, "W": 64, "C": 32}, 131072),
        ("requant_relu", {"N": 4096}, 4096),
        ("requant_relu", {"N": 32768}, 32768),
        ("fc", {"In": 512, "Out": 32}, 16384),
        ("fc", {"In": 1024, "Out": 512}, 524288),
        ("int8_base_example", {"K": 64, "M": 16}, 1024),
    ],
)
def test_work_matches_the_scope_table(bench: str, params: dict, work: int) -> None:
    assert WORK[bench][1](params) == work


def test_derived_metrics_with_known_values() -> None:
    stats = region(insts=7000, ops=7000, cycles=14000, ipc=0.5, l1d_misses=7, l1i_misses=0)

    derived, missing, unit = derive(stats, parse_result(FC_LINE))

    assert unit == "MAC"
    assert derived == {
        "repetitions": 2,
        "work": 16384,
        "work_total": 32768,
        "cpi": 2.0,
        "l1i_mpki": 0.0,
        "l1d_mpki": 1.0,
        "l2_mpki": None,
        "insts_per_rep": 3500.0,
        "ops_per_rep": 3500.0,
        "cycles_per_rep": 7000.0,
        "insts_per_work": 7000 / 32768,
        "cycles_per_work": 14000 / 32768,
        "work_per_cycle": 32768 / 14000,
    }
    # Sem L2, a métrica derivada herda o motivo da bruta.
    assert missing == {"l2_mpki": ABSENT}


def test_derived_metrics_on_atomic_and_without_result() -> None:
    atomic, atomic_missing, _ = derive(
        region("atomic", insts=7000, ops=7000), parse_result(FC_LINE)
    )
    hello, hello_missing, unit = derive(
        region(insts=10, ops=10, cycles=20, ipc=0.5), parse_result("RESULT sum=1\n")
    )
    none, none_missing, _ = derive(region(insts=10, ops=10, cycles=20, ipc=0.5), None)

    assert atomic["insts_per_work"] == 7000 / 32768
    for key in ("cpi", "cycles_per_rep", "cycles_per_work", "work_per_cycle"):
        assert atomic[key] is None
        assert atomic_missing[key] == "a CPU atomic não modela tempo"
    assert (hello["cpi"], unit) == (2.0, None)
    assert hello_missing["work"] == "o benchmark não usa a base comum (sem bench= na linha RESULT)"
    assert hello_missing["cycles_per_work"] == hello_missing["work"]
    assert none_missing["repetitions"] == "o programa não imprimiu a linha RESULT"
    assert none["cpi"] == 2.0


@pytest.mark.parametrize(
    ("line", "stats", "key", "reason"),
    [
        ("RESULT bench=novo variant=ref R=1", {}, "work", "sem contagem de MACs para novo"),
        ("RESULT bench=fc variant=ref In=8 R=1", {}, "work", "a linha RESULT não tem Out"),
        ("RESULT bench=fc variant=ref In=8 Out=8", {}, "repetitions", "a linha RESULT não tem R"),
        (FC_LINE, {"insts": 0, "cycles": 10}, "cpi", "indefinida: insts = 0"),
        (FC_LINE, {"insts": 10, "cycles": 0}, "work_per_cycle", "indefinida: cycles = 0"),
    ],
)
def test_derived_metric_reasons(line: str, stats: dict, key: str, reason: str) -> None:
    values = {"insts": 10, "ops": 10, "cycles": 20, "ipc": 0.5, **stats}

    derived, missing, _ = derive(region(**values), parse_result(line))

    assert derived[key] is None
    assert missing[key] == reason


def test_variant_pairs_with_known_values() -> None:
    ref = measured("ref", insts=1000, cycles=2000)
    custom = measured("custom", insts=200, cycles=800)
    rvv = measured("rvv", insts=250, ops=400, cycles=500)

    comparison = compare([custom, rvv, ref])

    assert [pair.label for pair in comparison.pairs] == ["custom→rvv", "ref→custom", "ref→rvv"]
    values = {pair.label: pair.values for pair in comparison.pairs}
    assert values["ref→custom"] == {"r_i": 5.0, "r_i_ops": 5.0, "s_c": 2.5, "ipc_ratio": 0.5}
    assert values["ref→rvv"] == {"r_i": 4.0, "r_i_ops": 2.5, "s_c": 4.0, "ipc_ratio": 1.0}
    assert values["custom→rvv"] == {"r_i": 0.8, "r_i_ops": 0.5, "s_c": 1.6, "ipc_ratio": 2.0}
    # S_C = R_I × (IPC_b / IPC_a).
    for pair in comparison.pairs:
        assert pair.values["s_c"] == pytest.approx(pair.values["r_i"] * pair.values["ipc_ratio"])
        assert pair.kind == "variante" and pair.problem is None
    assert (comparison.excluded, comparison.superseded) == ([], [])


def test_pairs_need_the_same_scenario() -> None:
    ref = measured("ref")
    others = [
        measured("custom", memory="ddr4"),
        measured("custom", cpu="minor"),
        measured("custom", data="satpos"),
        measured("custom", gem5="outro"),
        measured("custom", flags=("-O2", "-DRCB_DATA=1")),
    ]

    assert compare([ref, *others]).pairs == []


def test_invalid_runs_and_checksums_are_reported() -> None:
    ref = measured("ref")
    custom = measured("custom", checksum="0xbad0")
    failed = measured("rvv", status="failed")
    wrong = measured("rvv", mismatches="3")
    hello = measured("ref", bench=None, run_id="20261023T000009.000000Z-hhhhhhhh")

    comparison = compare([ref, custom, failed, wrong, hello])

    (pair,) = comparison.pairs
    assert (pair.label, pair.values) == ("ref→custom", {})
    assert pair.problem == "checksums diferentes: 0x00ff (ref -O2) × 0xbad0 (custom -O2)"
    assert [reason for _, reason in comparison.excluded] == [
        "execução não concluída (status failed)",
        "resultado incorreto (mismatches=3)",
        "o benchmark não usa a base comum (sem bench= e variant= na linha RESULT)",
    ]


def test_vlen_only_matters_for_rvv() -> None:
    old_ref = measured("ref", vlen=512, run_id="20261023T000001.000000Z-aaaaaaaa")
    ref = measured("ref", run_id="20261023T000002.000000Z-bbbbbbbb")
    custom = measured("custom", insts=200, cycles=800)
    rvv = measured("rvv", insts=250, cycles=500)
    rvv512 = measured("rvv", vlen=512, insts=125, cycles=400)

    comparison = compare([old_ref, ref, custom, rvv, rvv512])

    # A VLEN não muda a ref: as duas são a mesma execução, e vale a mais recente.
    assert comparison.superseded == [old_ref.run.path]
    assert sorted(pair.label for pair in comparison.pairs) == [
        "custom→rvv",
        "custom→rvv@vlen512",
        "ref→custom",
        "ref→rvv",
        "ref→rvv@vlen512",
    ]
    assert all(pair.a.run is not old_ref.run for pair in comparison.pairs)


def test_latency_only_matters_for_custom() -> None:
    old_ref = measured("ref", latency=6, run_id="20261023T000001.000000Z-aaaaaaaa")
    ref = measured("ref", run_id="20261023T000002.000000Z-bbbbbbbb")
    custom = measured("custom", insts=200, cycles=800)
    custom6 = measured("custom", latency=6, insts=200, cycles=1000)
    rvv6 = measured("rvv", latency=6, insts=250, cycles=500)

    comparison = compare([old_ref, ref, custom, custom6, rvv6])

    # Uma ref serve para as custom de todas as latências, e a rvv também.
    assert comparison.superseded == [old_ref.run.path]
    labels = {pair.label: pair.values["s_c"] for pair in comparison.pairs}
    assert labels == {
        "ref→custom": 2.5,
        "ref→custom@lat6": 2.0,
        "ref→rvv": 4.0,
        "custom→rvv": 1.6,
        "custom@lat6→rvv": 2.0,
    }


def test_custom_units_only_matter_for_custom() -> None:
    """RCB-33: unidades e pipeline entram no rótulo e na chave só da custom."""
    ref = measured("ref", units={"custom_units": 2})
    custom = measured("custom", insts=200, cycles=800)
    two = measured("custom", insts=200, cycles=500, units={"custom_units": 2})
    serial = measured(
        "custom", insts=200, cycles=1000, latency=6, units={"custom_pipelined": False}
    )

    comparison = compare([ref, custom, two, serial])

    labels = {pair.label: pair.values["s_c"] for pair in comparison.pairs}
    assert labels == {
        "ref→custom": 2.5,
        "ref→custom@2u": 4.0,
        "ref→custom@lat6+np": 2.0,
    }
    assert custom_qualifier(
        {"custom_latency": 6, "custom_units": 2, "custom_pipelined": False}
    ) == ("lat6+2u+np")
    assert (
        custom_qualifier({"custom_latency": "3", "custom_units": "", "custom_pipelined": "true"})
        == ""
    )


def test_cold_and_warm_caches_do_not_mix() -> None:
    warm = measured("ref", run_id="20261023T000001.000000Z-aaaaaaaa")
    cold = measured("ref", cycles=3000, cache_state="cold", run_id="20261023T000002.000000Z-b")
    custom_cold = measured("custom", insts=200, cycles=1500, cache_state="cold")

    comparison = compare([warm, cold, custom_cold])

    # Não são repetições uma da outra, e a custom fria só pareia com a ref fria.
    assert comparison.superseded == []
    (pair,) = comparison.pairs
    assert (pair.a.run, pair.values["s_c"]) == (cold.run, 2.0)


def test_scenario_label() -> None:
    resolved = {
        "benchmark": {"cache_state": "warm"},
        "cache": {"l1i": {"size": "32KiB"}, "l1d": {"size": "4KiB"}, "l2": None},
        "memory": {"type": "ddr4"},
    }
    assert scenario_label(resolved) == "l1i=32KiB,l1d=4KiB,ddr4"
    assert scenario_label({**resolved, "scenario": "reduzido"}) == "reduzido"
    cold = {**resolved, "scenario": "l1-l2", "benchmark": {"cache_state": "cold"}}
    assert scenario_label(cold) == "l1-l2,cold"
    assert scenario_label({"memory": {"type": "simple"}}) == "sem-cache,simple"
    # Ajustes das caches (RCB-32): só os que não são o padrão, depois da memória.
    tuned = {
        **resolved,
        "cache": {
            **resolved["cache"],
            "line": 128,
            "l1d": {"size": "4KiB", "latency": 3, "prefetcher": "stride"},
        },
    }
    assert cache_tuning(tuned) == "line=128,l1d.lat=3,l1d.pf=stride"
    assert scenario_label(tuned) == "l1i=32KiB,l1d=4KiB,ddr4,line=128,l1d.lat=3,l1d.pf=stride"
    assert scenario_label({**tuned, "benchmark": {"cache_state": "cold"}}).endswith(
        "pf=stride,cold"
    )
    assert scenario_label(resolved, tuning="l2.lat=20") == "l1i=32KiB,l1d=4KiB,ddr4,l2.lat=20"
    assert cache_tuning(resolved) == ""


def test_compiler_pairs_keep_the_other_flags() -> None:
    data = "-DRCB_DATA=1"
    o2 = measured("ref", flags=("-O2", data), insts=1000, cycles=2000)
    o3 = measured("ref", flags=("-O3", data), insts=800, cycles=1000)
    custom_o3 = measured("custom", flags=("-O3", data), insts=200, cycles=500)
    other_data = measured("ref", flags=("-O3",), insts=800, cycles=1000)

    comparison = compare([o2, o3, custom_o3, other_data])

    labels = {
        pair.label: (pair.kind, pair.values["r_i"], pair.values["s_c"]) for pair in comparison.pairs
    }
    assert labels == {
        "ref→custom(-O3)": ("variante", 4.0, 2.0),
        "ref(-O2→-O3)": ("compilador", 1.25, 2.0),
    }


def test_atomic_pairs_have_no_cycles() -> None:
    ref = measured("ref", cpu="atomic", insts=1000)
    custom = measured("custom", cpu="atomic", insts=200)

    (pair,) = compare([ref, custom]).pairs

    assert pair.values == {"r_i": 5.0, "r_i_ops": 5.0, "s_c": None, "ipc_ratio": None}
    assert pair.missing == {
        "s_c": "a CPU atomic não modela tempo",
        "ipc_ratio": "a CPU atomic não modela tempo",
    }


def fc_run(tmp_path: Path, run_id: str, variant: str, **metadata: object) -> Path:
    """Pasta de execução da fc S na o3 (stats de exemplo) com a linha RESULT."""
    resolved = json.loads(json.dumps(FC_O3["resolved"]))
    resolved["benchmark"]["variant"] = variant
    line = FC_LINE.replace("variant=ref", f"variant={variant}").replace("R=2", "R=1")
    return make_run(
        tmp_path,
        run_id=run_id,
        stdout=f"{line}\n",
        stats=ROI_STATS,
        experiment={"resolved": resolved},
        **metadata,
    )


@pytest.fixture
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_collect_and_compare_run_folders(in_tmp: Path) -> None:
    fc_run(in_tmp, "20261023T000001.000000Z-aaaaaaaa", "ref")
    fc_run(in_tmp, "20261023T000002.000000Z-bbbbbbbb", "custom")
    make_run(in_tmp, run_id="20261023T000003.000000Z-cccccccc", status="failed")
    make_run(in_tmp, run_id="20261023T000004.000000Z-dddddddd")

    items, excluded = collect(in_tmp)
    comparison = compare(items, excluded)

    (pair,) = comparison.pairs
    # Mesmo stats.txt nas duas: as razões dão 1.
    assert (pair.label, pair.values["r_i"], pair.values["s_c"]) == ("ref→custom", 1.0, 1.0)
    assert [(path.name, reason) for path, reason in comparison.excluded] == [
        ("20261023T000003.000000Z-cccccccc", "execução não concluída (status failed)"),
        (
            "20261023T000004.000000Z-dddddddd",
            "exp/20261023T000004.000000Z-dddddddd/gem5/stats.txt não existe: o gem5 não "
            "gravou estatísticas.",
        ),
    ]


def test_cli_compare(in_tmp: Path) -> None:
    fc_run(in_tmp, "20261023T000001.000000Z-aaaaaaaa", "ref")
    fc_run(in_tmp, "20261023T000002.000000Z-bbbbbbbb", "custom")
    make_run(in_tmp, run_id="20261023T000003.000000Z-cccccccc", status="failed")

    text = CliRunner().invoke(app, ["compare", "."])
    document = CliRunner().invoke(app, ["compare", ".", "--json"])

    assert text.exit_code == 0, text.stderr
    lines = text.stdout.splitlines()
    assert lines[0].split() == [
        "OPERAÇÃO",
        "PARÂMETROS",
        "CPU",
        "CENÁRIO",
        "PAR",
        "R_I",
        "R_I_OPS",
        "S_C",
        "IPC_RATIO",
    ]
    assert lines[1].split() == [
        "fc",
        "In=512,Out=32,R=1",
        "o3@1GHz",
        "sem-cache,?",
        "ref→custom",
        "1.000",
        "1.000",
        "1.000",
        "1.000",
    ]
    assert "1 par(es) aceito(s), 0 rejeitado(s)." in text.stdout
    assert "  exp/20261023T000003.000000Z-cccccccc: execução não concluída (status failed)" in lines
    pairs = json.loads(document.stdout)["pairs"]
    assert [(pair["kind"], pair["label"], pair["problem"]) for pair in pairs] == [
        ("variante", "ref→custom", None)
    ]
    assert pairs[0]["scenario"]["params"] == {"In": 512, "Out": 32, "R": 1}


def test_cli_compare_without_pairs_and_missing_folder(in_tmp: Path) -> None:
    empty = CliRunner().invoke(app, ["compare", "."])
    missing = CliRunner().invoke(app, ["compare", "nada"])

    assert empty.exit_code == 0
    assert empty.stdout.startswith("\n0 par(es) aceito(s), 0 rejeitado(s).")
    assert missing.exit_code == 1
    assert missing.stderr == "Erro: pasta não encontrada: nada\n"


def test_cli_stats_shows_derived_metrics(in_tmp: Path) -> None:
    run_dir = fc_run(in_tmp, "20261023T000001.000000Z-aaaaaaaa", "custom")

    text = CliRunner().invoke(app, ["stats", str(run_dir.relative_to(in_tmp))])
    document = json.loads(
        CliRunner().invoke(app, ["stats", str(run_dir.relative_to(in_tmp)), "--json"]).stdout
    )

    assert text.exit_code == 0, text.stderr
    lines = text.stdout.splitlines()
    assert lines[3] == (
        "Resultado: bench=fc variant=custom data=random In=512 Out=32 R=1 checksum=0x00ff "
        "mismatches=0"
    )
    rows = {line.split()[0]: line.split(maxsplit=3)[1:] for line in lines if line.startswith("  ")}
    assert rows["work"] == ["16384", "MACs", "MACs de uma repetição (nominais)"]
    assert rows["insts_per_work"] == ["7.03552", "inst/MAC", "insts / work_total"]
    assert rows["cpi"] == ["0.574425", "ciclos/inst", "cycles / insts"]
    assert "Derivadas" in lines
    assert document["result"]["checksum"] == "0x00ff"
    assert document["work_unit"] == "MAC"
    assert document["derived"]["work_total"] == 16384
    assert document["derived_missing"] == {}
