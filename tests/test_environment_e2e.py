"""Teste de ponta a ponta do ambiente (RCB-27).

Executado apenas com `make e2e-test` (ou `pytest -m e2e`) dentro do container:
a toolchain compila rv64gc e rv64gcv, o QEMU roda os dois, e o gem5 do fork
confere com o build-info.
"""

import json
import subprocess
import sys

import pytest

pytestmark = pytest.mark.e2e


def test_environment_is_complete() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "riscvcnnbench.cli", "ambiente", "--json"],
        capture_output=True,
        text=True,
    )

    document = json.loads(result.stdout)
    checks = {item["name"]: item for item in document["checks"]}
    missing = [item for item in document["checks"] if item["required"] and not item["ok"]]
    assert result.returncode == 0 and document["ok"], missing
    for name in ("toolchain", "binutils", "rv64gc", "rv64gcv", "qemu", "python", "scons", "gem5"):
        assert checks[name]["ok"], checks[name]
    assert "v=true" in checks["rv64gcv"]["detail"]
    assert checks["python: matplotlib"]["version"]
