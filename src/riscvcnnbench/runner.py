"""Execução de um experimento: YAML → build → gem5 → pasta da execução.

O trabalho de organizar a pasta, compilar, chamar o gem5 e gravar os metadados
fica em scripts/run-gem5.py; aqui se monta o que ele recebe a partir do YAML.
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from riscvcnnbench.config import PROJECT_ROOT, Experiment, load_experiment

WRAPPER = PROJECT_ROOT / "scripts" / "run-gem5.py"
GEM5_CONFIG = PROJECT_ROOT / "configs" / "gem5" / "se_riscv_configurable.py"


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
        "--",
        *experiment.gem5_args(),
    ]


def run_experiment(path: Path, gem5: Path | None = None) -> int:
    """Valida, compila e executa o experimento; retorna o código de saída do wrapper.

    Levanta ConfigError se o YAML for inválido, antes de criar qualquer pasta.
    """
    experiment = load_experiment(path)
    with tempfile.TemporaryDirectory(prefix="riscvcnnbench-") as temporary:
        resolved_path = Path(temporary) / "experiment.resolved.json"
        resolved_path.write_text(
            json.dumps(resolved_config(experiment), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        command = wrapper_command(
            experiment,
            path,
            resolved_path,
            (gem5 or default_gem5()).resolve(),
            new_run_id(),
        )
        return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode
