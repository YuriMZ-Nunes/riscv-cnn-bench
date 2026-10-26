"""Leitura das pastas de execução: listagem, diagnóstico de falhas e métricas.

Lê o `metadata.json`, os logs e o `gem5/stats.txt` gravados por
scripts/run-gem5.py; veja docs/results.md para o significado de cada campo.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riscvcnnbench.config import PROJECT_ROOT, uses_roi
from riscvcnnbench.parser import RegionStats, StatsError, cpu_model, read_region

# Linha da configuração gem5 quando a simulação recebe SIGINT antes do fim.
INTERRUPTED_SIMULATION = re.compile(r"^Simulação interrompida no tick \d+", re.MULTILINE)
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
    def resolved(self) -> dict[str, Any]:
        """Configuração resolvida do YAML; vazia nas execuções sem YAML."""
        return (self.metadata.get("experiment") or {}).get("resolved") or {}

    @property
    def experiment(self) -> str:
        return self.resolved.get("name") or self.path.parent.name

    @property
    def benchmark(self) -> str:
        name = (self.resolved.get("benchmark") or {}).get("name")
        return name or Path(self.metadata.get("original_binary") or "?").name

    @property
    def cpu(self) -> str:
        cpu = self.resolved.get("cpu")
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


def region_stats(run: Run) -> RegionStats:
    """Métricas da ROI da execução, ou do programa inteiro se o benchmark não tem ROI.

    O número de blocos esperado vem do fonte do benchmark (`uses_roi`) e o modelo da
    CPU, do config.ini gravado pelo gem5. Erros saem como StatsError com o caminho.
    """
    stats = run.path / "gem5" / "stats.txt"
    if not stats.is_file():
        raise StatsError(f"{display(stats)} não existe: o gem5 não gravou estatísticas.")
    benchmark_dir = PROJECT_ROOT / "benchmarks" / run.benchmark
    has_roi = uses_roi(benchmark_dir) if benchmark_dir.is_dir() else None
    cpu = cpu_model(stats.with_name("config.ini")) or (run.resolved.get("cpu") or {}).get("model")
    try:
        return read_region(stats, has_roi, cpu)
    except StatsError as error:
        raise StatsError(f"{display(stats)}: {error}.") from error


def summary(stats: RegionStats) -> str:
    """Resumo de uma linha: região, instruções, ciclos e IPC."""
    metrics = stats.metrics
    parts = [
        "ROI" if stats.region == "roi" else "programa inteiro",
        f"{metrics['insts']} instruções",
    ]
    if metrics["cycles"] is None:
        parts.append(f"sem ciclos ({stats.missing['cycles']})")
    else:
        parts.append(f"{metrics['cycles']} ciclos")
    if metrics["ipc"] is not None:
        parts.append(f"IPC {metrics['ipc']:.3f}")
    return ", ".join(parts)


def metric_cells(run: Run) -> list[str]:
    """INSTS, CICLOS e IPC de uma execução concluída para a tabela de `runs`.

    `-` quando não há valor (execução não concluída, ciclos na atomic) e `?` quando
    o stats.txt não pôde ser lido; o motivo aparece em `riscvcnnbench stats`.
    """
    if run.metadata.get("status") != "completed":
        return ["-", "-", "-"]
    try:
        metrics = region_stats(run).metrics
    except StatsError:
        return ["?", "?", "?"]
    cycles, ipc = metrics["cycles"], metrics["ipc"]
    return [
        str(metrics["insts"]),
        "-" if cycles is None else str(cycles),
        "-" if ipc is None else f"{ipc:.3f}",
    ]


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
        if INTERRUPTED_SIMULATION.search(read_text(stdout_log)):
            return Diagnosis(
                "interrupted",
                "a simulação foi interrompida (SIGINT) antes do fim do programa; as "
                f"estatísticas estão incompletas. Rode de novo. Veja {display(stdout_log)}.",
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
