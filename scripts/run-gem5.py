"""Executa gem5 e preserva os artefatos de cada execução.

Argumentos após `--` são repassados à configuração gem5, por exemplo:

    run-gem5.py --gem5 ... --binary ... --config ... --results-dir ... -- --cpu timing
"""

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from provenance import (
    build_info_path,
    command_output,
    gem5_version,
    git_info,
    save_git_diff,
    sha256,
)


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def environment_info(binary: Path) -> dict:
    """Versões das ferramentas e do container usados na execução."""
    prefix = os.environ.get("RISCV_PREFIX", "riscv64-linux-gnu-")
    gcc = command_output(f"{prefix}gcc", "--version")
    comment = command_output(f"{prefix}readelf", "-p", ".comment", str(binary))
    compilers = [
        line.split("]", 1)[1].strip()
        for line in (comment or "").splitlines()
        if line.strip().startswith("[")
    ]
    return {
        "container_image": os.environ.get("RCB_IMAGE"),
        "container_image_id": os.environ.get("RCB_IMAGE_ID"),
        "platform": platform.platform(),
        "python": sys.version,
        "riscv_gcc": gcc.splitlines()[0] if gcc else None,
        # Compilador registrado no próprio ELF, que vale mesmo se a
        # toolchain do ambiente tiver mudado depois do build.
        "binary_compiler": compilers or None,
    }


def gem5_build_info(gem5: Path, gem5_hash: str) -> dict | None:
    """Lê o registro de build-info e confere se ele corresponde ao executável."""
    path = build_info_path(gem5)
    if not path.is_file():
        return None
    info = json.loads(path.read_text(encoding="utf-8"))
    info["matches_executable"] = info.get("gem5_sha256") == gem5_hash
    return info


def write_metadata(path: Path, metadata: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    root = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gem5", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument(
        "config_args",
        nargs="*",
        help="Argumentos extras repassados à configuração gem5, após --.",
    )
    args = parser.parse_args()

    gem5 = args.gem5.resolve()
    binary = args.binary.resolve()
    config = args.config.resolve()

    for label, path in [
        ("gem5", gem5),
        ("binário", binary),
        ("configuração", config),
    ]:
        if not path.is_file():
            parser.error(f"{label} não encontrado: {path}")

    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        + "-"
        + uuid4().hex[:8]
    )
    run_dir = args.results_dir.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    inputs_dir = run_dir / "inputs"
    inputs_dir.mkdir()
    gem5_dir = run_dir / "gem5"
    gem5_dir.mkdir()

    metadata_path = run_dir / "metadata.json"
    metadata = {
        "schema_version": 2,
        "run_id": run_id,
        "started_at": timestamp(),
        "finished_at": None,
        "status": "preparing",
        "exit_code": None,
        "cwd": str(root),
        "project": git_info(root),
        "gem5_repository": git_info(root / "third_party/gem5"),
        "original_binary": str(binary),
        "original_config": str(config),
        "gem5_executable": str(gem5),
    }
    write_metadata(metadata_path, metadata)

    print(f"Resultado da execução: {run_dir}", flush=True)
    exit_code = 1

    with (
        (run_dir / "stdout.log").open("w", encoding="utf-8") as stdout,
        (run_dir / "stderr.log").open("w", encoding="utf-8") as stderr,
    ):
        try:
            saved_binary = inputs_dir / binary.name
            saved_config = inputs_dir / config.name

            if saved_binary == saved_config:
                raise ValueError("Binário e configuração devem ter nomes distintos.")

            shutil.copy2(binary, saved_binary)
            shutil.copy2(config, saved_config)

            command = [
                str(gem5),
                f"--outdir={gem5_dir}",
                str(saved_config),
                "--binary",
                str(saved_binary),
                *args.config_args,
            ]

            (run_dir / "command.txt").write_text(
                shlex.join(command) + "\n",
                encoding="utf-8",
            )

            gem5_hash = sha256(gem5)
            diffs = {}
            for key, directory in [
                ("project", root),
                ("gem5_repository", root / "third_party/gem5"),
            ]:
                if metadata[key]["dirty"]:
                    diff_path = inputs_dir / f"{key}.diff"
                    if save_git_diff(directory, diff_path):
                        diffs[key] = str(diff_path.relative_to(run_dir))

            metadata.update(
                {
                    "status": "running",
                    "command": command,
                    "binary_sha256": sha256(saved_binary),
                    "config_sha256": sha256(saved_config),
                    "gem5_sha256": gem5_hash,
                    "gem5_version": gem5_version(gem5),
                    "gem5_build": gem5_build_info(gem5, gem5_hash),
                    "environment": environment_info(saved_binary),
                    "diffs": diffs,
                }
            )
            write_metadata(metadata_path, metadata)

            result = subprocess.run(
                command,
                cwd=root,
                stdout=stdout,
                stderr=stderr,
                check=False,
            )
            metadata["exit_code"] = result.returncode
            metadata["status"] = (
                "completed" if result.returncode == 0 else "failed"
            )
            exit_code = (
                result.returncode
                if result.returncode >= 0
                else 128 + abs(result.returncode)
            )

        except KeyboardInterrupt:
            metadata["status"] = "interrupted"
            metadata["error"] = "Execução interrompida pelo usuário."
            exit_code = 130

        except Exception as error:
            metadata["status"] = "failed"
            metadata["error"] = f"{type(error).__name__}: {error}"
            stderr.write(metadata["error"] + "\n")
            exit_code = 1

        finally:
            metadata["finished_at"] = timestamp()
            write_metadata(metadata_path, metadata)

    print(f"Status: {metadata['status']}", flush=True)
    print(f"Logs: {run_dir}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())