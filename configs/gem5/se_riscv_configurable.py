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
    System,
    System_Unit,
    SystemXBar,
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


def mult_div(latency, count):
    """IntMultDiv da O3 com a latência das instruções personalizadas."""
    return IntMultDiv(
        count=count,
        opList=[
            OpDesc(opClass="IntMult", opLat=MUL_LATENCY),
            OpDesc(opClass="CnnMult", opLat=latency),
            OpDesc(opClass="IntDiv", opLat=20, pipelined=False),
        ],
    )


def configure_o3(cpu, edge, latency):
    """Unidades funcionais (e, na de borda, larguras e filas) da O3CPU."""
    if edge:
        for name, value in O3_EDGE.items():
            setattr(cpu, name, value)
        units = [
            IntALU(count=2),
            mult_div(latency, count=1),
            FP_ALU(count=1),
            FP_MultDiv(count=1),
            SIMD_Unit(count=1),
            Matrix_Unit(),
            System_Unit(),
            PredALU(),
            RdWrPort(count=1),
        ]
        cpu.instQueues = [IQUnit(numEntries=O3_EDGE_IQ_ENTRIES, fuPool=FUPool(FUList=units))]
    elif latency != MUL_LATENCY:
        # Mesmas unidades e fila do padrão, só com outra latência para CnnMult.
        units = [
            mult_div(latency, fu.count) if isinstance(fu, IntMultDiv) else type(fu)()
            for fu in DefaultFUPool().FUList
        ]
        cpu.instQueues = [IQUnit(fuPool=FUPool(FUList=units))]


def configure_minor(cpu, latency):
    """Unidade própria de CnnMult na MinorCPU, com pipeline e a latência pedida.

    Uma unidade da Minor tem uma latência só (opLat), e o scoreboard libera o
    destino no commit, no fim da unidade. Por isso CnnMult sai da unidade de
    multiplicação, onde o fork a registra, e ganha uma unidade ao lado dela,
    como a de divisão. Vale também com a latência 3, para que só a latência
    mude entre os valores da matriz.
    """
    units = []
    for fu in MinorDefaultFUPool().funcUnits:
        unit = type(fu)()
        units.append(unit)
        if isinstance(fu, MinorDefaultIntMulFU):
            unit.opClasses = minorMakeOpClassSet(["IntMult"])
            units.append(
                MinorFU(
                    opClasses=minorMakeOpClassSet(["CnnMult"]),
                    opLat=latency,
                    issueLat=1,
                    timings=[MinorFUTiming(description="CnnMult", srcRegsRelativeLats=[0])],
                )
            )
    cpu.executeFuncUnits = MinorFUPool(funcUnits=units)


def make_cache(size, assoc, latency):
    return Cache(
        size=size,
        assoc=assoc,
        tag_latency=latency,
        data_latency=latency,
        response_latency=latency,
        mshrs=16,
        tgts_per_mshr=20,
    )


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
    parser.add_argument("--mem-type", choices=["simple", "ddr4"], default="simple")
    parser.add_argument("--mem-size", default="512MiB")
    for level in ["l1i", "l1d", "l2"]:
        parser.add_argument(f"--{level}-size", help=f"Tamanho da {level}; omita para não criar.")
        parser.add_argument(f"--{level}-assoc", type=int, default=8 if level == "l2" else 4)
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

    system = System()
    # Com caches frias, o m5_work_begin de rcb_roi_begin devolve o controle a
    # este script, que esvazia as caches antes da ROI.
    system.exit_on_work_items = args.roi_caches == "cold"

    system.clk_domain = SrcClockDomain(
        clock=args.clock,
        voltage_domain=VoltageDomain(),
    )

    system.mem_mode = "atomic" if args.cpu == "atomic" else "timing"
    system.mem_ranges = [AddrRange(args.mem_size)]

    system.cpu = CPU_MODELS[args.cpu]()
    system.cpu.isa = [system.cpu.ArchISA(vlen=args.vlen)]
    if args.cpu in ("o3", "o3-edge"):
        configure_o3(system.cpu, args.cpu == "o3-edge", args.custom_latency)
    elif args.cpu == "minor":
        configure_minor(system.cpu, args.custom_latency)
    system.membus = SystemXBar()

    # Caches L1 ligam a CPU à L2 (se existir) ou diretamente ao barramento.
    if args.l2_size:
        system.l2bus = L2XBar()
        system.l2cache = make_cache(args.l2_size, args.l2_assoc, latency=10)
        system.l2cache.cpu_side = system.l2bus.mem_side_ports
        system.l2cache.mem_side = system.membus.cpu_side_ports
        below_l1 = system.l2bus.cpu_side_ports
    else:
        below_l1 = system.membus.cpu_side_ports

    if args.l1i_size:
        system.cpu.icache = make_cache(args.l1i_size, args.l1i_assoc, latency=2)
        system.cpu.icache.cpu_side = system.cpu.icache_port
        system.cpu.icache.mem_side = below_l1
    else:
        system.cpu.icache_port = system.membus.cpu_side_ports

    if args.l1d_size:
        system.cpu.dcache = make_cache(args.l1d_size, args.l1d_assoc, latency=2)
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
        f"memória={args.mem_type}/{args.mem_size} caches_roi={args.roi_caches}",
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

    print(
        f"Simulação encerrada no tick {m5.curTick()}: "
        f"{exit_event.getCause()} "
        f"(code={exit_event.getCode()})",
        flush=True,
    )

    raise SystemExit(exit_event.getCode())


if __name__ == "__m5_main__":
    main()
