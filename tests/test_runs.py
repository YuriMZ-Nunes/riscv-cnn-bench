import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench.cli import app
from riscvcnnbench.parser import StatsError, read_region
from riscvcnnbench.runs import diagnose, list_runs, load_run, region_stats, summary

RESOLVED = {
    "name": "exp",
    "benchmark": {"name": "hello_riscv_param", "args": []},
    "cpu": {"model": "timing", "clock": "2GHz"},
}
# stats.txt de exemplo (ver test_parser.py): fc S na o3, com ROI, e
# hello_riscv_param na atomic, sem ROI.
DATA = Path(__file__).parent / "data" / "stats"
ROI_STATS = (DATA / "roi_o3_l2_ddr4.txt").read_text(encoding="utf-8")
PROGRAM_STATS = (DATA / "program_atomic_simple.txt").read_text(encoding="utf-8")
FC_O3 = {
    "resolved": {
        "name": "fc_s",
        "benchmark": {"name": "fc", "args": ["512", "32", "1"], "variant": "custom"},
        "cpu": {"model": "o3", "clock": "1GHz"},
    }
}
ATOMIC_INI = "[system.cpu]\ntype=BaseAtomicSimpleCPU\n"


def make_run(
    root: Path,
    run_id: str = "20261020T000000.000000Z-aaaaaaaa",
    stdout: str = "",
    stderr: str = "",
    build_log: str | None = None,
    stats: str | None = None,
    config_ini: str | None = None,
    **metadata: object,
) -> Path:
    """Pasta de execução mínima, como a gravada por scripts/run-gem5.py."""
    run_dir = root / "exp" / run_id
    run_dir.mkdir(parents=True)
    content = {
        "schema_version": 5,
        "run_id": run_id,
        "status": "completed",
        "failed_step": None,
        "exit_code": 0,
        "program_exit_code": 0,
        "experiment": {"resolved": RESOLVED},
        "build": {"command": ["make"], "exit_code": 0, "log": "build.log"},
    }
    content.update(metadata)
    (run_dir / "metadata.json").write_text(json.dumps(content), encoding="utf-8")
    (run_dir / "stdout.log").write_text(stdout, encoding="utf-8")
    (run_dir / "stderr.log").write_text(stderr, encoding="utf-8")
    if build_log is not None:
        (run_dir / "build.log").write_text(build_log, encoding="utf-8")
    for name, content in (("stats.txt", stats), ("config.ini", config_ini)):
        if content is not None:
            (run_dir / "gem5").mkdir(exist_ok=True)
            (run_dir / "gem5" / name).write_text(content, encoding="utf-8")
    return run_dir


@pytest.fixture(autouse=True)
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Mensagens mostram caminhos relativos ao diretório atual.
    monkeypatch.chdir(tmp_path)


RUN = "exp/20261020T000000.000000Z-aaaaaaaa"

