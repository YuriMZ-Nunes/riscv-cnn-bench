"""Formato dos arquivos de experimento (YAML).

Um experimento escolhe benchmark, flags de compilação, CPU, caches, memória e
pasta de saída. Só `name` e `benchmark.name` são obrigatórios; os demais campos
têm padrões equivalentes a configs/gem5/se_riscv.py. Veja docs/experiments.md.
"""

import difflib
from pathlib import Path
from typing import Any, Literal, get_args

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Tamanhos e frequências no formato aceito pelo gem5, por exemplo 32KiB e 1GHz.
SIZE_PATTERN = r"^[1-9][0-9]*(KiB|MiB|GiB)$"
CLOCK_PATTERN = r"^[1-9][0-9]*(\.[0-9]+)?(MHz|GHz)$"
NAME_PATTERN = r"^[A-Za-z0-9_-]+$"

# Explicação mostrada quando um valor não segue o formato esperado.
FORMAT_HINTS = {
    SIZE_PATTERN: "use um tamanho como 32KiB, 512MiB ou 1GiB",
    CLOCK_PATTERN: "use uma frequência como 800MHz ou 2GHz",
    NAME_PATTERN: "use apenas letras, números, _ e -",
}


class ConfigError(Exception):
    """Arquivo de experimento ausente, malformado ou inválido.

    `problems` lista cada problema encontrado, um por linha da mensagem.
    """

    def __init__(self, path: Path, problems: list[str]) -> None:
        self.path = path
        self.problems = problems
        if len(problems) == 1:
            message = f"{path}: {problems[0]}"
        else:
            listed = "\n".join(f"  {problem}" for problem in problems)
            message = f"{path} tem {len(problems)} problemas:\n{listed}"
        super().__init__(message)


class StrictModel(BaseModel):
    # Campos desconhecidos são erro, para que erros de digitação não passem.
    model_config = ConfigDict(extra="forbid")


class BenchmarkConfig(StrictModel):
    name: str = Field(description="Pasta em benchmarks/ com main.c e Makefile.")
    args: list[str] = Field(default=[], description="Argumentos passados ao programa.")

    @field_validator("args", mode="before")
    @classmethod
    def numbers_as_strings(cls, value: Any) -> Any:
        # Permite `args: [4096, 2]` sem exigir aspas em cada número.
        if isinstance(value, list):
            return [
                str(item) if isinstance(item, int | float) and not isinstance(item, bool) else item
                for item in value
            ]
        return value


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
    name: str = Field(pattern=NAME_PATTERN)
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


def _model_at(location: tuple[Any, ...]) -> type[BaseModel] | None:
    """Modelo Pydantic que descreve o campo em `location`."""
    model: type[BaseModel] = Experiment
    for part in location:
        field = model.model_fields.get(str(part))
        if field is None:
            return None
        candidates = [field.annotation, *get_args(field.annotation)]
        nested = [c for c in candidates if isinstance(c, type) and issubclass(c, BaseModel)]
        if not nested:
            return None
        model = nested[0]
    return model


def _describe(item: dict[str, Any]) -> str:
    """Traduz um erro do Pydantic em uma explicação curta em português."""
    kind = item["type"]
    location = item["loc"]
    value = item.get("input")
    context = item.get("ctx", {})

    if kind == "missing":
        return "campo obrigatório ausente"

    if kind == "extra_forbidden":
        model = _model_at(location[:-1])
        valid = sorted(model.model_fields) if model else []
        close = difflib.get_close_matches(str(location[-1]), valid, n=1)
        if close:
            return f"campo desconhecido; você quis dizer '{close[0]}'?"
        return f"campo desconhecido; campos válidos aqui: {', '.join(valid)}"

    if kind == "literal_error":
        expected = str(context["expected"]).replace(" or ", " ou ")
        return f"valor {value!r} inválido; use {expected}"

    if kind == "string_pattern_mismatch":
        hint = FORMAT_HINTS.get(context.get("pattern", ""), "formato inválido")
        return f"valor {value!r} inválido; {hint}"

    if kind == "string_type":
        model = _model_at(location[:-1])
        field = model.model_fields.get(str(location[-1])) if model else None
        patterns = [getattr(m, "pattern", None) for m in field.metadata] if field else []
        hint = next((FORMAT_HINTS[p] for p in patterns if p in FORMAT_HINTS), None)
        message = f"deve ser texto, mas recebeu {value!r}"
        return f"{message}; {hint}" if hint else message

    if kind == "list_type":
        return f'deve ser uma lista, como ["a", "b"], mas recebeu {value!r}'

    if kind in ("model_type", "model_attributes_type", "dict_type"):
        return f"deve conter subcampos (um mapeamento YAML), mas recebeu {value!r}"

    if kind in ("int_type", "int_parsing", "int_from_float"):
        return f"deve ser um número inteiro, mas recebeu {value!r}"

    if kind == "greater_than_equal":
        return f"deve ser no mínimo {context['ge']}, mas recebeu {value!r}"

    if kind == "value_error":
        return str(context.get("error", item["msg"]))

    return item["msg"]


