"""Executa gem5 e preserva os artefatos de cada execução."""

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_info(directory: Path) -> dict:
    def query(*args: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    status = query("status", "--porcelain")
    return {
        "commit": query("rev-parse", "HEAD"),
        "dirty": None if status is None else bool(status),
        "status": status,
    }


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
        "schema_version": 1,
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
            ]

            (run_dir / "command.txt").write_text(
                shlex.join(command) + "\n",
                encoding="utf-8",
            )

            metadata.update(
                {
                    "status": "running",
                    "command": command,
                    "binary_sha256": sha256(saved_binary),
                    "config_sha256": sha256(saved_config),
                    "gem5_sha256": sha256(gem5),
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