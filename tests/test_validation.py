"""Validação de equivalência entre as variantes, antes da campanha (RCB-15).

Executada com `make validate`, que roda também os testes e2e, ou com
`pytest -m validation` dentro do container. Precisa da toolchain, do QEMU e do
gem5 do fork.

Para cada operação, as três variantes recebem os mesmos dados e são comparadas
com o mesmo oráculo. A equivalência é então: todas terminam com mismatches=0 e
com o mesmo checksum, no QEMU e no gem5 atomic, e o mesmo binário dá o mesmo
checksum nos dois. A matriz:

- conjunto aleatório (`random`) em S e L e conjuntos extremos (`satpos`,
  `satneg`) em S;
- variantes ref, custom em modo modelo (QEMU e gem5), custom com as instruções
  reais (só gem5) e rvv (VLEN 256).

As simulações rodam em paralelo (RCB_JOBS, padrão: número de CPUs).
"""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from test_kernels_e2e import GEM5, OPS, QEMU, ROOT, SIZES, result_pattern

DATASETS = {"random": 0, "satpos": 1, "satneg": 2}
# Modo -> (VARIANT, CNN_INSN). custom-model usa o modelo em C das instruções.
MODES = {
    "ref": ("ref", "hw"),
    "custom-model": ("custom", "model"),
    "custom": ("custom", "hw"),
    "rvv": ("rvv", "hw"),
}
# (tamanho, conjunto) validados: o aleatório em S e L, os extremos só em S.
CASES = [("S", "random"), ("L", "random"), ("S", "satpos"), ("S", "satneg")]
# Bytes de saída de cada operação no tamanho S.
OUTPUT_BYTES_S = {
    "conv3x3_direct": 16 * 16 * 16,
    "conv3x3_im2col": 16 * 16 * 16,
    "depthwise3x3": 16 * 16 * 32,
    "pointwise1x1": 16 * 16 * 32,
    "maxpool2x2": 16 * 16 * 16,
    "requant_relu": 4096,
    "fc": 32,
}
# Valor de toda a saída nos conjuntos extremos: 127 (satura) ou 0 (ReLU).
SATURATED = {"satpos": 127, "satneg": 0}
JOBS = int(os.environ.get("RCB_JOBS", os.cpu_count() or 1))

pytestmark = pytest.mark.validation

Key = tuple[str, str, str, str, str]  # (plataforma, operação, tamanho, modo, conjunto)


def fnv1a(data: bytes) -> str:
    """Mesmo checksum de rcb_checksum (FNV-1a de 64 bits)."""
    value = 0xCBF29CE484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"0x{value:016x}"


def build(out_dir: Path, op: str, mode: str, data: str) -> Path:
    variant, insn = MODES[mode]
    binary = out_dir / f"{op}_{mode}_{data}"
    subprocess.run(
        [
            "make",
            "-C",
            str(ROOT / "benchmarks" / op),
            f"OUT_DIR={out_dir}",
            f"OUT={binary}",
            f"FLAGS=-O2 -DRCB_DATA={DATASETS[data]}",
            f"VARIANT={variant}",
            f"CNN_INSN={insn}",
        ],
        check=True,
        capture_output=True,
    )
    return binary


def run_qemu(binary: Path, args: str) -> tuple[int, str]:
    run = subprocess.run([*QEMU, str(binary), *args.split()], capture_output=True, text=True)
    return run.returncode, run.stdout


def run_gem5(binary: Path, args: str, results: Path) -> tuple[int, str]:
    """Executa pelo wrapper (uma pasta por execução) e devolve o código do programa e o stdout."""
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run-gem5.py"),
            "--gem5",
            str(GEM5),
            "--binary",
            str(binary),
            "--config",
            str(ROOT / "configs/gem5/se_riscv_configurable.py"),
            "--results-dir",
            str(results),
            "--quiet",
            "--",
            *(f"--arg={arg}" for arg in args.split()),
        ],
        capture_output=True,
        check=False,
    )
    (run_dir,) = results.iterdir()
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    # None quando o gem5 parou antes do fim do programa.
    exit_code = metadata["program_exit_code"]
    return -1 if exit_code is None else exit_code, stdout


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[Key, tuple[int, str]]:
    """Compila e executa a matriz inteira em paralelo; chave -> (código, stdout)."""
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    root = tmp_path_factory.mktemp("validation")
    datasets = sorted({data for _, data in CASES})

    with ThreadPoolExecutor(max_workers=JOBS) as pool:
        builds = {
            (op, mode, data): pool.submit(build, root / "bin", op, mode, data)
            for op in OPS
            for mode in MODES
            for data in datasets
        }
        binaries = {key: future.result() for key, future in builds.items()}

        jobs = {}
        for op in OPS:
            for size, data in CASES:
                args = OPS[op][SIZES[size]]
                for mode in MODES:
                    binary = binaries[op, mode, data]
                    if mode != "custom":  # as instruções reais não existem no QEMU
                        jobs["qemu", op, size, mode, data] = pool.submit(run_qemu, binary, args)
                    results = root / "results" / f"{op}_{size}_{mode}_{data}"
                    jobs["gem5", op, size, mode, data] = pool.submit(
                        run_gem5, binary, args, results
                    )
        return {key: future.result() for key, future in jobs.items()}


def checksums(runs: dict, op: str, size: str, data: str) -> dict[tuple[str, str], str]:
    """Checksum de cada (plataforma, modo), conferindo saída 0 e mismatches=0."""
    args = OPS[op][SIZES[size]]
    found = {}
    for (platform, run_op, run_size, mode, run_data), (code, stdout) in runs.items():
        if (run_op, run_size, run_data) != (op, size, data):
            continue
        match = result_pattern(op, args, MODES[mode][0], data).search(stdout)
        assert code == 0 and match, f"{platform} {mode}: código {code}\n{stdout}"
        assert match.group(2) == "0", f"{platform} {mode}: mismatches={match.group(2)}"
        found[platform, mode] = match.group(1)
    return found


@pytest.mark.parametrize(("size", "data"), CASES, ids=[f"{s}-{d}" for s, d in CASES])
@pytest.mark.parametrize("op", OPS)
def test_variants_are_equivalent(runs: dict, op: str, size: str, data: str) -> None:
    found = checksums(runs, op, size, data)

    # 3 modos no QEMU + 4 no gem5, todos com o mesmo checksum.
    assert len(found) == 7, sorted(found)
    assert len(set(found.values())) == 1, found


@pytest.mark.parametrize("data", ["satpos", "satneg"])
@pytest.mark.parametrize("op", OPS)
def test_extreme_data_saturates_every_output(runs: dict, op: str, data: str) -> None:
    """Além de bater com o oráculo, a saída inteira saturou no extremo esperado."""
    # No pooling a entrada é toda -128 (0x80) nos dois conjuntos, e o máximo também.
    value = 0x80 if op == "maxpool2x2" else SATURATED[data]
    expected = fnv1a(bytes([value]) * OUTPUT_BYTES_S[op])

    found = checksums(runs, op, "S", data)

    assert set(found.values()) == {expected}