CASES = [
    pytest.param({}, None, None, id="completed"),
    pytest.param(
        {
            "status": "failed",
            "failed_step": "build",
            "exit_code": None,
            "program_exit_code": None,
            "build": {"command": ["make"], "exit_code": 2, "log": "build.log"},
            "build_log": "gcc -O2 main.c\n"
            "riscv64-linux-gnu-gcc: error: unrecognized command-line option '-fx'\n"
            "make: *** [Makefile:25: out] Error 1\n",
        },
        "build",
        "o benchmark 'hello_riscv_param' não compilou (make retornou 2): "
        "riscv64-linux-gnu-gcc: error: unrecognized command-line option '-fx'. "
        f"Log: {RUN}/build.log.",
        id="build",
    ),
    pytest.param(
        {
            "status": "failed",
            "failed_step": "build",
            "exit_code": None,
            "build": {"command": ["make"], "exit_code": 2, "log": "build.log"},
            "build_log": "make: riscv64-linux-gnu-gcc: No such file or directory\n",
        },
        "toolchain",
        "toolchain RISC-V não encontrada durante o build "
        "(make: riscv64-linux-gnu-gcc: No such file or directory). Execute dentro do "
        f"container (make run ou make shell). Log: {RUN}/build.log.",
        id="toolchain",
    ),
    pytest.param(
        {
            "status": "failed",
            "failed_step": "simulation",
            "exit_code": 2,
            "program_exit_code": 2,
            "stdout": "Simulação encerrada no tick 1: exiting (code=2)\n",
            "stderr": "src/sim/syscall_emul.cc:86: warn: ignoring syscall mprotect(...)\n"
            "ERRO: N deve ser um inteiro positivo: abc\n",
        },
        "benchmark",
        "o benchmark 'hello_riscv_param' terminou com código 2: o gem5 funcionou, mas o "
        "programa reportou resultado inválido ou rejeitou a entrada. Mensagem do programa: "
        f"ERRO: N deve ser um inteiro positivo: abc. Veja {RUN}/stdout.log e {RUN}/stderr.log.",
        id="benchmark",
    ),
    pytest.param(
        {
            "status": "failed",
            "failed_step": "simulation",
            "exit_code": -6,
            "program_exit_code": None,
            "stderr": "src/arch/riscv/faults.cc:290: panic: Unknown instruction "
            "0x0000000b at pc (0x10498=>0x1049c).(0=>1)\n",
        },
        "instruction",
        "o gem5 não reconhece uma instrução do binário (panic: Unknown instruction "
        "0x0000000b at pc (0x10498=>0x1049c).(0=>1)). Se o benchmark usa instruções "
        "personalizadas, confira se o gem5 foi compilado a partir do fork com elas "
        f"(make gem5-build). Veja {RUN}/stderr.log.",
        id="instruction",
    ),
    pytest.param(
        {
            "status": "failed",
            "failed_step": "simulation",
            "exit_code": 1,
            "program_exit_code": None,
            "stderr": "src/sim/process.cc:10: fatal: Can't load object file x\n",
        },
        "gem5",
        f"o gem5 terminou com erro (fatal: Can't load object file x). Veja {RUN}/stderr.log.",
        id="gem5-fatal",
    ),
    pytest.param(
        {
            "status": "failed",
            "failed_step": "simulation",
            "exit_code": 3,
            "program_exit_code": None,
        },
        "gem5",
        "o gem5 terminou com código 3 sem concluir a simulação. "
        f"Veja {RUN}/stderr.log e {RUN}/stdout.log.",
        id="gem5-code",
    ),
    pytest.param(
        {
            "status": "failed",
            "failed_step": "preparation",
            "error": "FileNotFoundError: x",
        },
        "preparation",
        f"falha ao preparar a execução: FileNotFoundError: x. Veja {RUN}/stderr.log.",
        id="preparation",
    ),
    pytest.param(
        {"status": "interrupted", "failed_step": "simulation"},
        "interrupted",
        "execução interrompida pelo usuário (etapa: simulation).",
        id="interrupted",
    ),
    pytest.param(
        {"status": "running"},
        "incomplete",
        "a execução não terminou (status 'running'): ainda está em andamento ou foi "
        f"encerrada abruptamente. Veja {RUN}/stderr.log.",
        id="incomplete",
    ),
]


@pytest.mark.parametrize(("fields", "kind", "message"), CASES)
def test_diagnose(tmp_path: Path, fields: dict, kind: str | None, message: str | None) -> None:
    fields = dict(fields)
    files = {key: fields.pop(key) for key in ("stdout", "stderr", "build_log") if key in fields}
    run = load_run(make_run(tmp_path, **files, **fields))

    problem = diagnose(run)

    if kind is None:
        assert problem is None
    else:
        assert problem is not None
        assert (problem.kind, problem.message) == (kind, message)


def test_list_runs_sorted_by_run_id(tmp_path: Path) -> None:
    make_run(tmp_path, run_id="20261020T000002.000000Z-bbbbbbbb")
    make_run(tmp_path, run_id="20261020T000001.000000Z-aaaaaaaa")
    (tmp_path / "exp" / "lixo").mkdir()

    found = list_runs(tmp_path)

    assert [run.path.name for run in found] == [
        "20261020T000001.000000Z-aaaaaaaa",
        "20261020T000002.000000Z-bbbbbbbb",
    ]
    assert (found[0].experiment, found[0].benchmark, found[0].cpu) == (
        "exp",
        "hello_riscv_param",
        "timing@2GHz",
    )


