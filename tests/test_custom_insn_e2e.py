"""Testes de ponta a ponta do benchmark de semântica das instruções (RCB-10).

Executados apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisam da toolchain RISC-V, do QEMU e do gem5 compilado.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")
RISCV_PREFIX = os.environ.get("RISCV_PREFIX", "riscv64-linux-gnu-")
BENCHMARK = ROOT / "benchmarks/cnn_insn_semantics"
MODEL_RESULT = "RESULT mode=model cases=39 failures=0"

# (opcode, funct3, funct7) de cada instrução, conforme docs/custom_instructions.md.
ENCODINGS = {
    (0x0B, 0, 0x00): "cnn.dot8",
    (0x0B, 1, 0x00): "cnn.max8",
    (0x0B, 0, 0x01): "cnn.dwmac p=0",
    (0x0B, 1, 0x01): "cnn.dwmac p=1",
    (0x0B, 2, 0x01): "cnn.dwmac p=2",
    (0x0B, 3, 0x01): "cnn.dwmac p=3",
    (0x2B, 0, 0x00): "cnn.rqnt",
    (0x2B, 0, 0x01): "cnn.rqnt.relu",
}

pytestmark = pytest.mark.e2e


def build(tmp_path: Path, name: str, flags: str = "-O2") -> Path:
    binary = tmp_path / name
    subprocess.run(
        ["make", "-C", str(BENCHMARK), f"OUT_DIR={tmp_path}", f"OUT={binary}", f"FLAGS={flags}"],
        check=True,
        capture_output=True,
    )
    return binary


def custom_words(binary: Path) -> list[int]:
    """Palavras que o objdump não reconhece como instrução padrão (`.insn`)."""
    disassembly = subprocess.run(
        [f"{RISCV_PREFIX}objdump", "-d", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [int(word, 16) for word in re.findall(r"\.insn\s+4, (0x[0-9a-f]+)", disassembly)]


def test_model_runs_on_qemu(tmp_path: Path) -> None:
    binary = build(tmp_path, "model")

    run = subprocess.run(["qemu-riscv64", str(binary)], capture_output=True, text=True)

    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == MODEL_RESULT


def test_model_runs_on_gem5_from_yaml(tmp_path: Path) -> None:
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    results = tmp_path / "results"
    experiment = tmp_path / "cnn_insn_semantics.yaml"
    experiment.write_text(
        (ROOT / "experiments/cnn_insn_semantics.yaml").read_text(encoding="utf-8")
        + f"output:\n  dir: {results}\n",
        encoding="utf-8",
    )

    run = subprocess.run(
        [sys.executable, "-m", "riscvcnnbench.cli", "run", str(experiment), "--gem5", str(GEM5)],
        capture_output=True,
        text=True,
    )
    (run_dir,) = results.iterdir()
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))

    assert run.returncode == 0, f"{run.stdout}\n{run.stderr}"
    assert metadata["status"] == "completed"
    assert metadata["program_exit_code"] == 0
    assert MODEL_RESULT in (run_dir / "stdout.log").read_text(encoding="utf-8")


def test_hw_build_uses_only_the_specified_encodings(tmp_path: Path) -> None:
    model = build(tmp_path, "model")
    hw = build(tmp_path, "hw", "-O2 -DCNN_INSN_HW")

    words = custom_words(hw)
    found = {(word & 0x7F, (word >> 12) & 0x7, word >> 25) for word in words}

    # Sem CNN_INSN_HW nenhuma instrução personalizada é emitida.
    assert custom_words(model) == []
    # Com CNN_INSN_HW aparecem exatamente as 8 codificações, todas em custom-0/1
    # e nenhuma em custom-3 (0x7B, usado pelas m5ops do gem5) ou custom-2 (0x5B).
    assert found == set(ENCODINGS), sorted(found)
