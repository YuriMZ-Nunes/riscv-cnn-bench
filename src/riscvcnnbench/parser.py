"""Leitura do stats.txt do gem5: blocos, região de interesse e métricas.

O gem5 grava um bloco de estatísticas a cada dump. Os benchmarks com a base comum
(RCB-11) geram dois, a região de interesse (ROI) e o resto do programa; os demais,
um só, com o programa inteiro. Os nomes das estatísticas usadas pelo framework
ficam só em METRICS. Veja docs/results.md, seção "Métricas".
"""

import configparser
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MARKER = re.compile(r"^-+ (Begin|End) Simulation Statistics\s+-+$")
# Trecho do tipo da CPU no config.ini (BaseAtomicSimpleCPU, BaseO3CPU...) -> modelo do YAML.
CPU_TYPES = (("Atomic", "atomic"), ("Timing", "timing"), ("Minor", "minor"), ("O3", "o3"))

Value = int | float | None
Region = Literal["roi", "program"]


class StatsError(Exception):
    """stats.txt com estrutura ou conteúdo inesperado."""


@dataclass(frozen=True)
class Metric:
    """Métrica do framework e a estatística do gem5 de onde ela vem.

    O gem5 não imprime as estatísticas de cache e de memória que valem zero ou NaN
    (flags `nozero` e `nonan`), então a falta da linha não quer dizer falta do dado.
    `component` é o prefixo do objeto do gem5: sem nenhuma linha dele no bloco, o
    objeto não existe na configuração e a métrica fica ausente; com ele, a linha que
    falta vale conforme `omitted`:

    - `zero`: contador, vale 0;
    - `ratio`: razão, vale 0 se `denominator` > 0 e é indefinida (0/0) se não;
    - `undefined`: média sobre eventos (latência) sem nenhum evento, indefinida.

    Sem `component`, a estatística é da CPU ou da simulação e precisa existir.
    `timed` marca o que depende do tempo simulado: ausente na CPU atomic, que não
    modela tempo (o gem5 imprime `numCycles` nela, mas é só tick / período).
    """

    key: str
    stat: str
    group: str
    unit: str
    description: str
    component: str | None = None
    omitted: Literal["zero", "ratio", "undefined"] = "zero"
    denominator: str | None = None
    timed: bool = False


@dataclass(frozen=True)
class RegionStats:
    """Métricas do bloco escolhido e o motivo de cada uma que ficou ausente (None).

    `region` é `roi` (bloco 1 de 2) ou `program` (bloco único, benchmark sem ROI).
    """

    region: Region
    blocks: int
    cpu: str | None
    metrics: dict[str, Value]
    missing: dict[str, str]


ICACHE = "system.cpu.icache."
DCACHE = "system.cpu.dcache."
L2CACHE = "system.l2cache."
DRAM = "system.mem_ctrl."
SIMPLE_MEMORY = "system.memory."
BRANCH_PREDICTOR = "system.cpu.branchPred."


def _cache(key: str, component: str, name: str) -> tuple[Metric, ...]:
    return (
        Metric(
            f"{key}_accesses",
            f"{component}overallAccesses::total",
            "Caches",
            "acessos",
            f"Acessos à {name}",
            component,
        ),
        Metric(
            f"{key}_misses",
            f"{component}overallMisses::total",
            "Caches",
            "faltas",
            f"Faltas na {name}",
            component,
        ),
        Metric(
            f"{key}_miss_rate",
            f"{component}overallMissRate::total",
            "Caches",
            "razão",
            f"Taxa de faltas na {name}",
            component,
            "ratio",
            f"{key}_accesses",
        ),
        Metric(
            f"{key}_avg_miss_latency",
            f"{component}demandAvgMissLatency::total",
            "Caches",
            "ticks",
            f"Latência média de uma falta na {name}",
            component,
            "undefined",
            timed=True,
        ),
    )


