"""Auditoria e pacote de dados das campanhas, para publicação (RCB-24).

`audit` confere o que uma campanha precisa ter para valer como resultado: todas
as combinações concluídas e válidas, com `project.dirty` e `gem5_repository.dirty`
falsos, o executável do gem5 igual ao do build-info (`matches_executable`), um só
commit do projeto e uma validação de equivalência aprovada. `package` junta uma
ou mais campanhas num .tar.gz com README, licença dos dados (CC BY 4.0),
MANIFEST.json (commits, contagens, validação) e SHA256SUMS. Doc: docs/data.md.

`diff` (RCB-29) compara uma campanha com outra, como a publicada, combinação a
combinação pela chave da configuração: binário, gem5, RESULT e stats.txt.
Doc: docs/reproducibility.md.
"""

import hashlib
import io
import json
import tarfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from riscvcnnbench import __version__
from riscvcnnbench.campaign import (
    CampaignError,
    Plan,
    RunState,
    file_sha256,
    load_plan_from,
    read_log,
    states,
)
from riscvcnnbench.metric import Result, load_metrics, parse_result
from riscvcnnbench.parser import StatsError, stats_differences
from riscvcnnbench.runs import Run, display, list_runs, read_text

LICENSE = "CC-BY-4.0"
LICENSE_TEXT = """\
Os dados deste pacote (resultados de simulação, logs, configurações, tabelas e
figuras) estão sob a licença Creative Commons Atribuição 4.0 Internacional
(CC BY 4.0): https://creativecommons.org/licenses/by/4.0/legalcode.pt

The data in this package is licensed under the Creative Commons Attribution 4.0
International License (CC BY 4.0): https://creativecommons.org/licenses/by/4.0/
"""
CODE_URL = "https://github.com/YuriMZ-Nunes/riscv-cnn-bench"
GEM5_URL = "https://github.com/YuriMZ-Nunes/gem5"


@dataclass
class Audit:
    """O que a auditoria encontrou numa campanha. `problems` impedem o pacote."""

    root: Path
    name: str
    description: str
    combinations: int
    done: int
    extra_runs: int = 0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    project_commits: Counter = field(default_factory=Counter)
    gem5_commits: Counter = field(default_factory=Counter)
    gem5_sha256: Counter = field(default_factory=Counter)
    validation: dict[str, Any] | None = None
    first_started: str | None = None
    last_finished: str | None = None

    @property
    def ok(self) -> bool:
        return not self.problems


def _short(commit: object) -> str:
    return str(commit)[:7]


def current_states(root: Path) -> tuple[Plan, list[RunState], list[Run], str | None]:
    """Plano da campanha em `root`, a situação de cada combinação, todas as execuções
    das pastas e o gem5 de referência.

    O gem5 de referência é o executável mais frequente entre as execuções
    concluídas; uma combinação vale pela mais recente concluída com ele, como em
    `campaign status`.
    """
    plan = load_plan_from(root)
    found_runs = list_runs(plan.root / "runs")
    hashes = Counter(
        run.metadata.get("gem5_sha256")
        for run in found_runs
        if run.metadata.get("status") == "completed"
    )
    reference = hashes.most_common(1)[0][0] if hashes else None
    return plan, states(plan, reference), found_runs, reference


def audit(root: Path) -> Audit:
    """Confere a campanha em `root` pelas pastas das execuções e pelo campaign.json.

    Cada combinação vale pela execução de `current_states`.
    """
    plan, found, found_runs, reference = current_states(root)
    result = Audit(
        root,
        plan.campaign.name,
        (plan.campaign.description or "").strip(),
        len(found),
        sum(1 for state in found if state.done),
    )
    started, finished = [], []
    for state in found:
        name = state.planned.name
        if not state.done or state.run is None:
            result.problems.append(f"{name}: {state.label()}")
            continue
        metadata = state.run.metadata
        project = metadata.get("project") or {}
        repository = metadata.get("gem5_repository") or {}
        result.project_commits[project.get("commit")] += 1
        result.gem5_commits[repository.get("commit")] += 1
        result.gem5_sha256[metadata.get("gem5_sha256")] += 1
        started.append(metadata.get("started_at") or "")
        finished.append(metadata.get("finished_at") or "")
        if project.get("dirty") is not False:
            result.problems.append(f"{name}: project.dirty = {project.get('dirty')}")
        if repository.get("dirty") is not False:
            result.problems.append(f"{name}: gem5_repository.dirty = {repository.get('dirty')}")
        if (metadata.get("gem5_build") or {}).get("matches_executable") is not True:
            result.problems.append(f"{name}: gem5_build.matches_executable não é true")
        try:
            problem = load_metrics(state.run).problem
        except StatsError as error:
            problem = str(error)
        if problem:
            result.problems.append(f"{name}: {problem}")
    if len(result.project_commits) > 1:
        commits = ", ".join(_short(commit) for commit in result.project_commits)
        result.problems.append(f"execuções de commits diferentes do projeto: {commits}")

    chosen = {state.run.path for state in found if state.run}
    extras = [run for run in found_runs if run.path not in chosen]
    result.extra_runs = len(extras)
    if extras:
        dirty = sum(1 for run in extras if (run.metadata.get("project") or {}).get("dirty"))
        result.notes.append(
            f"{len(extras)} execução(ões) a mais nas pastas (repetidas ou substituídas), "
            f"{dirty} com project.dirty true; não contam: vale a mais recente concluída"
        )
    validations = [item for item in read_log(root).get("validations", []) if item.get("passed")]
    result.validation = validations[-1] if validations else None
    if result.validation is None:
        result.notes.append("sem validação de equivalência aprovada no campaign.json")
    elif (
        result.validation.get("project_commit") not in result.project_commits
        or result.validation.get("gem5_sha256") != reference
    ):
        result.notes.append("a validação aprovada é de outro commit do projeto ou outro gem5")
    if not (root / "report" / "runs.csv").is_file():
        result.notes.append("sem report/runs.csv (rode riscvcnnbench report)")
    if not (root / "figures" / "figures.json").is_file():
        result.notes.append("sem figures/ (rode riscvcnnbench plot)")
    result.first_started = min(started) if started else None
    result.last_finished = max(finished) if finished else None
    return result


