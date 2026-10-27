"""Gerador de experimentos (RCB-31): o JavaScript da página roda no QuickJS, e o YAML
que ele gera passa pelo validador do framework (experimento ou plano da campanha)."""

import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest
import quickjs
import yaml
from typer.testing import CliRunner

from riscvcnnbench.campaign import build_plan, load_campaign
from riscvcnnbench.cli import app
from riscvcnnbench.config import PROJECT_ROOT, CpuConfig, load_experiment
from riscvcnnbench.estimate import binary_key, speed_key
from riscvcnnbench.generator import (
    GeneratorError,
    _binary,
    estimate_data,
    page_data,
    script,
    write_page,
)
from riscvcnnbench.runner import resolved_config
from test_estimate import measured

DATA = page_data()
OPS = [op["id"] for op in DATA["ops"]]


@pytest.fixture(scope="module")
def js() -> quickjs.Context:
    context = quickjs.Context()
    context.eval(script())
    return context


def call(context: quickjs.Context, function: str, *args: Any) -> Any:
    payload = ", ".join(json.dumps(arg, ensure_ascii=False) for arg in args)
    return json.loads(context.eval(f"JSON.stringify(RCB.{function}({payload}))"))


def state(**changes: Any) -> dict[str, Any]:
    base = {
        "name": "teste",
        "description": "",
        "ops": ["fc"],
        "sizes": ["S"],
        "variants": ["ref"],
        "cpus": ["minor"],
        "scenarios": ["l1-l2"],
        "custom": None,
        "latencies": [3],
        "vlens": [256],
        "flags": ["-O2"],
        "datasets": ["random"],
        "cacheStates": ["warm"],
        "clock": "1GHz",
    }
    return base | changes


def custom(**levels: Any) -> dict[str, Any]:
    """Memória personalizada: cada nível como (tamanhos, associatividade) ou None."""
    memory = {"memoryType": levels.pop("memory_type", "ddr4"), "memorySize": "512MiB"}
    memory["memorySize"] = levels.pop("memory_size", "512MiB")
    for level in ("l1i", "l1d", "l2"):
        value = levels.get(level)
        memory[level] = {"sizes": value[0], "assoc": value[1]} if value else None
    return memory


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_page_data_comes_from_the_code() -> None:
    assert OPS == [
        "conv3x3_direct",
        "conv3x3_im2col",
        "depthwise3x3",
        "pointwise1x1",
        "maxpool2x2",
        "requant_relu",
        "fc",
    ]
    fc = DATA["ops"][-1]
    assert fc["variants"] == ["ref", "custom", "rvv"]
    assert fc["sizes"]["S"] == {
        "experiment": "fc_s",
        "args": [512, 32, 1],
        "names": ["In", "Out", "R"],
        "bytes": 17056,
    }
    assert {cpu["id"] for cpu in DATA["cpus"]} == set(
        get_args(CpuConfig.model_fields["model"].annotation)
    )
    assert [cpu["id"] for cpu in DATA["cpus"] if cpu["latency"]] == ["minor", "o3-edge", "o3"]
    assert [s["id"] for s in DATA["scenarios"]] == ["", "sem-cache", "l1", "l1-l2", "reduzido"]
    assert DATA["scenarios"][3]["l1d"] == 32 * 1024
    assert DATA["scenarios"][3]["l2"] == 256 * 1024
    assert DATA["noScenarioLabel"] == "sem-cache,simple"
    assert (DATA["latency"]["min"], DATA["latency"]["max"], DATA["latency"]["default"]) == (
        1,
        64,
        3,
    )
    assert DATA["vlen"] == {"default": 256, "options": [128, 256, 512, 1024]}
    assert DATA["estimate"] is None
    assert [(d["id"], d["flag"]) for d in DATA["datasets"]] == [
        ("random", None),
        ("satpos", "-DRCB_DATA=1"),
        ("satneg", "-DRCB_DATA=2"),
    ]
    assert DATA["memory"]["default"] == {"type": "simple", "size": "512MiB"}
    assert DATA["memory"]["custom"]["l2"] == {"size": "256KiB", "assoc": 8}


