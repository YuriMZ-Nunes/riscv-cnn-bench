import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench.cli import app
from riscvcnnbench.runs import diagnose, list_runs, load_run

RESOLVED = {
    "name": "exp",
    "benchmark": {"name": "hello_riscv_param", "args": []},
    "cpu": {"model": "timing", "clock": "2GHz"},
}


def make_run(
    root: Path,
    run_id: str = "20261020T000000.000000Z-aaaaaaaa",
    stdout: str = "",
    stderr: str = "",
    build_log: str | None = None,
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
    make_run(tmp_path, run_id="20261020T000001.000000Z-aaaaaaaa")
    make_run(
        tmp_path,
        run_id="20261020T000002.000000Z-bbbbbbbb",
        status="failed",
        failed_step="simulation",
        exit_code=1,
        program_exit_code=1,
    )

    result = CliRunner().invoke(app, ["runs", "."])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["RUN_ID", "EXPERIMENTO", "BENCHMARK", "CPU", "STATUS", "PASTA"]
    assert lines[1].split() == [
        "20261020T000001.000000Z-aaaaaaaa",
        "exp",
        "hello_riscv_param",
        "timing@2GHz",
        "completed",
        "exp/20261020T000001.000000Z-aaaaaaaa",
    ]
    assert "failed (benchmark)" in lines[2]
    assert "2 execução(ões)" in result.stdout


def test_cli_runs_empty_and_missing(tmp_path: Path) -> None:
    empty = CliRunner().invoke(app, ["runs", "."])
    missing = CliRunner().invoke(app, ["runs", "nada"])

    assert empty.exit_code == 0
    assert "Nenhuma execução em ." in empty.stdout
    assert missing.exit_code == 1
    assert "Erro: pasta não encontrada: nada" in missing.stderr
