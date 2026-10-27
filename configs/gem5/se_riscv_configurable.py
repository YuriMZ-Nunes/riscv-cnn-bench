"""Executa um binário RISC-V Linux no gem5 em modo SE com sistema configurável.

Permite escolher modelo de CPU, clock, VLEN, latência das instruções
personalizadas, caches L1/L2, estado das caches no início da ROI e tipo/tamanho
de memória por argumentos. Sem argumentos opcionais, monta o mesmo sistema de
se_riscv.py: AtomicSimpleCPU a 1GHz, sem caches e SimpleMemory de 512MiB.

Os argumentos correspondem às seções cpu, cache e memory dos YAMLs em
experiments/; veja docs/experiments.md e docs/scenarios.md.
"""

import argparse
import shlex
from pathlib import Path

import m5
from m5.objects import (
    FP_ALU,
    AddrRange,
    AtomicSimpleCPU,
    BaseCache,
    Cache,
    DDR4_2400_8x8,
    DefaultFUPool,
    FP_MultDiv,
    FUDesc,
    FUPool,
    IntALU,
    IntMultDiv,
    IQUnit,
    L2XBar,
    Matrix_Unit,
    MemCtrl,
    MinorCPU,
    MinorDefaultFUPool,
    MinorDefaultIntMulFU,
    MinorFU,
    MinorFUPool,
    MinorFUTiming,
    O3CPU,
    OpDesc,
    PredALU,
    Process,
    RdWrPort,
    Root,
    SEWorkload,
    SIMD_Unit,
    SimpleMemory,
    SrcClockDomain,
    StridePrefetcher,
    System,
    System_Unit,
    SystemXBar,
    TaggedPrefetcher,
    TimingSimpleCPU,
    VoltageDomain,
)
from m5.objects.BaseMinorCPU import minorMakeOpClassSet

CPU_MODELS = {
    "atomic": AtomicSimpleCPU,
    "timing": TimingSimpleCPU,
    "minor": MinorCPU,
    "o3": O3CPU,
    "o3-edge": O3CPU,
}

# Latência do mul (IntMult) nas unidades padrão da Minor e da O3. As
# instruções cnn.dot8, cnn.dwmac e cnn.rqnt[.relu] têm classe própria
# (CnnMult, fork do gem5). Na O3, ela fica na unidade do mul, com latência
# própria; na Minor, numa unidade só dela (configure_minor).
MUL_LATENCY = 3

# Causa com que o gem5 sai do laço de simulação ao receber SIGINT (Ctrl+C).
INTERRUPT_CAUSE = "user interrupt received"

# O3 de borda: larguras, filas e registradores do MediumBOOM (BOOM v3,
# WithNMediumBooms, 2-wide), mapeados para os parâmetros da O3CPU. As filas de
# emissão do BOOM (memória 12, inteira 20, ponto flutuante 16) viram uma fila
# única de 48 entradas, e as portas de emissão (1 + 2 + 1) viram as unidades
# abaixo. A unidade SIMD não vem do BOOM, que não tem a extensão V: é uma só,
# o mínimo para executar a variante RVV. Valores e justificativa em
# docs/scenarios.md.
O3_EDGE = {
    "fetchWidth": 4,
    "fetchBufferSize": 16,
    "fetchQueueSize": 16,
    "decodeWidth": 2,
    "renameWidth": 2,
    "dispatchWidth": 2,
    "issueWidth": 4,
    "wbWidth": 4,
    "commitWidth": 2,
    "numROBEntries": 64,
    "LQEntries": 16,
    "SQEntries": 16,
    "numPhysIntRegs": 80,
    "numPhysFloatRegs": 64,
    "numPhysVecRegs": 96,
}
O3_EDGE_IQ_ENTRIES = 48


def mult_div(latency, count, pipelined=True, shared=True):
    """IntMultDiv da O3; com `shared`, também executa as instruções personalizadas."""
    ops = [OpDesc(opClass="IntMult", opLat=MUL_LATENCY)]
    if shared:
        ops.append(OpDesc(opClass="CnnMult", opLat=latency, pipelined=pipelined))
    ops.append(OpDesc(opClass="IntDiv", opLat=20, pipelined=False))
    return IntMultDiv(count=count, opList=ops)