def test_footprint_and_residence_match_the_scenarios_doc(js: quickjs.Context) -> None:
    """A tabela "O que cabe em cada nível" de docs/scenarios.md, medida no gem5."""
    text = (PROJECT_ROOT / "docs/scenarios.md").read_text(encoding="utf-8")
    row = re.compile(
        r"^\| (?:`(\w+)`)? *\| ([SL]) \| ([\d,]+) KiB \| [\d.]+ \| (.+?) \| (.+?) \| (.+?) \| (.+?) \|$",
        re.M,
    )
    checked = 0
    op = None
    for match in row.finditer(text):
        op = match.group(1) or op
        size, kib = match.group(2), float(match.group(3).replace(",", "."))
        fits = [cell.startswith("cabe") for cell in match.groups()[3:]]
        info = next(item for item in DATA["ops"] if item["id"] == op)
        # A tabela arredonda para 0,1 KiB (132,25 aparece como 132,3).
        assert abs(info["sizes"][size]["bytes"] / 1024 - kib) <= 0.05 + 1e-9, (op, size)
        expected = {
            "l1": "L1d" if fits[0] else "DRAM",
            "l1-l2": "L1d" if fits[0] else "L2" if fits[1] else "DRAM",
            "reduzido": "L1d" if fits[2] else "L2" if fits[3] else "DRAM",
            "sem-cache": "DRAM",
            "": "memória",
        }
        for scenario, where in expected.items():
            assert call(js, "residence", op, size, scenario, DATA) == where, (op, size, scenario)
        checked += 1
    assert checked == 14


SINGLE = [
    # variante, CPU, cenário, latência, VLEN, flags, caches
    ("custom", "minor", "l1-l2", 6, 256, "-O3", "warm"),
    ("rvv", "o3-edge", "reduzido", 3, 512, "-O2", "cold"),
    ("ref", "atomic", "", 3, 256, "-O2", "warm"),
    ("custom", "timing", "sem-cache", 6, 256, "-O2", "warm"),
]


@pytest.mark.parametrize("choice", SINGLE)
def test_one_choice_is_a_valid_experiment(
    js: quickjs.Context, tmp_path: Path, choice: tuple
) -> None:
    variant, cpu, scenario, latency, vlen, flags, cache_state = choice
    for op in OPS:
        for size in ("S", "L"):
            selected = state(
                name=f"{op}_{size}",
                ops=[op],
                sizes=[size],
                variants=[variant],
                cpus=[cpu],
                scenarios=[scenario],
                latencies=[latency],
                vlens=[vlen],
                flags=[flags],
                cacheStates=[cache_state],
            )
            result = call(js, "build", selected, DATA)
            assert (result["kind"], result["problems"]) == ("experiment", [])
            [combo] = result["combinations"]
            path = write(tmp_path / f"{op}_{size}.yaml", result["yaml"])

            experiment = load_experiment(path)

            sizes = next(item for item in DATA["ops"] if item["id"] == op)["sizes"]
            assert experiment.benchmark.name == op
            assert [int(arg) for arg in experiment.benchmark.args] == sizes[size]["args"]
            assert experiment.benchmark.variant == variant
            assert experiment.benchmark.cache_state == cache_state
            assert experiment.cpu.model == cpu
            assert experiment.scenario == (scenario or None)
            assert experiment.compiler.flags == [flags]
            # A latência só vale na custom com unidades funcionais; a VLEN, na rvv.
            assert experiment.cpu.custom_latency == (latency if cpu == "minor" else 3)
            assert experiment.cpu.vlen == (vlen if variant == "rvv" else 256)
            resolved = resolved_config(experiment)
            assert call(js, "binaryKey", combo, DATA) == _binary(binary_key(resolved))
            assert call(js, "speedKey", combo, DATA) == "|".join(speed_key(resolved))


