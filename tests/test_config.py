from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench.cli import app
from riscvcnnbench.config import (
    PROJECT_ROOT,
    ConfigError,
    CpuConfig,
    load_experiment,
    load_scenarios,
)

EXAMPLES = [
    "experiments/smoke_test.yaml",
    "experiments/hello_param_minimal.yaml",
    "experiments/hello_param_cache.yaml",
    "experiments/cnn_insn_semantics.yaml",
    "experiments/int8_base_example.yaml",
    "experiments/conv3x3_direct_s.yaml",
    "experiments/conv3x3_direct_l.yaml",
    "experiments/conv3x3_direct_s_custom.yaml",
    "experiments/conv3x3_direct_s_rvv.yaml",
    "experiments/conv3x3_im2col_s.yaml",
    "experiments/conv3x3_im2col_l.yaml",
    "experiments/depthwise3x3_s.yaml",
    "experiments/depthwise3x3_l.yaml",
    "experiments/pointwise1x1_s.yaml",
    "experiments/pointwise1x1_l.yaml",
    "experiments/maxpool2x2_s.yaml",
    "experiments/maxpool2x2_l.yaml",
    "experiments/requant_relu_s.yaml",
    "experiments/requant_relu_l.yaml",
    "experiments/fc_s.yaml",
    "experiments/fc_l.yaml",
    "experiments/fc_s_cenario.yaml",
    "experiments/insn_latency.yaml",
]


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "experiment.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("example", EXAMPLES)
def test_examples_are_valid(example: str) -> None:
    load_experiment(PROJECT_ROOT / example)


def test_minimal_uses_defaults(tmp_path: Path) -> None:
    config = load_experiment(write(tmp_path, "name: m\nbenchmark:\n  name: hello_riscv\n"))

    assert config.benchmark.variant == "ref"
    assert config.benchmark.cache_state == "warm"
    assert config.scenario is None
    assert config.compiler.flags == ["-O2"]
    assert config.cpu.model == "atomic"
    assert config.cpu.clock == "1GHz"
    assert config.cpu.vlen == 256
    assert config.cpu.custom_latency == 3
    assert config.cache.l1i is None and config.cache.l1d is None and config.cache.l2 is None
    assert config.memory.type == "simple"
    assert config.memory.size == "512MiB"
    assert config.results_dir == Path("results/m")
    assert config.gem5_args() == [
        "--cpu=atomic",
        "--clock=1GHz",
        "--vlen=256",
        "--custom-latency=3",
        "--mem-type=simple",
        "--mem-size=512MiB",
        "--roi-caches=warm",
    ]


def test_custom_units(tmp_path: Path) -> None:
    """RCB-33: os campos só aparecem quando mudam; 1 unidade é o padrão da minor."""
    text = VALID_START + "cpu:\n  model: o3-edge\n  custom_units: 2\n  custom_pipelined: false\n"
    config = load_experiment(write(tmp_path, text))

    cpu = config.model_dump(mode="json")["cpu"]
    assert (cpu["custom_units"], cpu["custom_pipelined"]) == (2, False)
    assert config.gem5_args()[3:6] == [
        "--custom-latency=3",
        "--custom-units=2",
        "--custom-unpipelined",
    ]
    minor = load_experiment(
        write(tmp_path, VALID_START + "cpu:\n  model: minor\n  custom_units: 1\n")
    )
    default = load_experiment(write(tmp_path, VALID_START + "cpu:\n  model: minor\n"))
    assert minor.model_dump(mode="json") == default.model_dump(mode="json")
    assert set(default.model_dump(mode="json")["cpu"]) == {
        "model",
        "clock",
        "vlen",
        "custom_latency",
    }
    assert not any(arg.startswith("--custom-u") for arg in default.gem5_args())


def test_cache_tuning(tmp_path: Path) -> None:
    """Ajustes das caches (RCB-32): só os diferentes do padrão chegam ao gem5 e à
    configuração resolvida, para a chave das execuções anteriores não mudar."""
    text = (
        VALID_START
        + "cpu:\n  model: minor\ncache:\n  line: 128\n"
        + "  l1i:\n    size: 32KiB\n    latency: 2\n    mshrs: 16\n    targets: 20\n"
        + "  l1d:\n    size: 32KiB\n    latency: 3\n    mshrs: 4\n    targets: 8\n"
        + "    prefetcher: stride\n"
        + "  l2:\n    size: 256KiB\n    assoc: 8\n    latency: 10\n    prefetcher: none\n"
    )
    config = load_experiment(write(tmp_path, text))

    assert config.model_dump(mode="json")["cache"] == {
        "line": 128,
        "l1i": {"size": "32KiB", "assoc": 4},
        "l1d": {
            "size": "32KiB",
            "assoc": 4,
            "latency": 3,
            "mshrs": 4,
            "targets": 8,
            "prefetcher": "stride",
        },
        "l2": {"size": "256KiB", "assoc": 8},
    }
    assert config.gem5_args()[4:13] == [
        "--cache-line=128",
        "--l1i-size=32KiB",
        "--l1i-assoc=4",
        "--l1d-size=32KiB",
        "--l1d-assoc=4",
        "--l1d-latency=3",
        "--l1d-mshrs=4",
        "--l1d-targets=8",
        "--l1d-prefetcher=stride",
    ]
    # Valores padrão escritos ou omitidos dão a mesma configuração resolvida.
    plain = load_experiment(
        write(
            tmp_path,
            VALID_START + "cache:\n  line: 64\n  l1d:\n    size: 32KiB\n    latency: 2\n",
        )
    )
    omitted = load_experiment(write(tmp_path, VALID_START + "cache:\n  l1d:\n    size: 32KiB\n"))
    assert plain.model_dump(mode="json") == omitted.model_dump(mode="json")
    assert omitted.model_dump(mode="json")["cache"] == {
        "l1i": None,
        "l1d": {"size": "32KiB", "assoc": 4},
        "l2": None,
    }
    tuning = ("--cache-line", "--l1d-latency", "--l1d-mshrs", "--l1d-targets", "--l1d-prefetcher")
    assert not any(arg.startswith(tuning) for arg in omitted.gem5_args())


def test_scenarios_have_no_tuning() -> None:
    """Os cenários dos resultados publicados continuam com a mesma configuração."""
    for scenario in load_scenarios().values():
        cache = scenario.cache.model_dump(mode="json")
        assert "line" not in cache
        for level in ("l1i", "l1d", "l2"):
            assert set(cache[level] or {}) <= {"size", "assoc"}


def test_cache_example_gem5_args() -> None:
    config = load_experiment(PROJECT_ROOT / "experiments/hello_param_cache.yaml")

    assert config.gem5_args() == [
        "--arg=65536",
        "--arg=2",
        "--cpu=timing",
        "--clock=2GHz",
        "--vlen=256",
        "--custom-latency=3",
        "--l1i-size=32KiB",
        "--l1i-assoc=4",
        "--l1d-size=32KiB",
        "--l1d-assoc=4",
        "--l2-size=256KiB",
        "--l2-assoc=8",
        "--mem-type=ddr4",
        "--mem-size=512MiB",
        "--roi-caches=warm",
    ]


def test_full_config_is_loaded(tmp_path: Path) -> None:
    config = load_experiment(
        write(
            tmp_path,
            """\
name: completo
description: todos os campos
benchmark:
  name: hello_riscv_param
  args: [4096, "2"]
  variant: ref
compiler:
  flags: ["-O3"]
cpu:
  model: o3
  clock: 2.5GHz
  vlen: 512
cache:
  l1i: {size: 16KiB}
  l1d: {size: 32KiB, assoc: 8}
  l2: {size: 1MiB, assoc: 16}
memory:
  type: ddr4
  size: 1GiB
output:
  dir: results/outro
""",
        )
    )

    assert config.name == "completo"
    assert config.description == "todos os campos"
    assert config.benchmark.args == ["4096", "2"]
    assert config.compiler.flags == ["-O3"]
    assert (config.cpu.model, config.cpu.clock, config.cpu.vlen) == ("o3", "2.5GHz", 512)
    assert config.cache.l1i is not None and config.cache.l1i.assoc == 4
    assert config.cache.l1d is not None and config.cache.l1d.assoc == 8
    assert config.cache.l2 is not None and config.cache.l2.size == "1MiB"
    assert (config.memory.type, config.memory.size) == ("ddr4", "1GiB")
    assert config.results_dir == Path("results/outro")


VALID_START = "name: x\nbenchmark:\n  name: hello_riscv\n"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "benchmark:\n  name: hello_riscv\n",
            "name: campo obrigatório ausente",
        ),
        (
            "name: x\n",
            "benchmark: campo obrigatório ausente",
        ),
        (
            "name: x\nbenchmark:\n  args: [1]\n",
            "linha 2: benchmark.name: campo obrigatório ausente",
        ),
        (
            "name: meu experimento\nbenchmark:\n  name: hello_riscv\n",
            "linha 1: name: valor 'meu experimento' inválido; use apenas letras, números, _ e -",
        ),
        (
            VALID_START + "cahce: {}\n",
            "linha 4: cahce: campo desconhecido; você quis dizer 'cache'?",
        ),
        (
            VALID_START + "cpu:\n  modle: o3\n",
            "linha 5: cpu.modle: campo desconhecido; você quis dizer 'model'?",
        ),
        (
            VALID_START + "xyz: 1\n",
            "linha 4: xyz: campo desconhecido; campos válidos aqui: benchmark, cache,",
        ),
        (
            VALID_START + "cpu:\n  model: pentium\n",
            "linha 5: cpu.model: valor 'pentium' inválido; use 'atomic', 'timing', 'minor', 'o3' "
            "ou 'o3-edge'",
        ),
        (
            VALID_START + "  variant: rvvv\n",
            "linha 4: benchmark.variant: valor 'rvvv' inválido; use 'ref', 'custom' ou 'rvv'",
        ),
        (
            VALID_START + "  variant: rvv\n",
            "linha 4: benchmark.variant: o benchmark 'hello_riscv' não tem a variante 'rvv'; "
            "disponíveis: ref",
        ),
        (
            VALID_START + "cpu:\n  vlen: 300\n",
            "linha 5: cpu.vlen: valor 300 inválido; use 128, 256, 512 ou 1024",
        ),
        (
            VALID_START + "cpu:\n  clock: 2\n",
            "linha 5: cpu.clock: deve ser texto, mas recebeu 2; use uma frequência como 800MHz",
        ),
        (
            VALID_START + "cpu:\n  clock: 2 GHz\n",
            "linha 5: cpu.clock: valor '2 GHz' inválido; use uma frequência como 800MHz",
        ),
        (
            VALID_START + "cache:\n  l1d:\n    size: 32KB\n",
            "linha 6: cache.l1d.size: valor '32KB' inválido; use um tamanho como 32KiB",
        ),
        (
            VALID_START + "cache:\n  l1d:\n    size: 32KiB\n    assoc: 0\n",
            "linha 7: cache.l1d.assoc: deve ser no mínimo 1, mas recebeu 0",
        ),
        (
            VALID_START + "cache:\n  l2:\n    size: 1MiB\n",
            "linha 4: cache: cache.l2 requer cache.l1i e cache.l1d",
        ),
        (
            VALID_START + "cache:\n  l1d:\n    size: 48KiB\n",
            "linha 4: cache: cache.l1d: 48KiB com associatividade 4 e linha de 64 bytes não dá um "
            "número de conjuntos potência de 2, como o gem5 exige (tamanho ÷ (linha × "
            "associatividade))",
        ),
        (
            VALID_START + "cache:\n  line: 128\n  l1d:\n    size: 1KiB\n    assoc: 16\n",
            "linha 4: cache: cache.l1d: 1KiB com associatividade 16 e linha de 128 bytes não dá "
            "um número de conjuntos potência de 2, como o gem5 exige (tamanho ÷ (linha × "
            "associatividade))",
        ),
        (
            VALID_START + "cache:\n  line: 96\n",
            "linha 5: cache.line: valor 96 inválido; use 32, 64 ou 128",
        ),
        (
            VALID_START + "cache:\n  l1d:\n    size: 32KiB\n    latency: 0\n",
            "linha 7: cache.l1d.latency: deve ser no mínimo 1, mas recebeu 0",
        ),
        (
            VALID_START + "cache:\n  l1d:\n    size: 32KiB\n    mshrs: 2000\n",
            "linha 7: cache.l1d.mshrs: deve ser no máximo 1024, mas recebeu 2000",
        ),
        (
            VALID_START + "cache:\n  l1d:\n    size: 32KiB\n    prefetcher: next\n",
            "linha 7: cache.l1d.prefetcher: valor 'next' inválido; use 'none', 'stride' ou "
            "'tagged'",
        ),
        (
            VALID_START + "cache:\n  l1d:\n    size: 32KiB\n    prefetch: stride\n",
            "linha 7: cache.l1d.prefetch: campo desconhecido; você quis dizer 'prefetcher'?",
        ),
        (
            VALID_START + "cpu:\n  custom_latency: 6\n",
            "linha 4: cpu: cpu.custom_latency só tem efeito nas CPUs minor, o3 e o3-edge; a "
            "atomic não modela a latência das unidades funcionais (use 3, o padrão)",
        ),
        (
            VALID_START + "cpu:\n  model: timing\n  custom_units: 2\n",
            "linha 4: cpu: cpu.custom_units só tem efeito nas CPUs minor, o3 e o3-edge; a "
            "timing não modela as unidades funcionais (tire o campo)",
        ),
        (
            VALID_START + "cpu:\n  custom_pipelined: false\n",
            "linha 4: cpu: cpu.custom_pipelined só tem efeito nas CPUs minor, o3 e o3-edge; a "
            "atomic não modela as unidades funcionais (use true, o padrão)",
        ),
        (
            VALID_START + "cpu:\n  model: o3\n  custom_units: 9\n",
            "linha 6: cpu.custom_units: deve ser no máximo 8, mas recebeu 9",
        ),
        (
            VALID_START + "cpu:\n  model: minor\n  custom_latency: 0\n",
            "linha 6: cpu.custom_latency: deve ser no mínimo 1, mas recebeu 0",
        ),
        (
            VALID_START + "cpu:\n  model: o3\n  custom_latency: 100\n",
            "linha 6: cpu.custom_latency: deve ser no máximo 64, mas recebeu 100",
        ),
        (
            VALID_START + "  cache_state: frio\n",
            "linha 4: benchmark.cache_state: valor 'frio' inválido; use 'warm' ou 'cold'",
        ),
        (
            VALID_START + "scenario: l1l2\n",
            "linha 4: scenario: cenário 'l1l2' não existe em configs/scenarios.yaml; você quis "
            "dizer 'l1-l2'?",
        ),
        (
            VALID_START + "scenario: grande\n",
            "linha 4: scenario: cenário 'grande' não existe em configs/scenarios.yaml; "
            "disponíveis: sem-cache, l1, l1-l2, reduzido",
        ),
        (
            VALID_START + "scenario: l1\nmemory:\n  type: simple\n",
            "linha 5: memory: não use junto com scenario (l1), que já define cache e memory; "
            "tire um dos dois",
        ),
        (
            VALID_START + "cpu: o3\n",
            "linha 4: cpu: deve conter subcampos (um mapeamento YAML), mas recebeu 'o3'",
        ),
        (
            "name: x\nbenchmark:\n  name: hello_riscv\n  args: 4096\n",
            "linha 4: benchmark.args: deve ser uma lista",
        ),
        (
            "name: x\nbenchmark:\n  name: nao_existe\n",
            "linha 3: benchmark.name: benchmark 'nao_existe' não encontrado em benchmarks/; "
            "disponíveis: cnn_insn_semantics, conv3x3_direct, conv3x3_im2col, depthwise3x3, fc, "
            "hello_riscv, hello_riscv_param, insn_latency, int8_base_example, maxpool2x2, "
            "pointwise1x1, requant_relu",
        ),
        (
            VALID_START + "cpu:\n  model: o3\ncpu:\n  model: timing\n",
            "linha 6: cpu: campo repetido; só o último valor seria usado",
        ),
        ("", "arquivo vazio"),
        ("- name: x\n", "deve ser um mapeamento de campos"),
        (
            VALID_START + "cpu:\n  model: o3\n   clock: 1GHz\n",
            "linha 6, coluna 9: YAML inválido",
        ),
    ],
)
def test_invalid_config_message(tmp_path: Path, text: str, expected: str) -> None:
    with pytest.raises(ConfigError) as error:
        load_experiment(write(tmp_path, text))

    assert expected in str(error.value)


def test_all_problems_reported_in_line_order(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "name: a b\nbenchmark:\n  name: hello_riscv\ncpu:\n  model: x\nmemory:\n  size: 1\n",
    )

    with pytest.raises(ConfigError) as error:
        load_experiment(path)

    problems = error.value.problems
    assert [problem.split(":")[0] for problem in problems] == ["linha 1", "linha 5", "linha 7"]
    assert str(error.value).startswith(f"{path} tem 3 problemas:")


def test_cold_caches_need_caches_and_roi(tmp_path: Path) -> None:
    path = write(tmp_path, VALID_START + "  cache_state: cold\n")

    with pytest.raises(ConfigError) as error:
        load_experiment(path)

    assert error.value.problems == [
        "linha 4: benchmark.cache_state: 'cold' esvazia as caches no início da ROI, mas o "
        "experimento não tem caches; configure cache ou use um scenario com caches",
        "linha 4: benchmark.cache_state: 'cold' exige um benchmark que marque a região de "
        "interesse (rcb_roi_begin); 'hello_riscv' não marca",
    ]


def test_scenario_fills_cache_and_memory(tmp_path: Path) -> None:
    config = load_experiment(
        write(
            tmp_path,
            "name: c\nscenario: reduzido\nbenchmark:\n  name: fc\n  variant: custom\n"
            "  cache_state: cold\ncpu:\n  model: o3-edge\n  custom_latency: 6\n",
        )
    )

    assert config.scenario == "reduzido"
    assert config.cache.l1d is not None and config.cache.l1d.size == "4KiB"
    assert config.cache.l2 is not None and config.cache.l2.size == "32KiB"
    assert config.memory.type == "ddr4"
    assert config.gem5_args() == [
        "--cpu=o3-edge",
        "--clock=1GHz",
        "--vlen=256",
        "--custom-latency=6",
        "--l1i-size=32KiB",
        "--l1i-assoc=4",
        "--l1d-size=4KiB",
        "--l1d-assoc=4",
        "--l2-size=32KiB",
        "--l2-assoc=8",
        "--mem-type=ddr4",
        "--mem-size=512MiB",
        "--roi-caches=cold",
    ]


def test_scenarios_file() -> None:
    scenarios = load_scenarios()

    # Os quatro cenários de docs/scenarios.md, todos com DDR4 e a mesma L1i.
    assert list(scenarios) == ["sem-cache", "l1", "l1-l2", "reduzido"]
    assert all(s.memory.type == "ddr4" and s.memory.size == "512MiB" for s in scenarios.values())
    assert scenarios["sem-cache"].cache.l1i is None and scenarios["sem-cache"].cache.l1d is None
    for name in ("l1", "l1-l2", "reduzido"):
        cache = scenarios[name].cache
        assert cache.l1i is not None and (cache.l1i.size, cache.l1i.assoc) == ("32KiB", 4)
    sizes = {
        name: (s.cache.l1d.size if s.cache.l1d else None, s.cache.l2.size if s.cache.l2 else None)
        for name, s in scenarios.items()
    }
    assert sizes == {
        "sem-cache": (None, None),
        "l1": ("32KiB", None),
        "l1-l2": ("32KiB", "256KiB"),
        "reduzido": ("4KiB", "32KiB"),
    }


def test_default_latency_is_allowed_on_every_cpu() -> None:
    for model in ("atomic", "timing", "minor", "o3", "o3-edge"):
        assert CpuConfig(model=model).custom_latency == 3


def test_missing_file() -> None:
    with pytest.raises(ConfigError, match="arquivo não encontrado"):
        load_experiment(Path("nao_existe.yaml"))


def test_cli_validate() -> None:
    runner = CliRunner()

    ok = runner.invoke(app, ["validate", str(PROJECT_ROOT / "experiments/hello_param_cache.yaml")])
    assert ok.exit_code == 0
    assert "Configuração válida" in ok.stdout
    assert "l2=256KiB/8-way" in ok.stdout

    missing = runner.invoke(app, ["validate", "nao_existe.yaml"])
    assert missing.exit_code == 1
    assert "arquivo não encontrado" in missing.stderr


def test_cli_run_rejects_invalid_config(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["run", str(write(tmp_path, "name: x\n"))])

    assert result.exit_code == 1
    assert "benchmark: campo obrigatório ausente" in result.stderr