def test_list_runs_without_experiment(tmp_path: Path) -> None:
    # Execução de make hello-run-gem5: sem YAML, nome vem da pasta e do binário.
    make_run(tmp_path, experiment=None, original_binary="/x/inputs/hello_riscv")

    (run,) = list_runs(tmp_path)

    assert (run.experiment, run.benchmark, run.cpu) == ("exp", "hello_riscv", "-")


def test_cli_runs(tmp_path: Path) -> None:
    make_run(tmp_path, run_id="20261020T000001.000000Z-aaaaaaaa", stats=ROI_STATS, experiment=FC_O3)
    make_run(
        tmp_path,
        run_id="20261020T000002.000000Z-bbbbbbbb",
        status="failed",
        failed_step="simulation",
        exit_code=1,
        program_exit_code=1,
        stats=ROI_STATS,
    )
    make_run(
        tmp_path,
        run_id="20261020T000003.000000Z-cccccccc",
        stats=PROGRAM_STATS,
        config_ini=ATOMIC_INI,
    )
    make_run(tmp_path, run_id="20261020T000004.000000Z-dddddddd")

    result = CliRunner().invoke(app, ["runs", "."])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == [
        "RUN_ID",
        "EXPERIMENTO",
        "BENCHMARK",
        "CPU",
        "STATUS",
        "INSTS",
        "CICLOS",
        "IPC",
        "PASTA",
    ]
    assert lines[1].split() == [
        "20261020T000001.000000Z-aaaaaaaa",
        "fc_s",
        "fc",
        "o3@1GHz",
        "completed",
        "115270",
        "66214",
        "1.741",
        "exp/20261020T000001.000000Z-aaaaaaaa",
    ]
    # Falhou: as métricas não valem. Atomic: sem ciclos. Sem stats.txt: ilegível.
    assert lines[2].split()[4:9] == ["failed", "(benchmark)", "-", "-", "-"]
    assert lines[3].split()[4:8] == ["completed", "127769", "-", "-"]
    assert lines[4].split()[4:8] == ["completed", "?", "?", "?"]
    assert "4 execução(ões). INSTS, CICLOS e IPC são da região de interesse" in result.stdout


def test_cli_runs_empty_and_missing(tmp_path: Path) -> None:
    empty = CliRunner().invoke(app, ["runs", "."])
    missing = CliRunner().invoke(app, ["runs", "nada"])

    assert empty.exit_code == 0
    assert "Nenhuma execução em ." in empty.stdout
    assert missing.exit_code == 1
    assert "Erro: pasta não encontrada: nada" in missing.stderr


def test_region_stats_of_benchmark_with_roi(tmp_path: Path) -> None:
    run = load_run(make_run(tmp_path, stats=ROI_STATS, experiment=FC_O3))

    stats = region_stats(run)

    # Sem config.ini, o modelo da CPU vem da configuração resolvida.
    assert (stats.region, stats.blocks, stats.cpu) == ("roi", 2, "o3")
    assert stats.metrics["insts"] == 115270
    assert summary(stats) == "ROI, 115270 instruções, 66214 ciclos, IPC 1.741"


def test_region_stats_cpu_comes_from_config_ini(tmp_path: Path) -> None:
    # O config.ini é a máquina que o gem5 montou; vale mais que o YAML resolvido.
    run = load_run(make_run(tmp_path, stats=PROGRAM_STATS, config_ini=ATOMIC_INI))

    stats = region_stats(run)

    assert (stats.region, stats.cpu, stats.metrics["cycles"]) == ("program", "atomic", None)
    assert summary(stats) == (
        "programa inteiro, 127769 instruções, sem ciclos (a CPU atomic não modela tempo)"
    )


