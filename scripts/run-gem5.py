"""Executa gem5 e preserva os artefatos de cada execução.

Argumentos após `--` são repassados à configuração gem5, por exemplo:

    run-gem5.py --gem5 ... --binary ... --config ... --results-dir ... -- --cpu timing

Com --build-command, o benchmark é compilado dentro da pasta da execução antes
do gem5; --run-id permite que quem chama conheça essa pasta de antemão
(usado por `riscvcnnbench run`).
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

SCHEMA_VERSION = 3

from provenance import (
    build_info_path,
    command_output,
    gem5_version,
    git_info,
    save_git_diff,
    sha256,
)


class BuildError(Exception):
    """O comando de build terminou com código diferente de zero."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


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
        "--run-id",
        help="Identificador da execução. Padrão: data/hora UTC + sufixo aleatório.",
    )
    parser.add_argument(
        "--build-command",
        type=json.loads,
        help="Comando de build, como lista JSON, executado antes do gem5.",
    )
    parser.add_argument(
        "--experiment",
        type=Path,
        help="YAML do experimento, copiado para inputs/experiment.yaml.",
    )
    parser.add_argument(
        "--resolved-config",
        type=Path,
        help="Configuração resolvida (JSON), copiada e incluída nos metadados.",
    )
    parser.add_argument(
        "config_args",
        nargs="*",
        help="Argumentos extras repassados à configuração gem5, após --.",
    )
    args = parser.parse_args()

    gem5 = args.gem5.resolve()
    binary = args.binary.resolve()
    config = args.config.resolve()

    build_command = args.build_command
    if build_command is not None and (
        not isinstance(build_command, list)
        or not build_command
        or not all(isinstance(item, str) for item in build_command)
    ):
        parser.error("--build-command deve ser uma lista JSON de textos.")

    required = [("gem5", gem5), ("configuração", config)]
    # Com build, o binário só existe depois da compilação.
    if build_command is None:
        required.append(("binário", binary))
    for label, path in [
        *required,
        ("experimento", args.experiment),
        ("configuração resolvida", args.resolved_config),
    ]:
        if path is not None and not path.is_file():
            parser.error(f"{label} não encontrado: {path}")

    run_id = args.run_id or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        + "-"
        + uuid4().hex[:8]
    )
    if Path(run_id).name != run_id or run_id in (".", ".."):
        parser.error(f"--run-id inválido: {run_id}")
    run_dir = args.results_dir.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    inputs_dir = run_dir / "inputs"
    inputs_dir.mkdir()
    gem5_dir = run_dir / "gem5"
    gem5_dir.mkdir()

    metadata_path = run_dir / "metadata.json"
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": timestamp(),
        "finished_at": None,
        "status": "preparing",
        "failed_step": None,
        "exit_code": None,
        "cwd": str(root),
        "project": git_info(root),
        "gem5_repository": git_info(root / "third_party/gem5"),
        "original_binary": str(binary),
        "original_config": str(config),
        "gem5_executable": str(gem5),
        "experiment": None,
        "build": None,
    }
    write_metadata(metadata_path, metadata)

    print(f"Resultado da execução: {run_dir}", flush=True)
    exit_code = 1

    with (
        (run_dir / "stdout.log").open("w", encoding="utf-8") as stdout,
        (run_dir / "stderr.log").open("w", encoding="utf-8") as stderr,
    ):
        step = "preparation"
        try:
            saved_binary = inputs_dir / binary.name
            saved_config = inputs_dir / config.name
            saved_experiment = inputs_dir / "experiment.yaml"
            saved_resolved = inputs_dir / "experiment.resolved.json"

            names = [saved_binary.name, saved_config.name]
            names += [path.name for path in (saved_experiment, saved_resolved)]
            if len(set(names)) != len(names):
                raise ValueError(f"Arquivos de entrada com nomes repetidos: {names}")

            shutil.copy2(config, saved_config)

            if args.experiment or args.resolved_config:
                experiment = {
                    "source": None,
                    "file": None,
                    "sha256": None,
                    "resolved_file": None,
                    "resolved": None,
                }
                if args.experiment:
                    shutil.copy2(args.experiment, saved_experiment)
                    experiment["source"] = str(args.experiment.resolve())
                    experiment["file"] = str(saved_experiment.relative_to(run_dir))
                    experiment["sha256"] = sha256(saved_experiment)
                if args.resolved_config:
                    shutil.copy2(args.resolved_config, saved_resolved)
                    experiment["resolved_file"] = str(saved_resolved.relative_to(run_dir))
                    experiment["resolved"] = json.loads(
                        saved_resolved.read_text(encoding="utf-8")
                    )
                metadata["experiment"] = experiment

            if build_command is not None:
                step = "build"
                metadata["status"] = "building"
                metadata["build"] = {
                    "command": build_command,
                    "exit_code": None,
                    "log": "build.log",
                }
                write_metadata(metadata_path, metadata)
                (run_dir / "command.txt").write_text(
                    "# build\n" + shlex.join(build_command) + "\n",
                    encoding="utf-8",
                )
                with (run_dir / "build.log").open("w", encoding="utf-8") as build_log:
                    built = subprocess.run(
                        build_command,
                        cwd=root,
                        stdout=build_log,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                metadata["build"]["exit_code"] = built.returncode
                if built.returncode != 0:
                    raise BuildError(built.returncode)
                if not binary.is_file():
                    raise FileNotFoundError(f"build não gerou o binário {binary}")
                step = "preparation"

            # O build pode gerar o binário diretamente em inputs/.
            if binary != saved_binary:
                shutil.copy2(binary, saved_binary)

            command = [
                str(gem5),
                f"--outdir={gem5_dir}",
                str(saved_config),
                "--binary",
                str(saved_binary),
                *args.config_args,
            ]

            gem5_line = shlex.join(command) + "\n"
            if build_command is not None:
                gem5_line = "# gem5\n" + gem5_line
            with (run_dir / "command.txt").open("a", encoding="utf-8") as command_file:
                command_file.write(gem5_line)

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

            step = "simulation"
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
            if result.returncode != 0:
                metadata["failed_step"] = step
            exit_code = (
                result.returncode
                if result.returncode >= 0
                else 128 + abs(result.returncode)
            )

        except KeyboardInterrupt:
            metadata["status"] = "interrupted"
            metadata["failed_step"] = step
            metadata["error"] = "Execução interrompida pelo usuário."
            exit_code = 130

        except BuildError as error:
            metadata["status"] = "failed"
            metadata["failed_step"] = step
            metadata["error"] = f"Build falhou com código {error.code}; veja build.log."
            stderr.write(metadata["error"] + "\n")
            exit_code = error.code if error.code > 0 else 1

        except Exception as error:
            metadata["status"] = "failed"
            metadata["failed_step"] = step
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