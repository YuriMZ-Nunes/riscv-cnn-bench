"""Formato dos arquivos de experimento (YAML).

Um experimento escolhe benchmark (e variante do kernel), flags de compilação,
CPU, caches, memória e pasta de saída. Só `name` e `benchmark.name` são obrigatórios; os demais campos
têm padrões equivalentes a configs/gem5/se_riscv.py. Caches e memória podem vir de um cenário
nomeado de configs/scenarios.yaml (`scenario`). Veja docs/experiments.md e docs/scenarios.md.
"""

import difflib
import functools
from pathlib import Path
from typing import Any, Literal, TypeVar, get_args

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_PATH = PROJECT_ROOT / "configs" / "scenarios.yaml"

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
    variant: Literal["ref", "custom", "rvv"] = Field(
        default="ref",
        description="Implementação do kernel: referência, instruções personalizadas ou RVV.",
    )
    cache_state: Literal["warm", "cold"] = Field(
        default="warm",
        description="Caches no início da ROI: aquecidas pela inicialização ou esvaziadas pelo gem5.",
    )

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


# Latência do mul nas unidades padrão da Minor e da O3; padrão de cpu.custom_latency.
MUL_LATENCY = 3


class CpuConfig(StrictModel):
    model: Literal["atomic", "timing", "minor", "o3", "o3-edge"] = "atomic"
    clock: str = Field(default="1GHz", pattern=CLOCK_PATTERN)
    vlen: Literal[128, 256, 512, 1024] = Field(
        default=256, description="VLEN da extensão V, em bits (padrão do gem5)."
    )
    custom_latency: int = Field(
        default=MUL_LATENCY,
        ge=1,
        le=64,
        description="Latência, em ciclos, de cnn.dot8, cnn.dwmac e cnn.rqnt[.relu].",
    )
    custom_units: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description=(
            "Unidades só para cnn.dot8, cnn.dwmac e cnn.rqnt[.relu] (RCB-33). Padrão: a "
            "montagem de antes, 1 unidade própria na minor e as IntMultDiv, divididas com "
            "o mul, na o3 e na o3-edge."
        ),
    )
    custom_pipelined: bool = Field(
        default=True,
        description="false: a unidade só aceita outra instrução depois da latência inteira.",
    )

    @model_validator(mode="after")
    def latency_needs_pipeline(self) -> "CpuConfig":
        if self.custom_latency != MUL_LATENCY and self.model in ("atomic", "timing"):
            raise ValueError(
                f"cpu.custom_latency só tem efeito nas CPUs minor, o3 e o3-edge; a "
                f"{self.model} não modela a latência das unidades funcionais "
                f"(use {MUL_LATENCY}, o padrão)"
            )
        if self.model in ("atomic", "timing"):
            for name, changed, hint in (
                ("custom_units", self.custom_units is not None, "tire o campo"),
                ("custom_pipelined", not self.custom_pipelined, "use true, o padrão"),
            ):
                if changed:
                    raise ValueError(
                        f"cpu.{name} só tem efeito nas CPUs minor, o3 e o3-edge; a "
                        f"{self.model} não modela as unidades funcionais ({hint})"
                    )
        # Na minor, a montagem de antes já é 1 unidade própria: 1 é o padrão.
        if self.model == "minor" and self.custom_units == 1:
            self.custom_units = None
        return self

    @model_serializer(mode="wrap")
    def without_default_units(self, handler: Any) -> dict[str, Any]:
        """Os campos da RCB-33 só aparecem quando mudam: a chave das execuções
        anteriores não muda."""
        data = handler(self)
        if data.get("custom_units") is None:
            data.pop("custom_units", None)
        if data.get("custom_pipelined") is True:
            data.pop("custom_pipelined", None)
        return data


# Padrões de configs/gem5/se_riscv_configurable.py para os ajustes das caches
# (RCB-32). Um ajuste igual ao padrão sai da configuração resolvida, como se fosse
# omitido: assim a chave das execuções anteriores não muda.
CACHE_LATENCY = {"l1i": 2, "l1d": 2, "l2": 10}
CACHE_MSHRS = 16
CACHE_TARGETS = 20
CACHE_LINE = 64
NO_PREFETCHER = "none"
UNITS = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}


def size_bytes(text: str) -> int:
    """32KiB → 32768 (o formato de SIZE_PATTERN)."""
    for unit, factor in UNITS.items():
        if text.endswith(unit):
            return int(text.removesuffix(unit)) * factor
    raise ValueError(f"tamanho sem unidade: {text!r}")