SAME = "igual"
DIFFERENT = "diferente"
UNMATCHED = "sem correspondente"


@dataclass
class Match:
    """Uma combinação comparada com a de mesma chave na campanha de referência."""

    name: str
    status: str
    compared: int = 0
    differences: list[str] = field(default_factory=list)


@dataclass
class CampaignDiff:
    """O que `diff` encontrou: uma linha por combinação da campanha conferida."""

    name: str
    reference: str
    matches: list[Match] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(match.status == SAME for match in self.matches)


def _result(run: Run) -> Result | None:
    return parse_result(read_text(run.path / "stdout.log"))


def compare_runs(run: Run, other: Run) -> tuple[int, list[str]]:
    """Diferenças entre duas execuções da mesma configuração: binário, executável do
    gem5, campos da linha RESULT e stats.txt sem as estatísticas do host. Devolve
    quantas estatísticas foram comparadas e as diferenças."""
    differences = []
    for key in ("binary_sha256", "gem5_sha256"):
        first_hash, second_hash = run.metadata.get(key), other.metadata.get(key)
        if first_hash != second_hash:
            differences.append(f"{key}: {str(first_hash)[:12]} × {str(second_hash)[:12]}")
    mine, theirs = (_result(item) for item in (run, other))
    if mine is None or theirs is None:
        if mine != theirs:
            differences.append("RESULT: só uma das execuções imprimiu a linha")
    else:
        for key in sorted(mine.fields.keys() | theirs.fields.keys()):
            first, second = mine.fields.get(key), theirs.fields.get(key)
            if first != second:
                differences.append(
                    f"RESULT {key}: {first or '(ausente)'} × {second or '(ausente)'}"
                )
    compared, stats = stats_differences(
        *(read_text(item.path / "gem5" / "stats.txt") for item in (run, other))
    )
    if compared == 0 and not stats:
        stats = ["stats.txt vazio ou ausente"]
    return compared, differences + stats


def _binary_path_length(run: Run) -> int:
    return len(run.metadata.get("original_binary") or "")


def diff(root: Path, reference: Path) -> CampaignDiff:
    """Compara cada combinação da campanha em `root` com a de mesma chave (a da
    configuração, em plan.json) na campanha em `reference`.

    Nas duas vale a execução de `current_states`. Um caminho do binário com outro
    comprimento vira observação: ele entra na pilha do programa simulado e muda os
    ciclos (docs/reproducibility.md).
    """
    plan, found, _, _ = current_states(root)
    other_plan, others, _, _ = current_states(reference)
    by_key = {state.planned.key: state.run for state in others if state.done and state.run}
    result = CampaignDiff(plan.campaign.name, other_plan.campaign.name)
    lengths = 0
    for state in found:
        name = state.planned.name
        other = by_key.get(state.planned.key)
        if not state.done or state.run is None:
            result.matches.append(Match(name, state.label()))
        elif other is None:
            result.matches.append(Match(name, UNMATCHED))
        else:
            compared, differences = compare_runs(state.run, other)
            status = DIFFERENT if differences else SAME
            result.matches.append(Match(name, status, compared, differences))
            if _binary_path_length(state.run) != _binary_path_length(other):
                lengths += 1
    if lengths:
        result.notes.append(
            f"{lengths} combinação(ões) com o caminho do binário de outro comprimento que o "
            "da referência: ele entra na pilha do programa simulado e muda os ciclos "
            "(docs/reproducibility.md)"
        )
    return result


def summary(item: Audit) -> dict[str, Any]:
    return {
        "name": item.name,
        "description": item.description,
        "path": f"campanhas/{item.root.name}",
        "combinations": item.combinations,
        "done": item.done,
        "extra_runs": item.extra_runs,
        "project_commits": dict(item.project_commits),
        "gem5_commits": dict(item.gem5_commits),
        "gem5_sha256": dict(item.gem5_sha256),
        "validation": item.validation,
        "first_started": item.first_started,
        "last_finished": item.last_finished,
        "problems": item.problems,
        "notes": item.notes,
    }


