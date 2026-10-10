"""Executa um binário RISC-V Linux no gem5 em modo SE com sistema configurável.

Permite escolher modelo de CPU, clock, caches L1/L2 e tipo/tamanho de memória
por argumentos. Sem argumentos opcionais, monta o mesmo sistema de
se_riscv.py: AtomicSimpleCPU a 1GHz, sem caches e SimpleMemory de 512MiB.

Os argumentos correspondem às seções cpu, cache e memory dos YAMLs em
experiments/; veja docs/experiments.md.
"""

import argparse
import shlex
from pathlib import Path

import m5
from m5.objects import (
    AddrRange,
    AtomicSimpleCPU,
    Cache,
    DDR4_2400_8x8,
    L2XBar,
    MemCtrl,
    MinorCPU,
    O3CPU,
    Process,
    Root,
    SEWorkload,
    SimpleMemory,
    SrcClockDomain,
    System,
    SystemXBar,
    TimingSimpleCPU,
    VoltageDomain,
)

CPU_MODELS = {
    "atomic": AtomicSimpleCPU,
    "timing": TimingSimpleCPU,
    "minor": MinorCPU,
    "o3": O3CPU,
}


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
    parser.add_argument("--mem-type", choices=["simple", "ddr4"], default="simple")
    parser.add_argument("--mem-size", default="512MiB")
    for level in ["l1i", "l1d", "l2"]:
        parser.add_argument(f"--{level}-size", help=f"Tamanho da {level}; omita para não criar.")
        parser.add_argument(f"--{level}-assoc", type=int, default=8 if level == "l2" else 4)
    args = parser.parse_args()

    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error(f"Binário não encontrado: {binary}")
    if args.l2_size and not (args.l1i_size and args.l1d_size):
        parser.error("A L2 requer --l1i-size e --l1d-size.")

    system = System()

    system.clk_domain = SrcClockDomain(
        clock=args.clock,
        voltage_domain=VoltageDomain(),
    )

    system.mem_mode = "atomic" if args.cpu == "atomic" else "timing"
    system.mem_ranges = [AddrRange(args.mem_size)]

    system.cpu = CPU_MODELS[args.cpu]()
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
        f"Sistema: cpu={args.cpu} clock={args.clock} "
        f"l1i={args.l1i_size} l1d={args.l1d_size} l2={args.l2_size} "
        f"memória={args.mem_type}/{args.mem_size}",
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