@pytest.mark.parametrize(
    ("stats", "experiment", "message"),
    [
        (
            ROI_STATS,
            {"resolved": RESOLVED},
            f"{RUN}/gem5/stats.txt: 2 blocos, mas o benchmark não marca região de interesse "
            "e deveria ter 1 (o programa inteiro).",
        ),
        (
            PROGRAM_STATS,
            FC_O3,
            f"{RUN}/gem5/stats.txt: 1 bloco, mas o benchmark marca a região de interesse e "
            "deveria ter 2 (a ROI e o resto do programa).",
        ),
        (None, FC_O3, f"{RUN}/gem5/stats.txt não existe: o gem5 não gravou estatísticas."),
    ],
    ids=["two-blocks-without-roi", "one-block-with-roi", "no-stats"],
)
def test_region_stats_errors(
    tmp_path: Path, stats: str | None, experiment: dict, message: str
) -> None:
    run = load_run(make_run(tmp_path, stats=stats, experiment=experiment))

    with pytest.raises(StatsError) as error:
        region_stats(run)

    assert str(error.value) == message


def test_region_stats_of_unknown_benchmark(tmp_path: Path) -> None:
    # Benchmark que não existe mais em benchmarks/: o número de blocos decide.
    resolved = {**RESOLVED, "benchmark": {"name": "removido", "args": []}}
    run = load_run(make_run(tmp_path, stats=ROI_STATS, experiment={"resolved": resolved}))

    assert region_stats(run).region == "roi"


def test_cli_stats(tmp_path: Path) -> None:
    make_run(tmp_path, stats=ROI_STATS, experiment=FC_O3)

    result = CliRunner().invoke(app, ["stats", RUN])

    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[:3] == [
        f"Execução:  {RUN}",
        "Benchmark: fc, CPU o3, status completed",
        "Região:    ROI, bloco 1 de 2",
    ]
    rows = {line.split()[0]: line.split(maxsplit=3)[1:] for line in lines if line.startswith("  ")}
    assert rows["insts"] == ["115270", "instruções", "system.cpu.commitStats0.numInsts"]
    assert rows["ipc"] == ["1.74087", "inst/ciclo", "system.cpu.ipc"]
    assert rows["l1d_misses"] == ["0", "faltas", "system.cpu.dcache.overallMisses::total"]
    assert rows["l1d_avg_miss_latency"] == [
        "ausente",
        "ticks",
        "system.cpu.dcache.demandAvgMissLatency::total (indefinida: média sem eventos (0/0))",
    ]
    assert len(rows) == 30
    assert "Caches" in lines and "Memória" in lines
    assert result.stderr == ""


def test_cli_stats_json(tmp_path: Path) -> None:
    run_dir = make_run(tmp_path, stats=ROI_STATS, experiment=FC_O3)
    expected = read_region(run_dir / "gem5/stats.txt", has_roi=True, cpu="o3")

    result = CliRunner().invoke(app, ["stats", RUN, "--json"])

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "run_id": "20261020T000000.000000Z-aaaaaaaa",
        "path": RUN,
        "status": "completed",
        "experiment": "fc_s",
        "benchmark": "fc",
        "variant": "custom",
        "cpu": "o3",
        "region": "roi",
        "blocks": 2,
        "metrics": expected.metrics,
        "missing": expected.missing,
    }


def test_cli_stats_errors_and_warning(tmp_path: Path) -> None:
    make_run(tmp_path, run_id="20261020T000001.000000Z-aaaaaaaa", experiment=FC_O3)
    make_run(
        tmp_path,
        run_id="20261020T000002.000000Z-bbbbbbbb",
        status="failed",
        failed_step="simulation",
        exit_code=1,
        program_exit_code=1,
        stats=ROI_STATS,
        experiment=FC_O3,
    )

    not_a_run = CliRunner().invoke(app, ["stats", "exp"])
    no_stats = CliRunner().invoke(app, ["stats", "exp/20261020T000001.000000Z-aaaaaaaa"])
    failed = CliRunner().invoke(app, ["stats", "exp/20261020T000002.000000Z-bbbbbbbb"])

    assert not_a_run.exit_code == 1
    assert not_a_run.stderr == "Erro: exp não é uma pasta de execução (falta metadata.json).\n"
    assert no_stats.exit_code == 1
    assert no_stats.stderr == (
        "Erro: exp/20261020T000001.000000Z-aaaaaaaa/gem5/stats.txt não existe: o gem5 não "
        "gravou estatísticas.\n"
    )
    assert failed.exit_code == 0
    assert failed.stderr == (
        "Aviso: a execução não foi concluída (status failed); as métricas não valem como "
        "resultado.\n"
    )
