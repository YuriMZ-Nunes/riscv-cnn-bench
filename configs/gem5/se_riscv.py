"""Executa um binário RISC-V Linux no gem5 em modo SE."""

import argparse
from pathlib import Path

import m5
from m5.objects import (
    AddrRange,
    AtomicSimpleCPU,
    Process,
    Root,
    SEWorkload,
    SimpleMemory,
    SrcClockDomain,
    System,
    SystemXBar,
    VoltageDomain,
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
    args = parser.parse_args()

    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error(f"Binário não encontrado: {binary}")

    system = System()

    system.clk_domain = SrcClockDomain(
        clock="1GHz",
        voltage_domain=VoltageDomain(),
    )

    system.mem_mode = "atomic"
    system.mem_ranges = [AddrRange("512MiB")]

    system.cpu = AtomicSimpleCPU()
    system.membus = SystemXBar()

    system.cpu.icache_port = system.membus.cpu_side_ports
    system.cpu.dcache_port = system.membus.cpu_side_ports
    system.cpu.createInterruptController()

    system.memory = SimpleMemory(
        range=system.mem_ranges[0],
    )
    system.memory.port = system.membus.mem_side_ports
    system.system_port = system.membus.cpu_side_ports

    system.workload = SEWorkload.init_compatible(str(binary))

    process = Process()
    process.cmd = [str(binary)]

    system.cpu.workload = process
    system.cpu.createThreads()

    root = Root(full_system=False, system=system)
    m5.instantiate()

    print(f"Executando: {binary}", flush=True)
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