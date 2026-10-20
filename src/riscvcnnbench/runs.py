"""Leitura das pastas de execução: listagem e diagnóstico de falhas.

Lê o `metadata.json` e os logs gravados por scripts/run-gem5.py; veja
docs/results.md para o significado de cada campo.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UNKNOWN_INSTRUCTION = re.compile(r"panic: (Unknown|Illegal|Unimplemented) instruction.*")
GEM5_ERROR = re.compile(r"\b(fatal|panic): .*")
BUILD_ERROR = re.compile(r".*\berror\b.*", re.IGNORECASE)
MISSING_TOOL = re.compile(r".*(No such file or directory|[Cc]ommand not found|not found).*")
# Linhas que o gem5 escreve no stderr; o que sobra é provavelmente do programa.
GEM5_STDERR_LINE = re.compile(r"^(src/|build/|info:|warn:|system\.|\s|$)")


@dataclass(frozen=True)
class Diagnosis:
    """Tipo da falha (`build`, `toolchain`, `benchmark`, `instruction`, `gem5`,
    `preparation`, `interrupted` ou `incomplete`) e mensagem para o usuário."""

    kind: str
    message: str


@dataclass(frozen=True)
class Run:
    path: Path
    metadata: dict[str, Any]

    @property
    def experiment(self) -> str:
        resolved = (self.metadata.get("experiment") or {}).get("resolved") or {}
        return resolved.get("name") or self.path.parent.name

    @property
    def benchmark(self) -> str:
        resolved = (self.metadata.get("experiment") or {}).get("resolved") or {}
        name = (resolved.get("benchmark") or {}).get("name")
        return name or Path(self.metadata.get("original_binary") or "?").name

    @property
    def cpu(self) -> str:
        resolved = (self.metadata.get("experiment") or {}).get("resolved") or {}
        cpu = resolved.get("cpu")
        return f"{cpu['model']}@{cpu['clock']}" if cpu else "-"


def display(path: Path) -> str:
    """Caminho relativo ao diretório atual quando possível, mais curto nas mensagens."""
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(0).strip() if match else None


def program_message(stderr: str) -> str | None:
    """Última linha do stderr que não parece ser do gem5."""
    lines = [line for line in stderr.splitlines() if not GEM5_STDERR_LINE.match(line)]
    return lines[-1].strip() if lines else None


def load_run(path: Path) -> Run:
    metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    return Run(path, metadata)


def list_runs(root: Path) -> list[Run]:
    """Execuções sob `root` (por exemplo results/ ou results/<name>/), mais antigas primeiro."""
    runs = []
    for metadata in root.rglob("metadata.json"):
        try:
            runs.append(load_run(metadata.parent))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(runs, key=lambda run: run.metadata.get("run_id") or run.path.name)


def diagnose(run: Run) -> Diagnosis | None:
    """Explica por que a execução não terminou bem; None se ela foi concluída."""
    metadata = run.metadata
    status = metadata.get("status")
    step = metadata.get("failed_step")
    stdout_log = run.path / "stdout.log"
    stderr_log = run.path / "stderr.log"

    if status == "completed":
        return None

    if status == "interrupted":
        return Diagnosis("interrupted", f"execução interrompida pelo usuário (etapa: {step}).")

    if status != "failed":
        return Diagnosis(
            "incomplete",
            f"a execução não terminou (status '{status}'): ainda está em andamento ou foi "
            f"encerrada abruptamente. Veja {display(stderr_log)}.",
        )

    if step == "build":
        build = metadata.get("build") or {}
        build_log = run.path / (build.get("log") or "build.log")
        text = read_text(build_log)
        missing = first_match(MISSING_TOOL, text)
        if missing and "gcc" in missing:
            return Diagnosis(
                "toolchain",
                f"toolchain RISC-V não encontrada durante o build ({missing}). Execute dentro "
                f"do container (make run ou make shell). Log: {display(build_log)}.",
            )
        error = first_match(BUILD_ERROR, text) or "sem mensagem de erro no log"
        return Diagnosis(
            "build",
            f"o benchmark '{run.benchmark}' não compilou (make retornou "
            f"{build.get('exit_code')}): {error}. Log: {display(build_log)}.",
        )

    if step == "simulation":
        stderr = read_text(stderr_log)
        program_code = metadata.get("program_exit_code")
        if program_code not in (None, 0):
            message = program_message(stderr)
            detail = f" Mensagem do programa: {message}." if message else ""
            return Diagnosis(
                "benchmark",
                f"o benchmark '{run.benchmark}' terminou com código {program_code}: o gem5 "
                f"funcionou, mas o programa reportou resultado inválido ou rejeitou a entrada."
                f"{detail} Veja {display(stdout_log)} e {display(stderr_log)}.",
            )
        unknown = first_match(UNKNOWN_INSTRUCTION, stderr)
        if unknown:
            return Diagnosis(
                "instruction",
                f"o gem5 não reconhece uma instrução do binário ({unknown}). Se o benchmark usa "
                "instruções personalizadas, confira se o gem5 foi compilado a partir do fork "
                f"com elas (make gem5-build). Veja {display(stderr_log)}.",
            )
        error = first_match(GEM5_ERROR, stderr)
        if error:
            return Diagnosis(
                "gem5",
                f"o gem5 terminou com erro ({error}). Veja {display(stderr_log)}.",
            )
        return Diagnosis(
            "gem5",
            f"o gem5 terminou com código {metadata.get('exit_code')} sem concluir a simulação. "
            f"Veja {display(stderr_log)} e {display(stdout_log)}.",
        )

    return Diagnosis(
        "preparation",
        f"falha ao preparar a execução: {metadata.get('error') or 'sem detalhes'}. "
        f"Veja {display(stderr_log)}.",
    )
