"""Testes de ponta a ponta das operações nas três variantes (RCB-12 e RCB-14).

Executados apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisam da toolchain RISC-V, do QEMU e do gem5 do fork compilado.

- QEMU: tamanhos S e L das variantes ref, custom (modelo em C das instruções,
  CNN_INSN=model) e rvv (VLEN 256).
- gem5 atomic: tamanho S das três variantes pelo fluxo `riscvcnnbench run`; a
  custom usa as instruções reais.
- gem5 timing, minor e o3: variante rvv com formas reduzidas, pelo tempo de
  simulação das CPUs detalhadas.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")
BLOCK_HEADER = "---------- Begin Simulation Statistics ----------"
QEMU = ["qemu-riscv64", "-cpu", "rv64,v=true,vlen=256,vext_spec=v1.0"]

# Operação -> (nomes dos parâmetros, argumentos S, argumentos L, argumentos
# reduzidos para as CPUs detalhadas). S e L vêm de docs/scope.md.
OPS = {
    "conv3x3_direct": ("H W Cin Cout R", "16 16 8 16 1", "32 32 16 32 1", "6 6 16 8 1"),
    "conv3x3_im2col": ("H W Cin Cout R", "16 16 8 16 1", "32 32 16 32 1", "6 6 16 8 1"),
    "depthwise3x3": ("H W C R", "16 16 32 1", "32 32 64 1", "6 6 40 1"),
    "pointwise1x1": ("H W Cin Cout R", "16 16 32 32 1", "32 32 64 64 1", "4 4 40 16 1"),
    "maxpool2x2": ("H W C R", "32 32 16 1", "64 64 32 1", "8 8 40 1"),
    "requant_relu": ("N R", "4096 1", "32768 1", "200 1"),
    "fc": ("In Out R", "512 32 1", "1024 512 1", "136 16 1"),
}
SIZES = {"S": 1, "L": 2}
VARIANTS = ("ref", "custom", "rvv")

pytestmark = pytest.mark.e2e


def result_pattern(op: str, args: str, variant: str, data: str = "random") -> re.Pattern:
    names = OPS[op][0].split()
    params = " ".join(f"{name}={value}" for name, value in zip(names, args.split(), strict=True))
    return re.compile(
        rf"^RESULT bench={op} variant={variant} data={data} {params} "
        r"checksum=(0x[0-9a-f]{16}) "
        r"mismatches=(\d+)$",
        re.MULTILINE,
    )


@pytest.fixture(scope="module")
def binaries(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str, str], Path]:
    """Compila cada operação e variante uma vez, normal e com o erro proposital.

    A custom é compilada com o modelo em C (CNN_INSN=model), que roda no QEMU.
    """
    out_dir = tmp_path_factory.mktemp("kernels")
    built = {}
    for op in OPS:
        for variant in VARIANTS:
            for kind, flags in (("ok", "-O2"), ("bug", "-O2 -DRCB_INJECT_ERROR")):
                binary = out_dir / f"{op}_{variant}_{kind}"
                subprocess.run(
                    [
                        "make",
                        "-C",
                        str(ROOT / "benchmarks" / op),
                        f"OUT_DIR={out_dir}",
                        f"OUT={binary}",
                        f"FLAGS={flags}",
                        f"VARIANT={variant}",
                        "CNN_INSN=model",
                    ],
                    check=True,
                    capture_output=True,
                )
                built[op, variant, kind] = binary
    return built


def qemu(binary: Path, args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*QEMU, str(binary), *args.split()], capture_output=True, text=True)


def checksum_on_qemu(binaries: dict, op: str, args: str, variant: str = "ref") -> str:
    run = qemu(binaries[op, variant, "ok"], args)
    assert run.returncode == 0, run.stderr
    match = result_pattern(op, args, variant).search(run.stdout)
    assert match, run.stdout
    assert match.group(2) == "0"
    return match.group(1)


def run_on_gem5(tmp_path: Path, op: str, **changes: object) -> tuple[Path, dict, str]:
    """Executa experiments/<op>_s.yaml com `changes` aplicadas; devolve pasta, metadados e stdout.

    Cada chave de `changes` é `seção__campo`, por exemplo benchmark__variant="rvv".
    """
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    data = yaml.safe_load((ROOT / f"experiments/{op}_s.yaml").read_text(encoding="utf-8"))
    for key, value in changes.items():
        section, field = key.split("__")
        data.setdefault(section, {})[field] = value
    results = tmp_path / "results"
    data["output"] = {"dir": str(results)}
    experiment = tmp_path / f"{op}.yaml"
    experiment.write_text(yaml.safe_dump(data), encoding="utf-8")

    run = subprocess.run(
        [sys.executable, "-m", "riscvcnnbench.cli", "run", str(experiment), "--gem5", str(GEM5)],
        capture_output=True,
        text=True,
    )
    (run_dir,) = results.iterdir()
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert run.returncode == 0, f"{run.stdout}\n{run.stderr}\n{stdout}"
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    return run_dir, metadata, stdout


def roi_stat(stats: str, name: str) -> int:
    """Valor de `name` no primeiro bloco do stats.txt, que é a ROI."""
    roi = stats.split(BLOCK_HEADER)[1]
    match = re.search(rf"^{re.escape(name)}\s+(\d+)", roi, re.MULTILINE)
    assert match, name
    return int(match.group(1))


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("op", OPS)
def test_op_passes_on_qemu(binaries: dict, op: str, size: str, variant: str) -> None:
    args = OPS[op][SIZES[size]]

    checksum = checksum_on_qemu(binaries, op, args, variant)

    assert checksum == checksum_on_qemu(binaries, op, args)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("op", OPS)
def test_op_s_on_gem5_matches_qemu(binaries: dict, tmp_path: Path, op: str, variant: str) -> None:
    args = OPS[op][1]

    run_dir, metadata, stdout = run_on_gem5(tmp_path, op, benchmark__variant=variant)
    stats = (run_dir / "gem5/stats.txt").read_text(encoding="utf-8")
    match = result_pattern(op, args, variant).search(stdout)

    assert metadata["experiment"]["resolved"]["benchmark"]["variant"] == variant
    assert stats.count(BLOCK_HEADER) == 2
    assert match and match.group(2) == "0"
    # Mesmo checksum da referência no QEMU: a custom roda as instruções reais.
    assert match.group(1) == checksum_on_qemu(binaries, op, args)

    insts = roi_stat(stats, "system.cpu.commitStats0.numInsts")
    ops = roi_stat(stats, "system.cpu.commitStats0.numOps")
    if variant == "rvv" and op != "maxpool2x2":
        # Instruções vetoriais com LMUL > 1 viram vários micro-ops no gem5.
        assert ops > insts
    else:
        # Escalares, instruções personalizadas e a RVV do pooling (só LMUL 1).
        assert ops == insts


@pytest.mark.parametrize("cpu", ["timing", "minor", "o3"])
@pytest.mark.parametrize("op", OPS)
def test_rvv_on_detailed_cpus(binaries: dict, tmp_path: Path, op: str, cpu: str) -> None:
    args = OPS[op][3]

    _, metadata, stdout = run_on_gem5(
        tmp_path, op, benchmark__variant="rvv", benchmark__args=args.split(), cpu__model=cpu
    )
    match = result_pattern(op, args, "rvv").search(stdout)

    assert metadata["experiment"]["resolved"]["cpu"]["model"] == cpu
    assert match and match.group(2) == "0", stdout
    assert match.group(1) == checksum_on_qemu(binaries, op, args)


def test_vlen_reaches_gem5(binaries: dict, tmp_path: Path) -> None:
    args = OPS["depthwise3x3"][3]

    run_dir, metadata, stdout = run_on_gem5(
        tmp_path,
        "depthwise3x3",
        benchmark__variant="rvv",
        benchmark__args=args.split(),
        cpu__vlen=512,
    )
    stderr = (run_dir / "stderr.log").read_text(encoding="utf-8")
    match = result_pattern("depthwise3x3", args, "rvv").search(stdout)

    assert metadata["experiment"]["resolved"]["cpu"]["vlen"] == 512
    assert "RVV enabled, VLEN = 512 bits" in stderr
    assert "vlen=512" in stdout
    assert match and match.group(1) == checksum_on_qemu(binaries, "depthwise3x3", args)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("size", SIZES)
def test_direct_and_im2col_compute_the_same_layer(binaries: dict, size: str, variant: str) -> None:
    args = OPS["conv3x3_direct"][SIZES[size]]

    direct = checksum_on_qemu(binaries, "conv3x3_direct", args, variant)
    im2col = checksum_on_qemu(binaries, "conv3x3_im2col", args, variant)

    assert direct == im2col


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("op", OPS)
def test_wrong_kernel_is_detected(binaries: dict, op: str, variant: str) -> None:
    args = OPS[op][1]
    run = qemu(binaries[op, variant, "bug"], args)

    assert run.returncode == 1
    assert result_pattern(op, args, variant).search(run.stdout).group(2) == "1"
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
    run = qemu(binaries[op, "ref", "ok"], args)

    assert run.returncode == 2
    assert run.stderr.splitlines()[0] == message
