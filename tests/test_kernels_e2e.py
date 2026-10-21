"""Testes de ponta a ponta dos kernels de referência das operações (RCB-12).

Executados apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisam da toolchain RISC-V, do QEMU e do gem5 compilado. Tamanhos S e L
no QEMU; só S no gem5, pelo tempo de simulação.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")
BLOCK_HEADER = "---------- Begin Simulation Statistics ----------"

# Operação -> (nomes dos parâmetros, argumentos S, argumentos L), de docs/scope.md.
OPS = {
    "conv3x3_direct": ("H W Cin Cout R", "16 16 8 16 1", "32 32 16 32 1"),
    "conv3x3_im2col": ("H W Cin Cout R", "16 16 8 16 1", "32 32 16 32 1"),
    "depthwise3x3": ("H W C R", "16 16 32 1", "32 32 64 1"),
    "pointwise1x1": ("H W Cin Cout R", "16 16 32 32 1", "32 32 64 64 1"),
    "maxpool2x2": ("H W C R", "32 32 16 1", "64 64 32 1"),
    "requant_relu": ("N R", "4096 1", "32768 1"),
    "fc": ("In Out R", "512 32 1", "1024 512 1"),
}
SIZES = {"S": 1, "L": 2}

pytestmark = pytest.mark.e2e


def result_pattern(op: str, args: str) -> re.Pattern:
    names = OPS[op][0].split()
    params = " ".join(f"{name}={value}" for name, value in zip(names, args.split(), strict=True))
    return re.compile(
        rf"^RESULT bench={op} variant=ref {params} checksum=(0x[0-9a-f]{{16}}) "
        r"mismatches=(\d+)$",
        re.MULTILINE,
    )


@pytest.fixture(scope="module")
def binaries(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str], Path]:
    """Compila cada operação uma vez, normal e com o erro proposital."""
    out_dir = tmp_path_factory.mktemp("kernels")
    built = {}
    for op in OPS:
        for kind, flags in (("ok", "-O2"), ("bug", "-O2 -DRCB_INJECT_ERROR")):
            binary = out_dir / f"{op}_{kind}"
            subprocess.run(
                [
                    "make",
                    "-C",
                    str(ROOT / "benchmarks" / op),
                    f"OUT_DIR={out_dir}",
                    f"OUT={binary}",
                    f"FLAGS={flags}",
                ],
                check=True,
                capture_output=True,
            )
            built[op, kind] = binary
    return built


def qemu(binary: Path, args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["qemu-riscv64", str(binary), *args.split()], capture_output=True, text=True
    )


def checksum_on_qemu(binaries: dict, op: str, args: str) -> str:
    run = qemu(binaries[op, "ok"], args)
    assert run.returncode == 0, run.stderr
    match = result_pattern(op, args).search(run.stdout)
    assert match, run.stdout
    assert match.group(2) == "0"
    return match.group(1)


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("op", OPS)
def test_op_passes_on_qemu(binaries: dict, op: str, size: str) -> None:
    checksum_on_qemu(binaries, op, OPS[op][SIZES[size]])


@pytest.mark.parametrize("op", OPS)
def test_op_s_on_gem5_matches_qemu(binaries: dict, tmp_path: Path, op: str) -> None:
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    args = OPS[op][1]
    results = tmp_path / "results"
    experiment = tmp_path / f"{op}_s.yaml"
    experiment.write_text(
        (ROOT / f"experiments/{op}_s.yaml").read_text(encoding="utf-8")
        + f"output:\n  dir: {results}\n",
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
    match = result_pattern(op, args).search((run_dir / "stdout.log").read_text(encoding="utf-8"))

    assert stats.count(BLOCK_HEADER) == 2
    assert match and match.group(2) == "0"
    assert match.group(1) == checksum_on_qemu(binaries, op, args)


@pytest.mark.parametrize("size", SIZES)
def test_direct_and_im2col_compute_the_same_layer(binaries: dict, size: str) -> None:
    args = OPS["conv3x3_direct"][SIZES[size]]

    direct = checksum_on_qemu(binaries, "conv3x3_direct", args)
    im2col = checksum_on_qemu(binaries, "conv3x3_im2col", args)

    assert direct == im2col


@pytest.mark.parametrize("op", OPS)
def test_wrong_kernel_is_detected(binaries: dict, op: str) -> None:
    args = OPS[op][1]
    run = qemu(binaries[op, "bug"], args)

    assert run.returncode == 1
    assert result_pattern(op, args).search(run.stdout).group(2) == "1"
    assert re.search(r"^ERRO: y\[0\] = -?\d+, oráculo = -?\d+$", run.stderr, re.MULTILINE)


@pytest.mark.parametrize(
    ("op", "args", "message"),
    [
        ("conv3x3_direct", "16 16 12 16", "ERRO: Cin deve ser múltiplo de 8: 12"),
        ("depthwise3x3", "16 16 0", "ERRO: C deve estar entre 8 e 512: 0"),
        ("maxpool2x2", "31 32 16", "ERRO: H deve ser múltiplo de 2: 31"),
        ("requant_relu", "100", "ERRO: N deve ser múltiplo de 8: 100"),
        ("fc", "512 32 1 9", "ERRO: argumentos demais: 4 (máximo 3)"),
    ],
)
def test_invalid_arguments_exit_with_2(binaries: dict, op: str, args: str, message: str) -> None:
    run = qemu(binaries[op, "ok"], args)

    assert run.returncode == 2
    assert run.stderr.splitlines()[0] == message
