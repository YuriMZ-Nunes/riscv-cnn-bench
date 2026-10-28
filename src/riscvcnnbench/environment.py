"""Ferramentas e versões do ambiente (RCB-27).

`check_environment` confere, dentro do container, o que o fluxo precisa: a
toolchain RISC-V compilando `rv64gc` e `rv64gcv` (com intrínsecos RVV), o QEMU
rodando os dois binários (o RVV com `v=true`), Python, uv, SCons, Git, o gem5 do
fork com o build-info, as bibliotecas Python e a imagem do container. Cada item
tem situação e versão, para registrar o ambiente de um experimento. Doc:
docs/container.md.
"""

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PREFIX = os.environ.get("RISCV_PREFIX", "riscv64-linux-gnu-")
# Os mesmos parâmetros do QEMU dos testes das variantes RVV (tests/test_kernels_e2e.py).
QEMU = ["qemu-riscv64", "-cpu", "rv64,v=true,vlen=256,vext_spec=v1.0"]
FLAGS = ["-O2", "-static", "-mabi=lp64d"]
# Bibliotecas Python: as do framework são obrigatórias; as de desenvolvimento, não.
PACKAGES = {
    "pydantic": True,
    "typer": True,
    "PyYAML": True,
    "pandas": True,
    "matplotlib": True,
    "pytest": False,
    "ruff": False,
    "quickjs": False,
}

SCALAR = """\
#include <stdio.h>
int main(void)
{
    long sum = 0;
    for (long i = 0; i < 1000; ++i) sum += i;
    printf("%ld\\n", sum);
    return sum == 499500 ? 0 : 1;
}
"""
VECTOR = """\
#include <riscv_vector.h>
#include <stdio.h>
int main(void)
{
    signed char a[64], b[64], c[64];
    for (int i = 0; i < 64; ++i) {
        a[i] = (signed char)(i % 16);
        b[i] = (signed char)(2 * (i % 16));
    }
    for (size_t done = 0, vl; done < 64; done += vl) {
        vl = __riscv_vsetvl_e8m1(64 - done);
        vint8m1_t x = __riscv_vle8_v_i8m1(a + done, vl);
        vint8m1_t y = __riscv_vle8_v_i8m1(b + done, vl);
        __riscv_vse8_v_i8m1(c + done, __riscv_vadd_vv_i8m1(x, y, vl), vl);
    }
    int sum = 0;
    for (int i = 0; i < 64; ++i) sum += c[i];
    printf("%d\\n", sum);
    return sum == 1440 ? 0 : 1;
}
"""


@dataclass
class Check:
    """Um item do ambiente: se está pronto, a versão e o que foi conferido."""

    name: str
    ok: bool
    version: str | None
    detail: str
    required: bool = True


def run(command: list[str], timeout: int = 120) -> tuple[int, str]:
    """Código de saída e saída (stdout e stderr); 127 se o programa não existe."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        return 127, f"{command[0]} não encontrado"
    except subprocess.TimeoutExpired:
        return 124, f"{command[0]} passou de {timeout} s"
    return result.returncode, (result.stdout + result.stderr).strip()


def first_line(text: str) -> str:
    return text.splitlines()[0].strip() if text else ""


def tool(name: str, command: list[str], pattern: str = "", required: bool = True) -> Check:
    """Versão de uma ferramenta: a primeira linha da saída, ou o grupo de `pattern`."""
    code, output = run(command)
    if code != 0:
        return Check(name, False, None, output or f"saída {code}", required)
    match = re.search(pattern, output) if pattern else None
    version = match.group(1) if match else first_line(output)
    return Check(name, True, version, " ".join(command))


def compile_and_run(name: str, march: str, source: str, expected: str, qemu: list[str]) -> Check:
    """Compila `source` com -march=`march` e roda no QEMU; confere a saída."""
    with tempfile.TemporaryDirectory(prefix="rcb-ambiente-") as folder:
        path = Path(folder) / "teste.c"
        binary = Path(folder) / "teste"
        path.write_text(source, encoding="utf-8")
        compiler = [f"{PREFIX}gcc", *FLAGS, f"-march={march}", str(path), "-o", str(binary)]
        code, output = run(compiler)
        if code != 0:
            return Check(name, False, None, f"compilação falhou: {first_line(output)}")
        code, output = run([*qemu, str(binary)])
        if code != 0 or output != expected:
            return Check(name, False, None, f"o QEMU devolveu {code} e {output!r}")
    detail = f"compila com -march={march} e roda em {' '.join(qemu)}"
    return Check(name, True, march, detail)


def gem5_check(gem5: Path) -> Check:
    """O gem5 do fork: versão, hash e o build-info de `make gem5-build`."""
    if not gem5.is_file():
        return Check("gem5", False, None, f"{gem5} não existe; rode make gem5-build")
    code, output = run([str(gem5), "--build-info"])
    version = next(
        (line.removeprefix("gem5 version ") for line in output.splitlines() if "version" in line),
        None,
    )
    digest = hashlib.sha256(gem5.read_bytes()).hexdigest()
    info_path = gem5.with_name(gem5.name + ".build-info.json")
    if not info_path.is_file():
        return Check("gem5", False, version, f"sem {info_path.name}; recompile com make gem5-build")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    repository = info.get("repository") or {}
    matches = info.get("gem5_sha256") == digest
    detail = (
        f"commit {str(repository.get('commit'))[:7]} ({repository.get('branch')}), "
        f"sha256 {digest[:12]}, build-info {'confere' if matches else 'NÃO confere'}"
    )
    return Check("gem5", code == 0 and matches, version, detail)


def package_checks() -> list[Check]:
    found = []
    for name, required in PACKAGES.items():
        try:
            version = importlib.metadata.version(name)
            found.append(Check(f"python: {name}", True, version, "importlib.metadata", required))
        except importlib.metadata.PackageNotFoundError:
            hint = "rode make sync" if required else "rode make sync (extra dev)"
            found.append(Check(f"python: {name}", False, None, hint, required))
    return found


def image_check() -> Check:
    image, image_id = os.environ.get("RCB_IMAGE"), os.environ.get("RCB_IMAGE_ID")
    if not image_id:
        return Check("imagem", False, image, "não informada (rode por make ambiente)", False)
    return Check("imagem", True, image, f"id {image_id[:19]}", False)


def check_environment(gem5: Path) -> list[Check]:
    return [
        image_check(),
        tool("toolchain", [f"{PREFIX}gcc", "--version"]),
        tool("binutils", [f"{PREFIX}as", "--version"]),
        compile_and_run("rv64gc", "rv64gc", SCALAR, "499500", ["qemu-riscv64"]),
        compile_and_run("rv64gcv", "rv64gcv", VECTOR, "1440", QEMU),
        tool("qemu", ["qemu-riscv64", "--version"]),
        Check("python", True, platform.python_version(), platform.python_implementation()),
        tool("uv", ["uv", "--version"]),
        tool("scons", ["scons", "--version"], pattern=r"SCons: v(\d+(?:\.\d+)*)"),
        tool("git", ["git", "--version"]),
        gem5_check(gem5),
        *package_checks(),
    ]


def as_document(checks: list[Check]) -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "ok": all(item.ok for item in checks if item.required),
        "checks": [asdict(item) for item in checks],
    }