class CacheLevelConfig(StrictModel):
    size: str = Field(pattern=SIZE_PATTERN)
    assoc: int = Field(default=4, ge=1)
    latency: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description="Ciclos de tag, dados e resposta. Padrão: 2 na L1i e na L1d, 10 na L2.",
    )
    mshrs: int | None = Field(
        default=None, ge=1, le=1024, description="Faltas pendentes ao mesmo tempo. Padrão: 16."
    )
    targets: int | None = Field(
        default=None, ge=1, le=1024, description="Acessos à espera por MSHR. Padrão: 20."
    )
    prefetcher: Literal["none", "stride", "tagged"] = Field(
        default=NO_PREFETCHER,
        description="none | stride (passo constante) | tagged (próxima linha).",
    )

    @field_validator("mshrs")
    @classmethod
    def default_mshrs(cls, value: int | None) -> int | None:
        return None if value == CACHE_MSHRS else value

    @field_validator("targets")
    @classmethod
    def default_targets(cls, value: int | None) -> int | None:
        return None if value == CACHE_TARGETS else value

    @model_serializer(mode="wrap")
    def without_defaults(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for key in ("latency", "mshrs", "targets"):
            if data.get(key) is None:
                data.pop(key, None)
        if data.get("prefetcher") == NO_PREFETCHER:
            data.pop("prefetcher", None)
        return data


class CacheConfig(StrictModel):
    line: Literal[32, 64, 128] | None = Field(
        default=None, description="Linha de todas as caches, em bytes. Padrão: 64."
    )
    l1i: CacheLevelConfig | None = None
    l1d: CacheLevelConfig | None = None
    l2: CacheLevelConfig | None = None

    @model_validator(mode="after")
    def l2_requires_l1(self) -> "CacheConfig":
        if self.l2 and not (self.l1i and self.l1d):
            raise ValueError("cache.l2 requer cache.l1i e cache.l1d")
        return self

    @model_validator(mode="after")
    def gem5_geometry(self) -> "CacheConfig":
        """Ajustes iguais ao padrão viram omitidos; conjuntos em potência de 2."""
        if self.line == CACHE_LINE:
            self.line = None
        line = self.line or CACHE_LINE
        for level, default in CACHE_LATENCY.items():
            cache = getattr(self, level)
            if cache is None:
                continue
            if cache.latency == default:
                cache.latency = None
            block = line * cache.assoc
            total = size_bytes(cache.size)
            sets = total // block
            if total % block or sets & (sets - 1) or sets < 1:
                raise ValueError(
                    f"cache.{level}: {cache.size} com associatividade {cache.assoc} e linha de "
                    f"{line} bytes não dá um número de conjuntos potência de 2, como o gem5 "
                    "exige (tamanho ÷ (linha × associatividade))"
                )
        return self

    @model_serializer(mode="wrap")
    def without_default_line(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if data.get("line") is None:
            data.pop("line", None)
        return data


class MemoryConfig(StrictModel):
    type: Literal["simple", "ddr4"] = "simple"
    size: str = Field(default="512MiB", pattern=SIZE_PATTERN)


class OutputConfig(StrictModel):
    dir: Path | None = Field(default=None, description="Padrão: results/<name>.")


class Scenario(StrictModel):
    """Cenário de memória nomeado de configs/scenarios.yaml (RCB-18)."""

    description: str
    cache: CacheConfig = CacheConfig()
    memory: MemoryConfig = MemoryConfig()


@functools.cache
def load_scenarios() -> dict[str, Scenario]:
    """Cenários de configs/scenarios.yaml, na ordem do arquivo."""
    data = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8")) or {}
    return {str(name): Scenario.model_validate(item) for name, item in data.items()}


class Experiment(StrictModel):
    name: str = Field(pattern=NAME_PATTERN)
    description: str = ""
    # Antes de cache e memory: os validadores deles consultam o cenário.
    scenario: str | None = Field(
        default=None, description="Cenário de configs/scenarios.yaml; define cache e memory."
    )
    benchmark: BenchmarkConfig
    compiler: CompilerConfig = CompilerConfig()
    cpu: CpuConfig = CpuConfig()
    cache: CacheConfig = CacheConfig()
    memory: MemoryConfig = MemoryConfig()
    output: OutputConfig = OutputConfig()

    @field_validator("scenario")
    @classmethod
    def known_scenario(cls, value: str | None) -> str | None:
        scenarios = load_scenarios()
        if value is None or value in scenarios:
            return value
        close = difflib.get_close_matches(value, scenarios, n=1)
        hint = f"você quis dizer {close[0]!r}?" if close else f"disponíveis: {', '.join(scenarios)}"
        raise ValueError(f"cenário {value!r} não existe em configs/scenarios.yaml; {hint}")

    @field_validator("cache", "memory", mode="before")
    @classmethod
    def not_with_scenario(cls, value: Any, info: ValidationInfo) -> Any:
        scenario = info.data.get("scenario")
        if scenario:
            raise ValueError(
                f"não use junto com scenario ({scenario}), que já define cache e memory; "
                "tire um dos dois"
            )
        return value

    @model_validator(mode="after")
    def expand_scenario(self) -> "Experiment":
        if self.scenario:
            scenario = load_scenarios()[self.scenario]
            self.cache = scenario.cache.model_copy(deep=True)
            self.memory = scenario.memory.model_copy(deep=True)
        return self

    @property
    def benchmark_dir(self) -> Path:
        return PROJECT_ROOT / "benchmarks" / self.benchmark.name

    @property
    def results_dir(self) -> Path:
        return self.output.dir or Path("results") / self.name

    def gem5_args(self) -> list[str]:
        """Argumentos para configs/gem5/se_riscv_configurable.py."""
        args = [f"--arg={arg}" for arg in self.benchmark.args]
        args += [f"--cpu={self.cpu.model}", f"--clock={self.cpu.clock}", f"--vlen={self.cpu.vlen}"]
        args += [f"--custom-latency={self.cpu.custom_latency}"]
        if self.cpu.custom_units is not None:
            args.append(f"--custom-units={self.cpu.custom_units}")
        if not self.cpu.custom_pipelined:
            args.append("--custom-unpipelined")
        if self.cache.line:
            args += [f"--cache-line={self.cache.line}"]
        for level in ("l1i", "l1d", "l2"):
            cache = getattr(self.cache, level)
            if cache:
                args += [f"--{level}-size={cache.size}", f"--{level}-assoc={cache.assoc}"]
                for name in ("latency", "mshrs", "targets"):
                    value = getattr(cache, name)
                    if value is not None:
                        args.append(f"--{level}-{name}={value}")
                if cache.prefetcher != NO_PREFETCHER:
                    args.append(f"--{level}-prefetcher={cache.prefetcher}")
        args += [f"--mem-type={self.memory.type}", f"--mem-size={self.memory.size}"]
        args += [f"--roi-caches={self.benchmark.cache_state}"]
        return args


Model = TypeVar("Model", bound=BaseModel)


def _model_at(location: tuple[Any, ...], root: type[BaseModel]) -> type[BaseModel] | None:
    """Modelo Pydantic que descreve o campo em `location` (índices de lista são pulados)."""
    model: type[BaseModel] = root
    for part in location:
        if isinstance(part, int):
            continue
        field = model.model_fields.get(str(part))
        if field is None:
            return None
        candidates = [field.annotation, *get_args(field.annotation)]
        nested = [c for c in candidates if isinstance(c, type) and issubclass(c, BaseModel)]
        if not nested:
            return None
        model = nested[0]
    return model


def _describe(item: dict[str, Any], root: type[BaseModel] = Experiment) -> str:
    """Traduz um erro do Pydantic em uma explicação curta em português."""
    kind = item["type"]
    location = item["loc"]
    value = item.get("input")
    context = item.get("ctx", {})

    if kind == "missing":
        return "campo obrigatório ausente"

    if kind == "extra_forbidden":
        model = _model_at(location[:-1], root)
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
        model = _model_at(location[:-1], root)
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

    if kind == "less_than_equal":
        return f"deve ser no máximo {context['le']}, mas recebeu {value!r}"

    if kind == "too_short":
        return f"deve ter pelo menos {context['min_length']} item(ns)"

    if kind == "bool_parsing" or kind == "bool_type":
        return f"deve ser true ou false, mas recebeu {value!r}"

    if kind == "value_error":
        return str(context.get("error", item["msg"]))

    return item["msg"]


class _LineTracker:
    """Linhas das chaves de um documento YAML, para apontar onde está cada erro."""

    def __init__(self, root: yaml.Node | None) -> None:
        self.lines: dict[tuple[str, ...], int] = {}
        self.duplicates: list[tuple[tuple[str, ...], int]] = []
        if root is not None:
            self._walk(root, ())

    def _walk(self, node: yaml.Node, path: tuple[str, ...]) -> None:
        if isinstance(node, yaml.SequenceNode):
            for index, item in enumerate(node.value):
                child = (*path, str(index))
                self.lines[child] = item.start_mark.line + 1
                self._walk(item, child)
            return
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
    # "[key]" é como o Pydantic marca o erro na chave de um dicionário.
    field = ".".join(str(part) for part in location if part != "[key]") or "(raiz)"
    prefix = f"linha {line}: " if line else ""
    return (line or 0, f"{prefix}{field}: {text}")


def available_benchmarks() -> list[str]:
    root = PROJECT_ROOT / "benchmarks"
    return sorted(path.parent.name for path in root.glob("*/Makefile"))


def available_variants(benchmark_dir: Path) -> list[str]:
    """Variantes de um benchmark: `ref` e uma por arquivo kernel_<variante>.c."""
    variants = {path.stem.removeprefix("kernel_") for path in benchmark_dir.glob("kernel_*.c")}
    return ["ref", *(v for v in ("custom", "rvv") if v in variants)]


def uses_roi(benchmark_dir: Path) -> bool:
    """O benchmark marca a região de interesse (rcb_roi_begin da base comum, RCB-11)?

    Se marca, o stats.txt tem 2 blocos (ROI e resto do programa); se não, 1.
    """
    return any(
        "rcb_roi_begin" in source.read_text(encoding="utf-8", errors="replace")
        for source in benchmark_dir.glob("*.c")
    )


def _cold_problems(experiment: Experiment, lines: _LineTracker) -> list[tuple[int, str]]:
    """Caches frias exigem caches e um benchmark que marque a ROI (onde o gem5 as esvazia)."""
    location = ("benchmark", "cache_state")
    texts = []
    if not (experiment.cache.l1i or experiment.cache.l1d):
        texts.append(
            "'cold' esvazia as caches no início da ROI, mas o experimento não tem caches; "
            "configure cache ou use um scenario com caches"
        )
    if not uses_roi(experiment.benchmark_dir):
        texts.append(
            f"'cold' exige um benchmark que marque a região de interesse (rcb_roi_begin); "
            f"{experiment.benchmark.name!r} não marca"
        )
    return [_problem(lines.line_of(location), location, text) for text in texts]


def load_yaml(
    path: Path, minimum: str
) -> tuple[dict[str, Any], _LineTracker, list[tuple[int, str]]]:
    """Lê um arquivo YAML que deve ser um mapeamento de campos.

    Devolve os dados, as linhas das chaves e os campos repetidos já como
    problemas `(linha, mensagem)`. Arquivo ausente, vazio, com sintaxe inválida
    ou que não seja um mapeamento levanta ConfigError; `minimum` diz o que o
    arquivo precisa ter, para a mensagem de arquivo vazio.
    """
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
        raise ConfigError(path, [f"arquivo vazio; o mínimo é {minimum}"])
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
    return data, lines, problems


def validate_model(
    model: type[Model], data: Any, lines: _LineTracker
) -> tuple[Model | None, list[tuple[int, str]]]:
    """Valida `data` no modelo; os erros viram problemas `(linha, mensagem)` em português."""
    try:
        return model.model_validate(data), []
    except ValidationError as error:
        return None, [
            _problem(lines.line_of(item["loc"]), item["loc"], _describe(item, model))
            for item in error.errors()
        ]


def _benchmark_problems(experiment: Experiment, lines: _LineTracker) -> list[tuple[int, str]]:
    """Problemas que dependem de benchmarks/: benchmark, variante e ROI para caches frias."""
    if not (experiment.benchmark_dir / "Makefile").is_file():
        location = ("benchmark", "name")
        return [
            _problem(
                lines.line_of(location),
                location,
                f"benchmark {experiment.benchmark.name!r} não encontrado em benchmarks/; "
                f"disponíveis: {', '.join(available_benchmarks()) or 'nenhum'}",
            )
        ]
    problems = []
    variants = available_variants(experiment.benchmark_dir)
    if experiment.benchmark.variant not in variants:
        location = ("benchmark", "variant")
        problems.append(
            _problem(
                lines.line_of(location),
                location,
                f"o benchmark {experiment.benchmark.name!r} não tem a variante "
                f"{experiment.benchmark.variant!r}; disponíveis: {', '.join(variants)}",
            )
        )
    if experiment.benchmark.cache_state == "cold":
        problems += _cold_problems(experiment, lines)
    return problems


def raise_problems(path: Path, problems: list[tuple[int, str]]) -> None:
    """ConfigError com os problemas ordenados por linha, se houver algum."""
    if problems:
        raise ConfigError(path, [message for _, message in sorted(problems, key=lambda p: p[0])])


def load_experiment(path: Path) -> Experiment:
    """Lê e valida um experimento, reunindo todos os problemas em um ConfigError."""
    data, lines, problems = load_yaml(path, "name e benchmark.name")
    experiment, invalid = validate_model(Experiment, data, lines)
    problems += invalid
    # O benchmark e suas variantes só são procurados com o restante válido.
    if experiment:
        problems += _benchmark_problems(experiment, lines)
    raise_problems(path, problems)
    assert experiment is not None
    return experiment


def check_experiment(data: dict[str, Any], source: Path) -> Experiment:
    """Valida um experimento montado em memória, com as regras de load_experiment.

    Usado pelas campanhas, que geram os experimentos; as mensagens não têm linha.
    """
    lines = _LineTracker(None)
    experiment, problems = validate_model(Experiment, data, lines)
    if experiment:
        problems += _benchmark_problems(experiment, lines)
    raise_problems(source, problems)
    assert experiment is not None
    return experiment
