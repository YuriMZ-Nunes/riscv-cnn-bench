"""Testes de ponta a ponta das instruções personalizadas (RCB-10 e RCB-13).

Executados apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container,
pois precisam da toolchain RISC-V, do QEMU e do gem5 do fork compilado.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from riscvcnnbench.runs import diagnose, load_run
from test_custom_insn import model, source_cases

ROOT = Path(__file__).resolve().parents[1]
GEM5 = ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")
RISCV_PREFIX = os.environ.get("RISCV_PREFIX", "riscv64-linux-gnu-")
BENCHMARK = ROOT / "benchmarks/cnn_insn_semantics"
MODEL_RESULT = "RESULT mode=model cases=39 failures=0"
HW_RESULT = "RESULT mode=hw cases=39 failures=0"

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

# Combinações reservadas de custom-0/1, que o gem5 deve tratar como desconhecidas.
RESERVED = {
    (0x0B, 2, 0x00): "custom-0, funct7 0, funct3 livre",
    (0x0B, 7, 0x00): "custom-0, funct7 0, último funct3",
    (0x0B, 4, 0x01): "cnn.dwmac com p = 4",
    (0x0B, 0, 0x02): "custom-0, funct7 livre",
    (0x2B, 1, 0x00): "custom-1, funct3 livre",
    (0x2B, 0, 0x02): "custom-1, funct7 livre",
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


def run_semantics_yaml(tmp_path: Path, extra: str = "") -> tuple[str, dict]:
    """Executa experiments/cnn_insn_semantics.yaml (mais `extra`) e devolve stdout e metadados."""
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    results = tmp_path / "results"
    experiment = tmp_path / "cnn_insn_semantics.yaml"
    experiment.write_text(
        (ROOT / "experiments/cnn_insn_semantics.yaml").read_text(encoding="utf-8")
        + extra
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
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")

    assert run.returncode == 0, f"{run.stdout}\n{run.stderr}\n{stdout}"
    assert metadata["status"] == "completed"
    assert metadata["program_exit_code"] == 0
    return stdout, metadata


def test_model_runs_on_gem5_from_yaml(tmp_path: Path) -> None:
    stdout, _ = run_semantics_yaml(tmp_path)

    assert MODEL_RESULT in stdout


@pytest.mark.parametrize("cpu", ["atomic", "timing", "minor", "o3"])
def test_hw_runs_on_gem5(tmp_path: Path, cpu: str) -> None:
    """Instruções reais no gem5 do fork: cada caso confere instrução e modelo."""
    stdout, metadata = run_semantics_yaml(
        tmp_path, f"compiler:\n  flags: [-O2, -DCNN_INSN_HW]\ncpu:\n  model: {cpu}\n"
    )

    assert metadata["experiment"]["resolved"]["cpu"]["model"] == cpu
    assert HW_RESULT in stdout


def test_wrong_instruction_semantics_is_detected(tmp_path: Path) -> None:
    """Teste negativo: com CNN_INSN_INJECT_ERROR, o modo hw executa cnn.dwmac p=0 no lugar
    do cnn.dot8 (como um erro do decodificador), e os casos afetados precisam falhar."""
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    binary = build(tmp_path, "hw_bug", "-O2 -DCNN_INSN_HW -DCNN_INSN_INJECT_ERROR")
    results_dir = tmp_path / "results"
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
            str(results_dir),
            "--quiet",
        ],
        capture_output=True,
        check=False,
    )
    (run_dir,) = results_dir.iterdir()
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    stderr = (run_dir / "stderr.log").read_text(encoding="utf-8")

    # Casos de dot8 em que cnn.dwmac p=0 dá outro valor, pelo modelo em Python.
    expected = sorted(
        cid
        for cid, (op, _, rd, rs1, rs2, value) in source_cases().items()
        if op == "dot8" and model("dwmac", 0, rd, rs1, rs2) != value
    )
    failed = sorted(re.findall(r"^FALHA ([\w.-]+) instrução:", stderr, re.MULTILINE))

    assert metadata["program_exit_code"] == 1
    assert expected and failed == expected
    assert "FALHA" not in stderr.replace("FALHA dot8-", "")
    assert f"RESULT mode=hw cases=39 failures={len(expected)}" in stdout


@pytest.mark.parametrize("encoding", RESERVED, ids=RESERVED.values())
def test_reserved_encodings_are_unknown(tmp_path: Path, encoding: tuple[int, int, int]) -> None:
    assert GEM5.is_file(), f"gem5 não encontrado em {GEM5}; execute make gem5-build"
    opcode, funct3, funct7 = encoding
    source = tmp_path / "reserved.c"
    source.write_text(
        "int main(void) {\n"
        f'    __asm__ volatile(".insn r {opcode}, {funct3}, {funct7}, a0, a1, a2");\n'
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )
    binary = tmp_path / "reserved"
    subprocess.run(
        [f"{RISCV_PREFIX}gcc", "-O2", "-static", "-march=rv64gc", "-mabi=lp64d"]
        + ["-o", str(binary), str(source)],
        check=True,
    )
    results_dir = tmp_path / "results"
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
            str(results_dir),
            "--quiet",
        ],
        capture_output=True,
        check=False,
    )
    (run_dir,) = results_dir.iterdir()
    problem = diagnose(load_run(run_dir))

    assert problem is not None
    assert problem.kind == "instruction", problem.message
    # rd = a0 (x10), rs1 = a1 (x11), rs2 = a2 (x12).
    word = opcode | 10 << 7 | funct3 << 12 | 11 << 15 | 12 << 20 | funct7 << 25
    stderr = (run_dir / "stderr.log").read_text(encoding="utf-8")
    reported = re.search(r"Unknown instruction (0x[0-9a-f]+)", stderr)
    assert reported is not None, stderr
    assert int(reported[1], 16) & 0xFFFFFFFF == word


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