CAMPAIGNS = [
    # O grupo principal da matriz final: 504 combinações.
    state(
        ops=OPS,
        sizes=["S", "L"],
        variants=["ref", "custom", "rvv"],
        cpus=["timing", "minor", "o3-edge"],
        scenarios=["sem-cache", "l1", "l1-l2", "reduzido"],
    ),
    # Tudo o que se normaliza: latência, VLEN, flags, caches frias, clock.
    state(
        ops=["conv3x3_direct", "fc"],
        sizes=["S", "L"],
        variants=["ref", "custom", "rvv"],
        cpus=["atomic", "timing", "minor", "o3-edge"],
        scenarios=["l1", "reduzido"],
        latencies=[3, 6, 9],
        vlens=[128, 512],
        flags=["-O2", "-O3"],
        cacheStates=["warm", "cold"],
        clock="2GHz",
        description='Teste: "aspas", dois-pontos e acentuação',
    ),
    state(variants=["ref", "custom", "rvv"], cpus=["atomic"], scenarios=[""]),
    state(sizes=["S", "L"], cpus=["minor", "o3"], latencies=[6]),
    # Cenário nomeado e varredura de caches personalizadas: dois grupos.
    state(
        ops=["fc", "maxpool2x2"],
        sizes=["S", "L"],
        variants=["ref", "custom"],
        datasets=["random", "satpos"],
        custom=custom(
            l1i=(["32KiB"], 4), l1d=(["8KiB", "16KiB", "32KiB"], 4), l2=(["128KiB", "256KiB"], 8)
        ),
    ),
    # Só memória personalizada, sem caches, com caches frias de fora.
    state(
        variants=["ref", "rvv"],
        cpus=["timing", "o3-edge"],
        scenarios=[],
        custom=custom(memory_type="ddr4", memory_size="1GiB"),
        datasets=["random", "satneg"],
    ),
]


@pytest.mark.parametrize("selected", CAMPAIGNS)
def test_many_choices_are_a_valid_campaign(
    js: quickjs.Context, tmp_path: Path, selected: dict
) -> None:
    result = call(js, "build", selected, DATA)
    assert (result["kind"], result["problems"]) == ("campaign", [])
    path = write(tmp_path / "matriz.yaml", result["yaml"])
    campaign = load_campaign(path)

    plan = build_plan(campaign, tmp_path / "campanha", path)

    assert plan.invalid == []
    assert len(plan.runs) == len(result["combinations"])

    def memory_of(scenario: str, cache: dict | None, memory: tuple) -> tuple:
        if scenario:
            return (scenario, None, None)
        levels = tuple(
            sorted((level, v["size"], v.get("assoc", 4)) for level, v in (cache or {}).items() if v)
        )
        return ("", levels, memory)

    def key(base: str, data: dict) -> tuple:
        cpu = data.get("cpu") or {}
        benchmark = data["benchmark"]
        memory = data.get("memory") or {}
        return (
            base,
            benchmark.get("variant", "ref"),
            cpu.get("model", "atomic"),
            memory_of(
                data.get("scenario") or "",
                data.get("cache"),
                (memory.get("type", "simple"), memory.get("size", "512MiB")),
            ),
            cpu.get("custom_latency", 3),
            cpu.get("vlen", 256),
            tuple((data.get("compiler") or {}).get("flags", ["-O2"])),
            benchmark.get("cache_state", "warm"),
            cpu.get("clock", "1GHz"),
        )

    planned = {key(run.base, run.data) for run in plan.runs}
    generated = {
        (
            f"{c['op']}_{c['size'].lower()}",
            c["variant"],
            c["cpu"],
            memory_of(c["scenario"], c["cache"], (c["memoryType"], c["memorySize"])),
            c["latency"],
            c["vlen"],
            tuple(c["flags"]),
            c["cacheState"],
            c["clock"],
        )
        for c in result["combinations"]
    }
    assert len(planned) == len(plan.runs)
    sizes_seen = {run.base for run in plan.runs}
    assert sizes_seen == {
        f"{op}_{size.lower()}" for op in selected["ops"] for size in selected["sizes"]
    }
    assert planned == generated
    if selected["description"]:
        assert (
            yaml.safe_load(path.read_text(encoding="utf-8"))["description"]
            == (selected["description"])
        )


def test_custom_memory_experiment(js: quickjs.Context, tmp_path: Path) -> None:
    selected = state(
        scenarios=[],
        custom=custom(
            l1i=(["16KiB"], 2), l1d=(["8KiB"], 4), memory_type="simple", memory_size="1GiB"
        ),
        datasets=["satpos"],
        cacheStates=["cold"],
    )
    result = call(js, "build", selected, DATA)
    assert (result["kind"], result["problems"]) == ("experiment", [])
    [combo] = result["combinations"]
    path = write(tmp_path / "custom.yaml", result["yaml"])

    experiment = load_experiment(path)

    assert experiment.scenario is None
    assert (experiment.cache.l1i.size, experiment.cache.l1i.assoc) == ("16KiB", 2)
    assert (experiment.cache.l1d.size, experiment.cache.l1d.assoc) == ("8KiB", 4)
    assert experiment.cache.l2 is None
    assert (experiment.memory.type, experiment.memory.size) == ("simple", "1GiB")
    assert experiment.compiler.flags == ["-O2", "-DRCB_DATA=1"]
    assert experiment.benchmark.cache_state == "cold"
    resolved = resolved_config(experiment)
    assert call(js, "speedKey", combo, DATA) == "|".join(speed_key(resolved))
    assert call(js, "binaryKey", combo, DATA) == _binary(binary_key(resolved))
    # FC S (16,7 KiB) não cabe na L1d de 8 KiB e, sem L2, vem da memória.
    assert call(js, "residence", "fc", "S", combo, DATA) == "memória"
    larger = combo | {"cache": {"l1d": {"size": "8KiB"}, "l2": {"size": "32KiB"}}}
    assert call(js, "residence", "fc", "S", larger, DATA) == "L2"


def test_final_matrix_size(js: quickjs.Context) -> None:
    result = call(js, "build", CAMPAIGNS[0], DATA)
    assert len(result["combinations"]) == 504
    document = yaml.safe_load(result["yaml"])
    assert document["groups"][0]["vary"] == {
        "benchmark.variant": ["ref", "custom", "rvv"],
        "cpu.model": ["timing", "minor", "o3-edge"],
        "scenario": ["sem-cache", "l1", "l1-l2", "reduzido"],
    }
    assert "set" not in document["groups"][0]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"name": "meu teste"},
            "Nome: use apenas letras, números, _ e - (por exemplo, meu_teste).",
        ),
        ({"variants": []}, "Escolha pelo menos uma implementação."),
        ({"scenarios": ["", "l1"]}, '"Sem cenário" só pode ser escolhido sozinho.'),
        (
            {"scenarios": ["sem-cache", "l1"], "cacheStates": ["cold"]},
            "Caches frias exigem caches: tire sem-cache ou use só caches aquecidas.",
        ),
        (
            {"variants": ["custom"], "latencies": [0]},
            "Latência: use um inteiro de 1 a 64.",
        ),
        (
            {"variants": ["custom"], "latencies": []},
            "Escolha pelo menos uma latência para as instruções personalizadas.",
        ),
        ({"variants": ["rvv"], "vlens": []}, "Escolha pelo menos uma VLEN."),
        ({"clock": "1 GHz"}, "Clock: use uma frequência como 800MHz ou 2GHz."),
        ({"datasets": []}, "Escolha pelo menos um conjunto de dados."),
        ({"scenarios": []}, "Escolha pelo menos uma configuração de memória."),
        ({"scenarios": [""], "custom": custom()}, '"Sem cenário" só pode ser escolhido sozinho.'),
        ({"custom": custom(l2=(["256KiB"], 8))}, "A L2 exige a L1i e a L1d."),
        (
            {"custom": custom(l1d=(["48KiB"], 4))},
            "L1d: 48KiB com associatividade 4 não dá um número de conjuntos potência de 2 "
            "(tamanho ÷ (64 × associatividade)).",
        ),
        (
            {"custom": custom(l1d=(["32 KB"], 4))},
            'L1d: "32 KB": use um tamanho como 32KiB, 512MiB ou 1GiB.',
        ),
        (
            {"custom": custom(memory_size="lots")},
            "Tamanho da memória: use um tamanho como 32KiB, 512MiB ou 1GiB.",
        ),
        (
            {"scenarios": [], "custom": custom(), "cacheStates": ["cold"]},
            'Caches frias exigem caches: tire "sem caches,ddr4" ou use só caches aquecidas.',
        ),
    ],
)
def test_problems(js: quickjs.Context, changes: dict, message: str) -> None:
    result = call(js, "build", state(**changes), DATA)

    assert message in result["problems"]
    assert (result["yaml"], result["combinations"]) == ("", [])


def test_latency_without_custom_is_not_a_problem(js: quickjs.Context) -> None:
    result = call(js, "build", state(variants=["ref"], latencies=[]), DATA)
    assert result["problems"] == []


def test_estimate_from_measured_runs(js: quickjs.Context, tmp_path: Path) -> None:
    selected = state(variants=["ref", "custom", "rvv"])
    result = call(js, "build", selected, DATA)
    root = tmp_path / "medidas"
    # ref e custom medidas na minor, l1-l2: 8000 instruções em 10 s e 1000 em 3 s.
    for number, (variant, insts, seconds) in enumerate(
        [("ref", 8000, 10.0), ("custom", 1000, 3.0)]
    ):
        single = call(js, "build", state(variants=[variant]), DATA)
        path = write(tmp_path / f"{variant}.yaml", single["yaml"])
        resolved = resolved_config(load_experiment(path))
        measured(root, number, resolved, (insts // 2, insts - insts // 2), seconds)
    data = DATA | {"estimate": estimate_data([root])}

    time = call(js, "estimate", result["combinations"], data, 1)

    assert (time["known"], time["total"]) == (2, 3)  # a rvv não foi medida
    assert time["serial"] == pytest.approx(13)
    assert time["makespan"] == pytest.approx(13)
    assert call(js, "estimate", result["combinations"], data, 2)["makespan"] == pytest.approx(10)
    assert call(js, "estimate", result["combinations"], DATA, 4) is None


def test_write_page(tmp_path: Path) -> None:
    output = tmp_path / "gerador.html"

    data = write_page(output)

    html = output.read_text(encoding="utf-8")
    embedded = re.search(
        r'<script id="rcb-data" type="application/json">(.*?)</script>', html, re.S
    )
    assert embedded and json.loads(embedded.group(1).replace("<\\/", "</")) == data
    assert script() in html
    assert "__RCB_" not in html
    with pytest.raises(GeneratorError, match="já existe .*--force"):
        write_page(output)
    write_page(output, force=True)
    with pytest.raises(GeneratorError, match="pasta não encontrada"):
        write_page(tmp_path / "outra.html", measured=[tmp_path / "nada"])


def test_cli_gerador(tmp_path: Path) -> None:
    runner = CliRunner()
    output = tmp_path / "pagina.html"

    result = runner.invoke(app, ["gerador", "-o", str(output)])

    assert result.exit_code == 0, result.output
    assert "7 operação(ões), 4 cenário(s)" in result.output
    assert output.is_file()
    again = runner.invoke(app, ["gerador", "-o", str(output)])
    assert again.exit_code == 1 and "use --force" in again.stderr
