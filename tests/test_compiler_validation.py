"""Validação do contraste de compilador antes da campanha (RCB-22).

Executada com `make validate` (ou `pytest -m validation`), como a validação de
equivalência. A matriz final (campaigns/final.yaml) tem um grupo -O2 × -O3; aqui
se confere que o -O3 não muda o resultado:

- no QEMU, as sete operações em S e L, nas três variantes (custom com o modelo em
  C), compiladas com -O3, terminam com mismatches=0 e o checksum da ref -O2;
- no gem5 atomic, as operações do grupo compilador, na ref e na custom com as
  instruções reais, compiladas com -O3, dão o mesmo checksum.
"""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from riscvcnnbench.campaign import load_campaign
from riscvcnnbench.config import PROJECT_ROOT
from test_kernels_e2e import OPS, QEMU, ROOT, SIZES, result_pattern
from test_validation import JOBS, run_gem5

# (variante, CNN_INSN, flags): a referência -O2 e as três variantes com -O3.
CASES = (
    ("ref", "hw", "-O2"),
    ("ref", "hw", "-O3"),
    ("custom", "model", "-O3"),
    ("rvv", "hw", "-O3"),
)
COMPILER_OPS = ("conv3x3_direct", "conv3x3_im2col")

pytestmark = pytest.mark.validation


def build(out_dir: Path, op: str, variant: str, insn: str, flags: str) -> Path:
    binary = out_dir / f"{op}_{variant}_{insn}{flags}"
    subprocess.run(
        [
            "make",
            "-C",
            str(ROOT / "benchmarks" / op),
            f"OUT_DIR={out_dir}",
            f"OUT={binary}",
            f"FLAGS={flags}",
            f"VARIANT={variant}",
            f"CNN_INSN={insn}",
        ],
        check=True,
        capture_output=True,
    )
    return binary


def result(stdout: str, op: str, args: str, variant: str) -> tuple[str, int] | None:
    match = result_pattern(op, args, variant).search(stdout)
    return (match.group(1), int(match.group(2))) if match else None


@pytest.fixture(scope="module")
def qemu_runs(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple, tuple]:
    """(operação, tamanho, caso) -> (código de saída, (checksum, mismatches) ou None)."""
    out_dir = tmp_path_factory.mktemp("o3")

    def one(key: tuple) -> tuple[tuple, tuple]:
        op, size, (variant, insn, flags) = key
        binary = build(out_dir, op, variant, insn, flags)
        args = OPS[op][SIZES[size]]
        run = subprocess.run([*QEMU, str(binary), *args.split()], capture_output=True, text=True)
        return key, (run.returncode, result(run.stdout, op, args, variant))

    keys = [(op, size, case) for op in OPS for size in SIZES for case in CASES]
    with ThreadPoolExecutor(max_workers=JOBS) as pool:
        return dict(pool.map(one, keys))


def test_compiler_ops_are_the_matrix_group() -> None:
    campaign = load_campaign(PROJECT_ROOT / "campaigns/final.yaml")
    (group,) = [group for group in campaign.groups if group.name == "compilador"]
    assert group.experiments == [f"{op}_s" for op in COMPILER_OPS]


@pytest.mark.parametrize("size", list(SIZES))
@pytest.mark.parametrize("op", list(OPS))
def test_o3_passes_on_qemu(qemu_runs: dict, op: str, size: str) -> None:
    code, reference = qemu_runs[op, size, CASES[0]]
    assert code == 0 and reference is not None and reference[1] == 0
    for case in CASES[1:]:
        assert qemu_runs[op, size, case] == (0, (reference[0], 0)), case


@pytest.mark.parametrize("variant", ["ref", "custom"])
@pytest.mark.parametrize("op", COMPILER_OPS)
def test_o3_passes_on_gem5(qemu_runs: dict, tmp_path: Path, op: str, variant: str) -> None:
    binary = build(tmp_path, op, variant, "hw", "-O3")
    args = OPS[op][SIZES["S"]]

    code, stdout = run_gem5(binary, args, tmp_path / "results")

    reference = qemu_runs[op, "S", CASES[0]][1]
    assert code == 0 and result(stdout, op, args, variant) == (reference[0], 0)
