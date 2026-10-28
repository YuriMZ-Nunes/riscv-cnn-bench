import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench import environment
from riscvcnnbench.cli import app
from riscvcnnbench.environment import Check, as_document, gem5_check, image_check, tool


def test_tool_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    outputs = {
        "scons": (0, "SCons by Steven Knight\nSCons: v4.5.2.120fd4f, Tue, 21 Mar 2023"),
        "git": (0, "git version 2.43.0"),
        "nada": (127, "nada não encontrado"),
    }
    monkeypatch.setattr(environment, "run", lambda command, timeout=120: outputs[command[0]])

    scons = tool("scons", ["scons", "--version"], pattern=r"SCons: v(\d+(?:\.\d+)*)")
    assert (scons.ok, scons.version) == (True, "4.5.2.120")
    assert tool("git", ["git", "--version"]).version == "git version 2.43.0"
    missing = tool("nada", ["nada"], required=False)
    assert (missing.ok, missing.detail, missing.required) == (False, "nada não encontrado", False)


def test_gem5_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment, "run", lambda command, timeout=120: (0, "gem5 version 25.1"))
    gem5 = tmp_path / "gem5.opt"

    assert "não existe" in gem5_check(gem5).detail
    gem5.write_bytes(b"binario")
    assert "sem gem5.opt.build-info.json" in gem5_check(gem5).detail

    digest = hashlib.sha256(b"binario").hexdigest()
    info = {"gem5_sha256": digest, "repository": {"commit": "ce032446a6", "branch": "rcb"}}
    gem5.with_name("gem5.opt.build-info.json").write_text(json.dumps(info), encoding="utf-8")
    ok = gem5_check(gem5)
    assert (ok.ok, ok.version) == (True, "25.1")
    assert ok.detail == f"commit ce03244 (rcb), sha256 {digest[:12]}, build-info confere"

    gem5.write_bytes(b"outro")
    assert gem5_check(gem5).ok is False


def test_image_and_document(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RCB_IMAGE_ID", raising=False)
    assert image_check().ok is False and image_check().required is False
    monkeypatch.setenv("RCB_IMAGE", "localhost/x:dev")
    monkeypatch.setenv("RCB_IMAGE_ID", "308bf637ff88c52f1d1e8345e466")
    assert image_check() == Check(
        "imagem", True, "localhost/x:dev", "id 308bf637ff88c52f1d1", False
    )

    # Só os itens obrigatórios decidem.
    checks = [Check("a", True, "1", ""), Check("b", False, None, "", required=False)]
    assert as_document(checks)["ok"] is True
    assert as_document([*checks, Check("c", False, None, "")])["ok"] is False


def test_cli_ambiente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checks = [Check("toolchain", True, "13.3.0", "gcc"), Check("qemu", False, None, "falta")]
    monkeypatch.setattr(environment, "check_environment", lambda gem5: checks)
    runner = CliRunner()
    output = tmp_path / "ambiente.json"

    result = runner.invoke(app, ["ambiente", "--output", str(output)])

    assert result.exit_code == 1
    assert "toolchain  ok        13.3.0  gcc" in result.output
    assert "qemu       FALTA     -       falta" in result.output
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["ok"] is False
    assert [item["name"] for item in document["checks"]] == ["toolchain", "qemu"]
    monkeypatch.setattr(environment, "check_environment", lambda gem5: checks[:1])
    assert runner.invoke(app, ["ambiente", "--json"]).exit_code == 0