def cnn_units(latency, count, pipelined):
    """Unidades só de CnnMult (RCB-33: cpu.custom_units)."""
    return FUDesc(
        count=count, opList=[OpDesc(opClass="CnnMult", opLat=latency, pipelined=pipelined)]
    )


def configure_o3(cpu, edge, latency, units=None, pipelined=True):
    """Unidades funcionais (e, na de borda, larguras e filas) da O3CPU.

    Sem `units`, CnnMult divide as IntMultDiv com o mul, como no fork; com
    `units`, sai delas e ganha `units` unidades próprias.
    """
    shared = units is None

    def mult(count):
        return mult_div(latency, count, pipelined, shared)

    extra = [] if shared else [cnn_units(latency, units, pipelined)]
    if edge:
        for name, value in O3_EDGE.items():
            setattr(cpu, name, value)
        pool = [
            IntALU(count=2),
            mult(1),
            *extra,
            FP_ALU(count=1),
            FP_MultDiv(count=1),
            SIMD_Unit(count=1),
            Matrix_Unit(),
            System_Unit(),
            PredALU(),
            RdWrPort(count=1),
        ]
        cpu.instQueues = [IQUnit(numEntries=O3_EDGE_IQ_ENTRIES, fuPool=FUPool(FUList=pool))]
    elif latency != MUL_LATENCY or not shared or not pipelined:
        # Mesmas unidades e fila do padrão, só com a mudança nas de CnnMult.
        pool = []
        for fu in DefaultFUPool().FUList:
            pool.append(mult(fu.count) if isinstance(fu, IntMultDiv) else type(fu)())
            if isinstance(fu, IntMultDiv):
                pool += extra
        cpu.instQueues = [IQUnit(fuPool=FUPool(FUList=pool))]


def configure_minor(cpu, latency, units=None, pipelined=True):
    """Unidade própria de CnnMult na MinorCPU, com pipeline e a latência pedida.

    Uma unidade da Minor tem uma latência só (opLat), e o scoreboard libera o
    destino no commit, no fim da unidade. Por isso CnnMult sai da unidade de
    multiplicação, onde o fork a registra, e ganha uma unidade ao lado dela,
    como a de divisão. Vale também com a latência 3, para que só a latência
    mude entre os valores da matriz. `units` (RCB-33) repete essa unidade; sem
    pipeline, ela só aceita outra instrução depois da latência inteira.
    """
    pool = []
    for fu in MinorDefaultFUPool().funcUnits:
        unit = type(fu)()
        pool.append(unit)
        if isinstance(fu, MinorDefaultIntMulFU):
            unit.opClasses = minorMakeOpClassSet(["IntMult"])
            pool += [
                MinorFU(
                    opClasses=minorMakeOpClassSet(["CnnMult"]),
                    opLat=latency,
                    issueLat=1 if pipelined else latency,
                    timings=[MinorFUTiming(description="CnnMult", srcRegsRelativeLats=[0])],
                )
                for _ in range(units or 1)
            ]
    cpu.executeFuncUnits = MinorFUPool(funcUnits=pool)


# Ajustes das caches (RCB-32); os padrões são os de antes, e o YAML só os passa
# quando mudam (cache.<nível>.latency, mshrs, targets, prefetcher e cache.line).
CACHE_LATENCY = {"l1i": 2, "l1d": 2, "l2": 10}
CACHE_MSHRS = 16
CACHE_TARGETS = 20
CACHE_LINE = 64
PREFETCHERS = {"none": None, "stride": StridePrefetcher, "tagged": TaggedPrefetcher}


def make_cache(args, level):
    cache = Cache(
        size=getattr(args, f"{level}_size"),
        assoc=getattr(args, f"{level}_assoc"),
        tag_latency=getattr(args, f"{level}_latency"),
        data_latency=getattr(args, f"{level}_latency"),
        response_latency=getattr(args, f"{level}_latency"),
        mshrs=getattr(args, f"{level}_mshrs"),
        tgts_per_mshr=getattr(args, f"{level}_targets"),
    )
    prefetcher = PREFETCHERS[getattr(args, f"{level}_prefetcher")]
    if prefetcher is not None:
        cache.prefetcher = prefetcher()
    return cache