class _LineTracker:
    """Linhas das chaves de um documento YAML, para apontar onde está cada erro."""

    def __init__(self, root: yaml.Node) -> None:
        self.lines: dict[tuple[str, ...], int] = {}
        self.duplicates: list[tuple[tuple[str, ...], int]] = []
        self._walk(root, ())

    def _walk(self, node: yaml.Node, path: tuple[str, ...]) -> None:
        if not isinstance(node, yaml.MappingNode):
            return
        for key, value in node.value:
            child = (*path, str(key.value))
            line = key.start_mark.line + 1
            if child in self.lines:
                self.duplicates.append((child, line))
            else:
                self.lines[child] = line
            self._walk(value, child)

    def line_of(self, location: tuple[Any, ...]) -> int | None:
        path = tuple(str(part) for part in location)
        while path:
            if path in self.lines:
                return self.lines[path]
            path = path[:-1]
        return None


def _problem(line: int | None, location: tuple[Any, ...], text: str) -> tuple[int, str]:
    field = ".".join(str(part) for part in location) or "(raiz)"
    prefix = f"linha {line}: " if line else ""
    return (line or 0, f"{prefix}{field}: {text}")


def available_benchmarks() -> list[str]:
    root = PROJECT_ROOT / "benchmarks"
    return sorted(path.parent.name for path in root.glob("*/Makefile"))


def load_experiment(path: Path) -> Experiment:
    """Lê e valida um experimento, reunindo todos os problemas em um ConfigError."""
    if not path.is_file():
        raise ConfigError(path, ["arquivo não encontrado"])

    text = path.read_text(encoding="utf-8")
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        problem = getattr(error, "problem", None) or str(error)
        where = f"linha {mark.line + 1}, coluna {mark.column + 1}: " if mark else ""
        raise ConfigError(
            path,
            [f"{where}YAML inválido ({problem}); confira a indentação e os ':'"],
        ) from error

    if data is None:
        raise ConfigError(path, ["arquivo vazio; o mínimo é name e benchmark.name"])
    if not isinstance(data, dict):
        raise ConfigError(
            path,
            [
                "o arquivo deve ser um mapeamento de campos (name:, benchmark:, ...), não uma lista ou valor"
            ],
        )

    lines = _LineTracker(root)
    problems = [
        _problem(line, location, "campo repetido; só o último valor seria usado")
        for location, line in lines.duplicates
    ]

    experiment = None
    try:
        experiment = Experiment.model_validate(data)
    except ValidationError as error:
        for item in error.errors():
            problems.append(_problem(lines.line_of(item["loc"]), item["loc"], _describe(item)))

    if experiment and not (experiment.benchmark_dir / "Makefile").is_file():
        location = ("benchmark", "name")
        problems.append(
            _problem(
                lines.line_of(location),
                location,
                f"benchmark {experiment.benchmark.name!r} não encontrado em benchmarks/; "
                f"disponíveis: {', '.join(available_benchmarks()) or 'nenhum'}",
            )
        )

    if problems:
        raise ConfigError(path, [message for _, message in sorted(problems, key=lambda p: p[0])])

    assert experiment is not None
    return experiment
