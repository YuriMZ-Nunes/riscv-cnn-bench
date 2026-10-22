"""Execução de um experimento: YAML → build → gem5 → pasta da execução.

O trabalho de organizar a pasta, compilar, chamar o gem5 e gravar os metadados
fica em scripts/run-gem5.py; aqui se monta o que ele recebe a partir do YAML.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from riscvcnnbench.config import PROJECT_ROOT, Experiment, load_experiment

WRAPPER = PROJECT_ROOT / "scripts" / "run-gem5.py"
GEM5_CONFIG = PROJECT_ROOT / "configs" / "gem5" / "se_riscv_configurable.py"


class RunError(Exception):
    """Problema do ambiente detectado antes de criar a pasta da execução."""


@dataclass(frozen=True)
class PreparedRun:
    """Experimento validado, pronto para executar na pasta `run_dir`."""

    experiment: Experiment
    experiment_path: Path
    gem5: Path
    run_id: str

    @property
    def run_dir(self) -> Path:
        return results_dir(self.experiment) / self.run_id


def default_gem5() -> Path:
    return PROJECT_ROOT / os.environ.get("GEM5_BIN", "third_party/gem5/build/RISCV/gem5.opt")


def new_run_id() -> str:
    """Mesmo formato do wrapper: data/hora UTC + sufixo aleatório."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid4().hex[:8]


def results_dir(experiment: Experiment) -> Path:
    """Pasta de resultados; caminhos relativos partem da raiz do projeto."""
    return (PROJECT_ROOT / experiment.results_dir).resolve()


def resolved_config(experiment: Experiment) -> dict[str, Any]:
    """Configuração com todos os padrões preenchidos, como gravada nos metadados."""
    resolved = experiment.model_dump(mode="json")
    resolved["output"]["dir"] = str(results_dir(experiment))
    return resolved


def build_command(experiment: Experiment, binary: Path) -> list[str]:
    """Compila o benchmark com as flags do experimento direto em `binary`."""
    return [
        "make",
        "-C",
        str(experiment.benchmark_dir),
        f"OUT_DIR={binary.parent}",
        f"OUT={binary}",
        f"FLAGS={' '.join(experiment.compiler.flags)}",
        f"VARIANT={experiment.benchmark.variant}",
    ]


def wrapper_command(
    experiment: Experiment,
    experiment_path: Path,
    resolved_path: Path,
    gem5: Path,
    run_id: str,
) -> list[str]:
    run_dir = results_dir(experiment) / run_id
    binary = run_dir / "inputs" / experiment.benchmark.name
    return [
        sys.executable,
        str(WRAPPER),
        "--gem5",
        str(gem5),
        "--binary",
        str(binary),
        "--config",
        str(GEM5_CONFIG),
        "--results-dir",
        str(results_dir(experiment)),
        "--run-id",
        run_id,
        "--build-command",
        json.dumps(build_command(experiment, binary)),
        "--experiment",
        str(experiment_path),
        "--resolved-config",
        str(resolved_path),
        "--quiet",
        "--",
        *experiment.gem5_args(),
    ]


def check_environment(gem5: Path) -> None:
    """Confere gem5 e toolchain antes de criar a pasta, com mensagens específicas."""
    if not gem5.is_file():
        raise RunError(
            f"gem5 não encontrado em {gem5}. Compile com `make gem5-build` "
            "ou indique outro executável com --gem5."
        )
    compiler = os.environ.get("RISCV_PREFIX", "riscv64-linux-gnu-") + "gcc"
    for tool in (compiler, "make"):
        if shutil.which(tool) is None:
            raise RunError(
                f"{tool} não encontrado. Execute dentro do container: "
                "`make run EXPERIMENT=<yaml>` ou `make shell`."
            )


def prepare_run(path: Path, gem5: Path | None = None) -> PreparedRun:
    """Valida o YAML e o ambiente e decide a pasta; nada é criado ainda.

    Levanta ConfigError (YAML inválido) ou RunError (ambiente incompleto).
    """
    experiment = load_experiment(path)
    gem5 = (gem5 or default_gem5()).resolve()
    check_environment(gem5)
    return PreparedRun(experiment, path, gem5, new_run_id())


def execute(prepared: PreparedRun) -> int:
    """Executa o wrapper; retorna o código de saída dele."""
    with tempfile.TemporaryDirectory(prefix="riscvcnnbench-") as temporary:
        resolved_path = Path(temporary) / "experiment.resolved.json"
        resolved_path.write_text(
            json.dumps(resolved_config(prepared.experiment), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        command = wrapper_command(
            prepared.experiment,
            prepared.experiment_path,
            resolved_path,
            prepared.gem5,
            prepared.run_id,
        )
        return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


def run_experiment(path: Path, gem5: Path | None = None) -> int:
    """Valida, compila e executa o experimento; retorna o código de saída do wrapper."""
    return execute(prepare_run(path, gem5))
