"""Funções de proveniência compartilhadas pelos scripts de execução e build."""

import hashlib
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_output(*command: str) -> str | None:
    """Retorna a saída do comando, ou None se ele não existir ou falhar."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def git_info(directory: Path) -> dict:
    status = command_output("git", "-C", str(directory), "status", "--porcelain")
    return {
        "commit": command_output("git", "-C", str(directory), "rev-parse", "HEAD"),
        "dirty": None if status is None else bool(status),
        "status": status,
    }


def save_git_diff(directory: Path, destination: Path) -> bool:
    """Salva as alterações rastreadas em relação a HEAD.

    Arquivos não rastreados não entram no diff; eles aparecem apenas em
    git_info()["status"].
    """
    diff = command_output("git", "-C", str(directory), "diff", "HEAD", "--binary")
    if not diff:
        return False
    destination.write_text(diff + "\n", encoding="utf-8")
    return True


def gem5_version(gem5: Path) -> dict | None:
    """Extrai versão e data de compilação de `gem5 --build-info`."""
    output = command_output(str(gem5), "--build-info")
    if output is None:
        return None
    info = {}
    for line in output.splitlines():
        if line.startswith("gem5 version "):
            info["version"] = line.removeprefix("gem5 version ")
        elif line.startswith("compiled "):
            info["compiled"] = line.removeprefix("compiled ")
    return info


def build_info_path(gem5: Path) -> Path:
    return gem5.with_name(gem5.name + ".build-info.json")