METRICS: tuple[Metric, ...] = (
    Metric("insts", "system.cpu.commitStats0.numInsts", "Centrais", "instruções", "Instruções"),
    Metric(
        "ops",
        "system.cpu.commitStats0.numOps",
        "Centrais",
        "micro-ops",
        "Micro-operações (maior que insts quando uma instrução vira várias, como na RVV)",
    ),
    Metric("cycles", "system.cpu.numCycles", "Centrais", "ciclos", "Ciclos da CPU", timed=True),
    Metric("ipc", "system.cpu.ipc", "Centrais", "inst/ciclo", "Instruções por ciclo", timed=True),
    Metric(
        "sim_ticks",
        "simTicks",
        "Centrais",
        "ticks",
        "Tempo simulado (10^12 ticks por segundo; tick não é ciclo)",
        timed=True,
    ),
    Metric(
        "loads",
        "system.cpu.commitStats0.numLoadInsts",
        "Mistura de instruções",
        "instruções",
        "Loads",
    ),
    Metric(
        "stores",
        "system.cpu.commitStats0.numStoreInsts",
        "Mistura de instruções",
        "instruções",
        "Stores",
    ),
    Metric(
        "mem_refs",
        "system.cpu.commitStats0.numMemRefs",
        "Mistura de instruções",
        "instruções",
        "Referências à memória (loads + stores)",
    ),
    Metric(
        "branch_mispredicts",
        "system.cpu.branchPred.condIncorrect",
        "Desvios",
        "desvios",
        "Desvios condicionais mal previstos (só minor e o3 têm preditor)",
        BRANCH_PREDICTOR,
    ),
    *_cache("l1i", ICACHE, "L1 de instruções"),
    *_cache("l1d", DCACHE, "L1 de dados"),
    *_cache("l2", L2CACHE, "L2"),
    Metric(
        "dram_reads",
        "system.mem_ctrl.readReqs",
        "Memória",
        "requisições",
        "Leituras aceitas pela DDR4",
        DRAM,
    ),
    Metric(
        "dram_writes",
        "system.mem_ctrl.writeReqs",
        "Memória",
        "requisições",
        "Escritas aceitas pela DDR4",
        DRAM,
    ),
    Metric(
        "dram_bandwidth",
        "system.mem_ctrl.dram.bwTotal::total",
        "Memória",
        "bytes/s",
        "Banda total da DDR4",
        DRAM,
        timed=True,
    ),
    Metric(
        "dram_avg_latency",
        "system.mem_ctrl.dram.avgMemAccLat",
        "Memória",
        "ticks",
        "Latência média de acesso à DDR4",
        DRAM,
        "undefined",
        timed=True,
    ),
    Metric(
        "simple_bytes_read",
        "system.memory.bytesRead::total",
        "Memória",
        "bytes",
        "Bytes lidos da memória simple",
        SIMPLE_MEMORY,
    ),
    Metric(
        "simple_bytes_written",
        "system.memory.bytesWritten::total",
        "Memória",
        "bytes",
        "Bytes escritos na memória simple",
        SIMPLE_MEMORY,
    ),
    Metric(
        "simple_reads",
        "system.memory.numReads::total",
        "Memória",
        "requisições",
        "Leituras da memória simple",
        SIMPLE_MEMORY,
    ),
    Metric(
        "simple_writes",
        "system.memory.numWrites::total",
        "Memória",
        "requisições",
        "Escritas na memória simple",
        SIMPLE_MEMORY,
    ),
    Metric(
        "host_seconds",
        "hostSeconds",
        "Host",
        "s",
        "Tempo real de simulação no host (varia entre execuções)",
    ),
)