def readme(name: str, audits: list[Audit], framework: dict[str, Any] | None) -> str:
    lines = [
        f"# {name}",
        "",
        "Pacote de dados das campanhas de simulação do riscv-cnn-bench: operações de CNN",
        "quantizadas em int8 em RISC-V, simuladas no gem5 (modo SE) com a referência escalar,",
        "instruções personalizadas e RVV. Dados sintéticos, avaliação por operação.",
        "",
        f"- Código: {CODE_URL}",
        f"- Fork do gem5: {GEM5_URL} (branch riscv-cnn-bench)",
        "",
        "## Campanhas",
        "",
    ]
    for item in audits:
        commits = ", ".join(f"`{commit}`" for commit in item.project_commits) or "-"
        gem5 = ", ".join(f"`{commit}`" for commit in item.gem5_commits) or "-"
        lines += [
            f"### `campanhas/{item.root.name}/` (campanha `{item.name}`)",
            "",
            *([item.description, ""] if item.description else []),
            f"- {item.done} de {item.combinations} combinações concluídas, "
            f"de {item.first_started} a {item.last_finished}",
            f"- Commit do projeto: {commits}; do fork do gem5: {gem5}",
        ]
        if item.validation:
            lines.append(
                f"- Validação de equivalência aprovada em {item.validation.get('finished_at')}"
            )
        lines += [f"- {note}" for note in [*item.notes, *item.problems]]
        lines.append("")
    commit = (framework or {}).get("commit")
    lines += [
        "## Estrutura",
        "",
        "Cada campanha tem a matriz (`campaign.yaml`), o plano (`plan.json`), os experimentos",
        "gerados (`experiments/`), o histórico e a validação (`campaign.json`, `validation.log`),",
        "uma pasta por execução em `runs/<combinação>/<run_id>/` (YAML, binário e fontes em",
        "`inputs/`, `stats.txt` e configuração do gem5 em `gem5/`, logs e `metadata.json`), as",
        "tabelas (`report/runs.csv`, `report/pairs.csv`) e as figuras (`figures/`, com",
        "`figures.json`). O formato de cada arquivo está em `docs/results.md`, `docs/report.md`,",
        "`docs/plots.md` e `docs/data.md` do repositório do código.",
        "",
        "`MANIFEST.json` resume as campanhas (commits, contagens, validação) e `SHA256SUMS` tem o",
        "hash de cada arquivo do pacote. Para conferir, dentro desta pasta:",
        "",
        "    sha256sum -c SHA256SUMS",
        "",
        f"Gerado por `riscvcnnbench campaign package` {__version__}"
        + (f", commit `{commit}` do código." if commit else "."),
        "",
        "## Licença",
        "",
        "CC BY 4.0 (ver `LICENSE.txt`). Ao usar os dados, cite o pacote pelo DOI do Zenodo.",
        "",
    ]
    return "\n".join(lines)


def _add(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.mtime = int(time.time())
    archive.addfile(info, io.BytesIO(data))


def _anonymous(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def package(
    roots: list[Path],
    output: Path,
    name: str,
    allow_problems: bool = False,
    framework: dict[str, Any] | None = None,
) -> list[Audit]:
    """Grava o .tar.gz com as campanhas em `<name>/`; recusa se a auditoria achar problemas."""
    audits = [audit(root) for root in roots]
    folders = Counter(item.root.name for item in audits)
    repeated = sorted(folder for folder, count in folders.items() if count > 1)
    if repeated:
        raise CampaignError(f"pastas de campanha com o mesmo nome: {', '.join(repeated)}")
    problems = [f"{item.name}: {problem}" for item in audits for problem in item.problems]
    if problems and not allow_problems:
        shown = "\n  ".join(problems[:20])
        more = f"\n  ... e mais {len(problems) - 20}" if len(problems) > 20 else ""
        raise CampaignError(f"a auditoria achou problemas:\n  {shown}{more}")
    if output.exists():
        raise CampaignError(f"já existe {display(output)}")

    manifest = {
        "name": name,
        "license": LICENSE,
        "generator": f"riscvcnnbench {__version__}",
        "framework": framework,
        "campaigns": [summary(item) for item in audits],
    }
    extra = {
        "README.md": readme(name, audits, framework).encode(),
        "LICENSE.txt": LICENSE_TEXT.encode(),
        "MANIFEST.json": (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode(),
    }
    sums = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for arcname, data in extra.items():
            _add(archive, f"{name}/{arcname}", data)
            sums.append(f"{hashlib.sha256(data).hexdigest()}  {arcname}")
        for item in audits:
            for path in sorted(item.root.rglob("*")):
                if not path.is_file():
                    continue
                arcname = f"campanhas/{item.root.name}/{path.relative_to(item.root).as_posix()}"
                archive.add(path, f"{name}/{arcname}", recursive=False, filter=_anonymous)
                sums.append(f"{file_sha256(path)}  {arcname}")
        _add(archive, f"{name}/SHA256SUMS", ("\n".join(sums) + "\n").encode())
    return audits
