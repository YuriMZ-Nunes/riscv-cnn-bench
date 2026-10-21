"""Casos de teste de semântica das instruções personalizadas (RCB-10).

Os casos existem em dois lugares: na especificação (docs/custom_instructions.md)
e no benchmark que os executa (benchmarks/cnn_insn_semantics/main.c). Aqui se
confere que as duas listas são iguais e se recalcula cada valor esperado com um
modelo em Python, independente do modelo em C de benchmarks/common/cnn_insn.h.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/custom_instructions.md"
SOURCE = ROOT / "benchmarks/cnn_insn_semantics/main.c"

M64 = (1 << 64) - 1
C_OPS = {
    "CNN_OP_DOT8": "dot8",
    "CNN_OP_MAX8": "max8",
    "CNN_OP_DWMAC": "dwmac",
    "CNN_OP_RQNT": "rqnt",
    "CNN_OP_RQNT_RELU": "rqnt.relu",
}
# Instruções que leem rd; nas demais a especificação mostra "—" e o C usa 0.
READS_RD = {"dot8", "dwmac"}


def sext(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def lane8(reg: int, i: int) -> int:
    return sext(reg >> (8 * i), 8)


def model(op: str, p: int, rd: int, rs1: int, rs2: int) -> int:
    if op == "dot8":
        return sext(rd + sum(lane8(rs1, i) * lane8(rs2, i) for i in range(8)), 32) & M64
    if op == "max8":
        return sum((max(lane8(rs1, i), lane8(rs2, i)) & 0xFF) << (8 * i) for i in range(8))
    if op == "dwmac":
        lanes = [(rd >> (32 * j)) + lane8(rs1, 2 * p + j) * lane8(rs2, 2 * p + j) for j in (0, 1)]
        return sum((lane & 0xFFFFFFFF) << (32 * j) for j, lane in enumerate(lanes))
    acc, m0, s = sext(rs1, 32), sext(rs2, 32), (rs2 >> 32) & 31
    y = (acc * m0 + (1 << (30 + s))) >> (31 + s)
    return min(max(y, 0 if op == "rqnt.relu" else -128), 127) & M64


Case = tuple[str, int, int, int, int, int]


def source_cases() -> dict[str, Case]:
    pattern = re.compile(
        r'\{"([\w.-]+)", (CNN_OP_\w+), (\d), (0x[0-9a-f]{16}), (0x[0-9a-f]{16}), '
        r"(0x[0-9a-f]{16}), (0x[0-9a-f]{16})\},"
    )
    cases = {}
    for cid, op, p, *values in pattern.findall(SOURCE.read_text(encoding="utf-8")):
        cases[cid] = (C_OPS[op], int(p), *(int(v, 16) for v in values))
    return cases


def spec_cases() -> dict[str, Case]:
    pattern = re.compile(
        r"^\| ([\w.]+-\d\d) \| cnn\.(\w+(?:\.relu)?)(?: p=(\d))? \| (—|`0x[0-9a-f]{16}`) \| "
        r"`(0x[0-9a-f]{16})` \| `(0x[0-9a-f]{16})` \| `(0x[0-9a-f]{16})` \|",
        re.MULTILINE,
    )
    cases = {}
    for cid, op, p, rd, *values in pattern.findall(SPEC.read_text(encoding="utf-8")):
        rd_value = 0 if rd == "—" else int(rd.strip("`"), 16)
        cases[cid] = (op, int(p or 0), rd_value, *(int(v, 16) for v in values))
    return cases


def test_spec_and_source_have_the_same_cases() -> None:
    source, spec = source_cases(), spec_cases()

    assert len(source) == 39
    assert source == spec


def test_every_instruction_has_cases() -> None:
    ops = {(op, p) for op, p, *_ in source_cases().values()}

    assert ops >= {("dot8", 0), ("max8", 0), ("rqnt", 0), ("rqnt.relu", 0)}
    assert {p for op, p in ops if op == "dwmac"} == {0, 1, 2, 3}


def test_rd_shown_only_for_instructions_that_read_it() -> None:
    for cid, (op, _, rd, *_) in source_cases().items():
        if op not in READS_RD:
            assert rd == 0, cid


@pytest.mark.parametrize("cid", sorted(source_cases()))
def test_expected_value_matches_python_model(cid: str) -> None:
    op, p, rd, rs1, rs2, expected = source_cases()[cid]

    assert model(op, p, rd, rs1, rs2) == expected
