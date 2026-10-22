"""Testes de ponta a ponta da base comum dos kernels int8 (RCB-11).

Executados apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisam da toolchain RISC-V, do QEMU e do gem5 compilado.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")
RISCV_PREFIX = os.environ.get("RISCV_PREFIX", "riscv64-linux-gnu-")
BENCHMARK = ROOT / "benchmarks/int8_base_example"
BLOCK_HEADER = "---------- Begin Simulation Statistics ----------"
RESULT = re.compile(
    r"^RESULT bench=int8_base_example variant=ref data=random K=(\d+) M=(\d+) R=(\d+) "
    r"checksum=(0x[0-9a-f]{16}) mismatches=(\d+)$",
    re.MULTILINE,
)
WARNING = "AVISO: m5ops indisponíveis (fora do gem5); a região de interesse não foi marcada"

pytestmark = pytest.mark.e2e


def build(tmp_path: Path, name: str, flags: str = "-O2") -> Path:
    binary = tmp_path / name
    subprocess.run(
        ["make", "-C", str(BENCHMARK), f"OUT_DIR={tmp_path}", f"OUT={binary}", f"FLAGS={flags}"],
        check=True,
        capture_output=True,
    )
    return binary


def qemu(binary: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["qemu-riscv64", str(binary), *args], capture_output=True, text=True)


def run_gem5(tmp_path: Path, name: str, args: str) -> tuple[str, list[str]]:
    """Executa pelo `riscvcnnbench run`; devolve o stdout do programa e os blocos de stats."""
    results = tmp_path / "results" / name
    experiment = tmp_path / f"{name}.yaml"
    experiment.write_text(
        f"name: {name}\nbenchmark:\n  name: int8_base_example\n  args: {args}\n"
        f"output:\n  dir: {results}\n",
        encoding="utf-8",
    )
    run = subprocess.run(
        [sys.executable, "-m", "riscvcnnbench.cli", "run", str(experiment), "--gem5", str(GEM5)],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, f"{run.stdout}\n{run.stderr}"
    (run_dir,) = results.iterdir()
    stats = (run_dir / "gem5/stats.txt").read_text(encoding="utf-8")
    return (run_dir / "stdout.log").read_text(encoding="utf-8"), stats.split(BLOCK_HEADER)[1:]


def stat(block: str, name: str) -> int:
    match = re.search(rf"^{re.escape(name)}\s+(\d+)", block, re.MULTILINE)
    assert match, f"{name} não encontrado"
    return int(match.group(1))


def test_example_runs_on_qemu_without_m5ops(tmp_path: Path) -> None:
    run = qemu(build(tmp_path, "example"))

    assert run.returncode == 0, run.stderr
    match = RESULT.search(run.stdout)
    assert match and match.group(1, 2, 3, 5) == ("64", "16", "1", "0"), run.stdout
    assert run.stderr.strip() == WARNING


def test_roi_isolates_the_kernel_and_data_is_deterministic(tmp_path: Path) -> None:
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    native = RESULT.search(qemu(build(tmp_path, "example")).stdout)

    stdout_r1, blocks_r1 = run_gem5(tmp_path, "roi_r1", "[64, 16, 1]")
    stdout_r2, blocks_r2 = run_gem5(tmp_path, "roi_r2", "[64, 16, 2]")

    # Bloco 1: só a ROI. Bloco 2: do fim da ROI ao fim do programa.
    assert len(blocks_r1) == len(blocks_r2) == 2
    roi_r1 = stat(blocks_r1[0], "simInsts")
    roi_r2 = stat(blocks_r2[0], "simInsts")
    # Dobrar as repetições dobra a ROI (a menos das poucas instruções das m5ops)...
    assert abs(roi_r2 - 2 * roi_r1) < 0.01 * roi_r1
    # ...e não muda o que vem depois dela.
    assert stat(blocks_r1[1], "simInsts") == stat(blocks_r2[1], "simInsts")

    # Mesmos dados e mesmo resultado no QEMU e no gem5.
    gem5 = RESULT.search(stdout_r1)
    assert native and gem5
    assert gem5.group(4) == native.group(4)
    assert gem5.group(5) == "0"
    assert RESULT.search(stdout_r2).group(4) == native.group(4)


def test_wrong_kernel_is_detected(tmp_path: Path) -> None:
    run = qemu(build(tmp_path, "bug", "-O2 -DRCB_INJECT_ERROR"))

    assert run.returncode == 1
    assert RESULT.search(run.stdout).group(5) == "1"
    assert re.search(r"^ERRO: y\[8\] = -?\d+, oráculo = -?\d+$", run.stderr, re.MULTILINE)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["10"], "ERRO: K deve ser múltiplo de 8: 10"),
        (["64", "0"], "ERRO: M deve estar entre 1 e 4096: 0"),
        (["64", "x"], "ERRO: M deve ser um inteiro: x"),
        (["8", "1", "1", "1"], "ERRO: argumentos demais: 4 (máximo 3)"),
    ],
)
def test_invalid_arguments_exit_with_2(tmp_path: Path, args: list[str], message: str) -> None:
    run = qemu(build(tmp_path, "example"), *args)

    assert run.returncode == 2
    assert run.stderr.splitlines()[0] == message


def test_other_illegal_instructions_still_crash(tmp_path: Path) -> None:
    """O tratador de SIGILL só pula m5ops; uma instrução custom-0 continua fatal."""
    source = tmp_path / "illegal.c"
    source.write_text(
        '#include "rcb_roi.h"\n'
        "int main(void) {\n"
        "    rcb_roi_begin();\n"
        '    __asm__ volatile(".insn r CUSTOM_0, 0, 0, x0, x0, x0");\n'
        "    rcb_roi_end();\n"
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )
    binary = tmp_path / "illegal"
    subprocess.run(
        [
            f"{RISCV_PREFIX}gcc",
            "-O2",
            "-static",
            "-march=rv64gc",
            "-mabi=lp64d",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(ROOT / "benchmarks/common"),
            "-o",
            str(binary),
            str(source),
        ],
        check=True,
    )

    run = qemu(binary)

    # QEMU repassa o SIGILL: -4 pelo subprocess, ou 132 se passar por um shell.
    assert run.returncode in (-4, 132), run.returncode
