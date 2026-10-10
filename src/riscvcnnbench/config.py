"""Formato dos arquivos de experimento (YAML).

Um experimento escolhe benchmark, flags de compilação, CPU, caches, memória e
pasta de saída. Só `name` e `benchmark.name` são obrigatórios; os demais campos
têm padrões equivalentes a configs/gem5/se_riscv.py. Veja docs/experiments.md.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Tamanhos e frequências no formato aceito pelo gem5, por exemplo 32KiB e 1GHz.
SIZE_PATTERN = r"^[1-9][0-9]*(KiB|MiB|GiB)$"
CLOCK_PATTERN = r"^[1-9][0-9]*(\.[0-9]+)?(MHz|GHz)$"


class ConfigError(Exception):
    """Arquivo de experimento ausente, malformado ou inválido."""


class StrictModel(BaseModel):
    # Campos desconhecidos são erro, para que erros de digitação não passem.
    model_config = ConfigDict(extra="forbid")


class BenchmarkConfig(StrictModel):
    name: str = Field(description="Pasta em benchmarks/ com main.c e Makefile.")
    args: list[str] = Field(default=[], description="Argumentos passados ao programa.")


class CompilerConfig(StrictModel):
    flags: list[str] = Field(
        default=["-O2"],
        description="Flags escolhidas pelo experimento; as obrigatórias ficam no Makefile.",
    )


class CpuConfig(StrictModel):
    model: Literal["atomic", "timing", "minor", "o3"] = "atomic"
    clock: str = Field(default="1GHz", pattern=CLOCK_PATTERN)


class CacheLevelConfig(StrictModel):
    size: str = Field(pattern=SIZE_PATTERN)
    assoc: int = Field(default=4, ge=1)


class CacheConfig(StrictModel):
    l1i: CacheLevelConfig | None = None
    l1d: CacheLevelConfig | None = None
    l2: CacheLevelConfig | None = None

    @model_validator(mode="after")
    def l2_requires_l1(self) -> "CacheConfig":
        if self.l2 and not (self.l1i and self.l1d):
            raise ValueError("cache.l2 requer cache.l1i e cache.l1d")
        return self


class MemoryConfig(StrictModel):
    type: Literal["simple", "ddr4"] = "simple"
    size: str = Field(default="512MiB", pattern=SIZE_PATTERN)


class OutputConfig(StrictModel):
    dir: Path | None = Field(default=None, description="Padrão: results/<name>.")


class Experiment(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    description: str = ""
    benchmark: BenchmarkConfig
    compiler: CompilerConfig = CompilerConfig()
    cpu: CpuConfig = CpuConfig()
    cache: CacheConfig = CacheConfig()
    memory: MemoryConfig = MemoryConfig()
    output: OutputConfig = OutputConfig()

    @property
    def benchmark_dir(self) -> Path:
        return PROJECT_ROOT / "benchmarks" / self.benchmark.name

    @property
    def results_dir(self) -> Path:
        return self.output.dir or Path("results") / self.name

    def gem5_args(self) -> list[str]:
        """Argumentos para configs/gem5/se_riscv_configurable.py."""
        args = [f"--arg={arg}" for arg in self.benchmark.args]
        args += [f"--cpu={self.cpu.model}", f"--clock={self.cpu.clock}"]
        for level in ("l1i", "l1d", "l2"):
            cache = getattr(self.cache, level)
            if cache:
                args += [f"--{level}-size={cache.size}", f"--{level}-assoc={cache.assoc}"]
        args += [f"--mem-type={self.memory.type}", f"--mem-size={self.memory.size}"]
        return args


def format_validation_error(error: ValidationError) -> str:
    lines = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "(raiz)"
        lines.append(f"  {location}: {item['msg']}")
    return "\n".join(lines)


def load_experiment(path: Path) -> Experiment:
    if not path.is_file():
        raise ConfigError(f"arquivo não encontrado: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigError(f"YAML inválido em {path}:\n{error}") from error

    if not isinstance(data, dict):
        raise ConfigError(f"{path} deve conter um mapeamento YAML com os campos do experimento")

    try:
        experiment = Experiment.model_validate(data)
    except ValidationError as error:
        raise ConfigError(f"{path} inválido:\n{format_validation_error(error)}") from error

    if not (experiment.benchmark_dir / "Makefile").is_file():
        raise ConfigError(
            f"{path} inválido:\n  benchmark.name: benchmark não encontrado em "
            f"benchmarks/{experiment.benchmark.name}/"
        )

    return experiment