def tuning(args):
    """Os ajustes das caches que não são o padrão, para a linha "Sistema:"."""
    parts = [f"linha={args.cache_line}"] if args.cache_line != CACHE_LINE else []
    for level in ["l1i", "l1d", "l2"]:
        if not getattr(args, f"{level}_size"):
            continue
        values = {
            "latência": (getattr(args, f"{level}_latency"), CACHE_LATENCY[level]),
            "mshrs": (getattr(args, f"{level}_mshrs"), CACHE_MSHRS),
            "alvos": (getattr(args, f"{level}_targets"), CACHE_TARGETS),
            "prefetcher": (getattr(args, f"{level}_prefetcher"), "none"),
        }
        parts += [f"{level}.{name}={value}" for name, (value, default) in values.items() if value != default]
    return parts


def main():
    project_root = Path(__file__).resolve().parents[2]

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binary",
        type=Path,
        default=project_root / "build/benchmarks/hello_riscv",
        help="Executável RISC-V Linux a simular.",
    )
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Argumento repassado ao programa; repita para vários.",
    )
    parser.add_argument("--cpu", choices=sorted(CPU_MODELS), default="atomic")
    parser.add_argument("--clock", default="1GHz")
    parser.add_argument(
        "--vlen", type=int, default=256, help="VLEN da extensão V, em bits (padrão do gem5)."
    )
    parser.add_argument(
        "--custom-latency",
        type=int,
        default=MUL_LATENCY,
        help="Latência, em ciclos, de cnn.dot8, cnn.dwmac e cnn.rqnt[.relu] (minor e o3).",
    )
    parser.add_argument(
        "--custom-units",
        type=int,
        help="Unidades só de CnnMult (padrão: 1 própria na minor; as IntMultDiv nas O3).",
    )
    parser.add_argument(
        "--custom-unpipelined",
        action="store_true",
        help="As unidades de CnnMult só aceitam outra instrução depois da latência inteira.",
    )
    parser.add_argument("--mem-type", choices=["simple", "ddr4"], default="simple")
    parser.add_argument("--mem-size", default="512MiB")
    parser.add_argument(
        "--cache-line", type=int, choices=[32, 64, 128], default=CACHE_LINE, help="Linha das caches."
    )
    for level in ["l1i", "l1d", "l2"]:
        parser.add_argument(f"--{level}-size", help=f"Tamanho da {level}; omita para não criar.")
        parser.add_argument(f"--{level}-assoc", type=int, default=8 if level == "l2" else 4)
        parser.add_argument(f"--{level}-latency", type=int, default=CACHE_LATENCY[level])
        parser.add_argument(f"--{level}-mshrs", type=int, default=CACHE_MSHRS)
        parser.add_argument(f"--{level}-targets", type=int, default=CACHE_TARGETS)
        parser.add_argument(f"--{level}-prefetcher", choices=sorted(PREFETCHERS), default="none")
    parser.add_argument(
        "--roi-caches",
        choices=["warm", "cold"],
        default="warm",
        help="cold: esvazia as caches no m5_work_begin que antecede a ROI (rcb_roi_begin).",
    )
    args = parser.parse_args()

    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error(f"Binário não encontrado: {binary}")
    if args.l2_size and not (args.l1i_size and args.l1d_size):
        parser.error("A L2 requer --l1i-size e --l1d-size.")
    if args.custom_latency < 1:
        parser.error("--custom-latency deve ser no mínimo 1.")
    if args.custom_units is not None and args.custom_units < 1:
        parser.error("--custom-units deve ser no mínimo 1.")
    pipelined = not args.custom_unpipelined

    system = System()
    # Com caches frias, o m5_work_begin de rcb_roi_begin devolve o controle a
    # este script, que esvazia as caches antes da ROI.
    system.exit_on_work_items = args.roi_caches == "cold"

    system.clk_domain = SrcClockDomain(
        clock=args.clock,
        voltage_domain=VoltageDomain(),
    )

    system.cache_line_size = args.cache_line
    system.mem_mode = "atomic" if args.cpu == "atomic" else "timing"
    system.mem_ranges = [AddrRange(args.mem_size)]

    system.cpu = CPU_MODELS[args.cpu]()
    system.cpu.isa = [system.cpu.ArchISA(vlen=args.vlen)]
    if args.cpu in ("o3", "o3-edge"):
        configure_o3(
            system.cpu, args.cpu == "o3-edge", args.custom_latency, args.custom_units, pipelined
        )
    elif args.cpu == "minor":
        configure_minor(system.cpu, args.custom_latency, args.custom_units, pipelined)
    system.membus = SystemXBar()

    # Caches L1 ligam a CPU à L2 (se existir) ou diretamente ao barramento.
    if args.l2_size:
        system.l2bus = L2XBar()
        system.l2cache = make_cache(args, "l2")
        system.l2cache.cpu_side = system.l2bus.mem_side_ports
        system.l2cache.mem_side = system.membus.cpu_side_ports
        below_l1 = system.l2bus.cpu_side_ports
    else:
        below_l1 = system.membus.cpu_side_ports

    if args.l1i_size:
        system.cpu.icache = make_cache(args, "l1i")
        system.cpu.icache.cpu_side = system.cpu.icache_port
        system.cpu.icache.mem_side = below_l1
    else:
        system.cpu.icache_port = system.membus.cpu_side_ports

    if args.l1d_size:
        system.cpu.dcache = make_cache(args, "l1d")
        system.cpu.dcache.cpu_side = system.cpu.dcache_port
        system.cpu.dcache.mem_side = below_l1
    else:
        system.cpu.dcache_port = system.membus.cpu_side_ports

    system.cpu.createInterruptController()

    if args.mem_type == "ddr4":
        system.mem_ctrl = MemCtrl(dram=DDR4_2400_8x8(range=system.mem_ranges[0]))
        system.mem_ctrl.port = system.membus.mem_side_ports
    else:
        system.memory = SimpleMemory(range=system.mem_ranges[0])
        system.memory.port = system.membus.mem_side_ports

    system.system_port = system.membus.cpu_side_ports

    system.workload = SEWorkload.init_compatible(str(binary))

    process = Process()
    process.cmd = [str(binary), *args.arg]

    system.cpu.workload = process
    system.cpu.createThreads()

    root = Root(full_system=False, system=system)
    m5.instantiate()

    print(f"Executando: {shlex.join(process.cmd)}", flush=True)
    print(
        f"Sistema: cpu={args.cpu} clock={args.clock} vlen={args.vlen} "
        f"custom_latency={args.custom_latency} "
        f"l1i={args.l1i_size} l1d={args.l1d_size} l2={args.l2_size} "
        f"memória={args.mem_type}/{args.mem_size} caches_roi={args.roi_caches}"
        + (f" custom_units={args.custom_units}" if args.custom_units is not None else "")
        + (" custom_pipelined=false" if not pipelined else "")
        + "".join(f" {part}" for part in tuning(args)),
        flush=True,
    )
    exit_event = m5.simulate()
    while exit_event.getCause() == "workbegin":
        # Só acontece com --roi-caches cold. Com o sistema drenado, grava as
        # linhas sujas na memória e invalida as caches. Só as caches:
        # m5.memInvalidate(root) também esvaziaria as TLBs e o BTB.
        m5.drain()
        caches = [obj for obj in root.descendants() if isinstance(obj, BaseCache)]
        for cache in caches:
            cache.memWriteback()
        for cache in caches:
            cache.memInvalidate()
        print(
            f"Caches esvaziadas antes da ROI no tick {m5.curTick()}: {len(caches)}",
            flush=True,
        )
        exit_event = m5.simulate()

    if exit_event.getCause() == INTERRUPT_CAUSE:
        # SIGINT: o programa não terminou e as estatísticas estão incompletas.
        # Sem a linha "Simulação encerrada", o wrapper não registra código do
        # programa; o 130 (128 + SIGINT) faz a execução contar como falha.
        print(f"Simulação interrompida no tick {m5.curTick()}: {INTERRUPT_CAUSE}", flush=True)
        raise SystemExit(130)

    print(
        f"Simulação encerrada no tick {m5.curTick()}: "
        f"{exit_event.getCause()} "
        f"(code={exit_event.getCode()})",
        flush=True,
    )

    raise SystemExit(exit_event.getCode())


if __name__ == "__m5_main__":
    main()