def split_blocks(text: str) -> list[dict[str, str]]:
    """Blocos do stats.txt, na ordem, como {estatística: primeiro valor da linha}."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = MARKER.match(line.strip())
        if marker and marker.group(1) == "Begin":
            if current is not None:
                raise StatsError(
                    f"linha {number}: o bloco {len(blocks) + 1} não terminou antes do seguinte"
                )
            current = {}
        elif marker:
            if current is None:
                raise StatsError(f"linha {number}: fim de bloco sem início")
            blocks.append(current)
            current = None
        elif current is not None:
            fields = line.split(maxsplit=2)
            if len(fields) >= 2:
                current[fields[0]] = fields[1]
    if current is not None:
        raise StatsError(
            f"o bloco {len(blocks) + 1} está incompleto: o arquivo termina antes do fim do "
            "bloco (a simulação foi interrompida?)"
        )
    return blocks


def stats_differences(first: str, second: str) -> tuple[int, list[str]]:
    """Compara dois stats.txt sem as estatísticas do host (hostSeconds, hostMemory e as
    taxas por segundo real), que mudam a cada execução. Numa simulação determinística,
    com as mesmas entradas, o resto se repete: devolve quantas estatísticas foram
    comparadas e as diferenças (RCB-23)."""
    blocks = [
        [{k: v for k, v in block.items() if not k.startswith("host")} for block in split_blocks(t)]
        for t in (first, second)
    ]
    if len(blocks[0]) != len(blocks[1]):
        return 0, [f"{_blocks(len(blocks[0]))} × {_blocks(len(blocks[1]))}"]
    compared, differences = 0, []
    for number, (a, b) in enumerate(zip(*blocks, strict=True), 1):
        for name in sorted(a.keys() | b.keys()):
            compared += 1
            if a.get(name) != b.get(name):
                values = f"{a.get(name, '(ausente)')} × {b.get(name, '(ausente)')}"
                differences.append(f"bloco {number}, {name}: {values}")
    return compared, differences


def _blocks(count: int) -> str:
    return f"{count} bloco" if count == 1 else f"{count} blocos"


def select_block(blocks: list[dict[str, str]], has_roi: bool | None) -> tuple[Region, dict]:
    """Bloco da ROI (o 1º de 2) ou do programa inteiro (o único).

    `has_roi` diz se o benchmark marca a ROI; com None, o número de blocos decide.
    """
    count = len(blocks)
    if count == 0:
        raise StatsError("nenhum bloco de estatísticas (o gem5 terminou antes de gravá-las?)")
    if has_roi is None and count in (1, 2):
        has_roi = count == 2
    if has_roi is None:
        raise StatsError(
            f"{_blocks(count)}; esperado 1 (programa inteiro) ou 2 (região de interesse "
            "e resto do programa)"
        )
    if has_roi and count != 2:
        raise StatsError(
            f"{_blocks(count)}, mas o benchmark marca a região de interesse e deveria ter 2 "
            "(a ROI e o resto do programa)"
        )
    if not has_roi and count != 1:
        raise StatsError(
            f"{_blocks(count)}, mas o benchmark não marca região de interesse e deveria ter 1 "
            "(o programa inteiro)"
        )
    return ("roi" if has_roi else "program"), blocks[0]


def _number(text: str, stat: str) -> int | float:
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        raise StatsError(f"valor inválido em {stat}: {text!r}") from None


def _value(
    metric: Metric,
    block: dict[str, str],
    components: set[str],
    values: dict[str, Value],
    cpu: str | None,
) -> tuple[Value, str | None]:
    """Valor da métrica no bloco e, se ausente, o motivo."""
    if metric.timed and cpu == "atomic":
        return None, "a CPU atomic não modela tempo"
    if metric.component and metric.component not in components:
        return None, f"{metric.component.rstrip('.')} não existe nesta configuração"
    raw = block.get(metric.stat)
    if raw is None:
        if metric.component is None:
            raise StatsError(
                f"estatística {metric.stat} não encontrada (o nome mudou nesta versão do gem5?)"
            )
        if metric.omitted == "zero":
            return 0, None
        if metric.omitted == "ratio" and metric.denominator:
            if values[metric.denominator]:
                return 0.0, None
            return None, f"indefinida: {metric.denominator} = 0"
        return None, "indefinida: média sem eventos (0/0)"
    value = _number(raw, metric.stat)
    if not math.isfinite(value):
        return None, "indefinida: média sem eventos (0/0)"
    # Razões e médias sempre em float, mesmo quando o gem5 imprime "1".
    return (value if metric.omitted == "zero" else float(value)), None


def extract(block: dict[str, str], cpu: str | None = None) -> tuple[dict[str, Value], dict]:
    """Valores das METRICS em um bloco e o motivo de cada valor ausente.

    `cpu` é o modelo (atomic, timing, minor, o3); na atomic, as métricas de tempo
    ficam ausentes.
    """
    prefixes = {metric.component for metric in METRICS if metric.component}
    components = {prefix for prefix in prefixes if any(name.startswith(prefix) for name in block)}
    values: dict[str, Value] = {}
    missing: dict[str, str] = {}
    # Razões depois dos seus denominadores.
    for metric in sorted(METRICS, key=lambda metric: metric.omitted == "ratio"):
        values[metric.key], reason = _value(metric, block, components, values, cpu)
        if reason:
            missing[metric.key] = reason
    order = [metric.key for metric in METRICS]
    reasons = {key: missing[key] for key in order if key in missing}
    return {key: values[key] for key in order}, reasons


def cpu_model(config_ini: Path) -> str | None:
    """Modelo da CPU (atomic, timing, minor, o3) segundo o config.ini do gem5."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(config_ini.read_text(encoding="utf-8", errors="replace"))
    except (OSError, configparser.Error):
        return None
    cpu_type = parser.get("system.cpu", "type", fallback="")
    return next((model for fragment, model in CPU_TYPES if fragment in cpu_type), None)


def read_region(path: Path, has_roi: bool | None, cpu: str | None = None) -> RegionStats:
    """Métricas da ROI do stats.txt, ou do programa inteiro se o benchmark não tem ROI.

    `has_roi`: o benchmark marca a ROI (2 blocos esperados) ou não (1); None aceita
    os dois. `cpu`: modelo da CPU; por padrão, o do config.ini ao lado do stats.txt.
    """
    blocks = split_blocks(path.read_text(encoding="utf-8", errors="replace"))
    region, block = select_block(blocks, has_roi)
    cpu = cpu or cpu_model(path.with_name("config.ini"))
    metrics, missing = extract(block, cpu)
    return RegionStats(region, len(blocks), cpu, metrics, missing)
