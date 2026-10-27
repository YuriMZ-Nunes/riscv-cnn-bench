"""Campanhas: execução em lote de uma matriz de experimentos (RCB-19).

Uma matriz (YAML em campaigns/) tem grupos; cada grupo é o produto cartesiano
de experimentos base de experiments/ com os valores dos campos que variam. A
campanha é a união dos grupos, sem repetir combinações. Cada combinação vira
um experimento comum, executado como pelo `riscvcnnbench run`, com a própria
pasta. Formato, pasta da campanha e retomada em docs/campaigns.md.
"""

import copy
import difflib
import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import AfterValidator, Field, field_validator

from riscvcnnbench.config import (
    MUL_LATENCY,
    NAME_PATTERN,
    PROJECT_ROOT,
    ConfigError,
    CpuConfig,
    Experiment,
    StrictModel,
    check_experiment,
    load_experiment,
    load_yaml,
    raise_problems,
    validate_model,
)
from riscvcnnbench.metric import IRRELEVANT, scenario_label
from riscvcnnbench.runner import check_environment, execute, prepare_run
from riscvcnnbench.runs import Run, diagnose, display, list_runs, metric_cells

EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
DEFAULT_ROOT = Path("results") / "campaigns"
# Campos que a campanha controla: o experimento base define a operação e os
# argumentos, e o nome e a pasta de cada combinação são gerados.
CONTROLLED = ("name", "description", "output", "benchmark.name", "benchmark.args")
# CPUs que não modelam a latência das unidades: cpu.custom_latency não vale nelas.
NO_FU_TIMING = ("atomic", "timing")
VALIDATION_COMMAND = [sys.executable, "-m", "pytest", "-m", "validation", "-q"]


def base_path(reference: str) -> Path:
    """Arquivo de um experimento base: nome em experiments/ ou caminho .yaml."""
    if reference.endswith((".yaml", ".yml")) or "/" in reference:
        path = Path(reference)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return EXPERIMENTS_DIR / f"{reference}.yaml"


def _check_base(reference: str) -> str:
    path = base_path(reference)
    if not path.is_file():
        names = sorted(item.stem for item in EXPERIMENTS_DIR.glob("*.yaml"))
        close = difflib.get_close_matches(reference, names, n=1)
        hint = (
            f"você quis dizer {close[0]!r}?"
            if close
            else "use um nome de experiments/ ou um caminho"
        )
        raise ValueError(f"experimento {reference!r} não encontrado; {hint}")
    try:
        load_experiment(path)
    except ConfigError as error:
        raise ValueError(f"experimento base inválido: {error}") from error
    return reference


def _check_path(path: str) -> str:
    """Campo do experimento em notação com pontos, como cpu.model."""
    if path in CONTROLLED or any(path.startswith(f"{item}.") for item in CONTROLLED):
        raise ValueError(
            f"{path!r} é definido pela campanha; a operação e os argumentos vêm do experimento base"
        )
    model: Any = Experiment
    parts = path.split(".")
    for index, part in enumerate(parts):
        fields = getattr(model, "model_fields", None)
        if fields is None or part not in fields:
            prefix = ".".join(parts[:index])
            valid = sorted(f"{prefix}.{name}" if prefix else name for name in fields or {})
            close = difflib.get_close_matches(path, valid, n=1)
            hint = (
                f"você quis dizer {close[0]!r}?" if close else f"campos válidos: {', '.join(valid)}"
            )
            raise ValueError(f"campo {path!r} não existe no experimento; {hint}")
        annotation = fields[part].annotation
        candidates = [annotation, *getattr(annotation, "__args__", ())]
        model = next(
            (c for c in candidates if isinstance(c, type) and issubclass(c, StrictModel)), None
        )
    return path


BaseRef = Annotated[str, AfterValidator(_check_base)]
FieldPath = Annotated[str, AfterValidator(_check_path)]


class Group(StrictModel):
    name: str = Field(pattern=NAME_PATTERN)
    description: str = ""
    experiments: list[BaseRef] = Field(min_length=1, description="Experimentos base.")
    set: dict[FieldPath, Any] = Field(default={}, description="Campos fixos do grupo.")
    vary: dict[FieldPath, Annotated[list[Any], Field(min_length=1)]] = Field(
        default={}, description="Campos que variam: produto cartesiano dos valores."
    )


class CampaignOutput(StrictModel):
    dir: Path | None = Field(default=None, description="Padrão: results/campaigns/<name>.")


class Campaign(StrictModel):
    name: str = Field(pattern=NAME_PATTERN)
    description: str = ""
    validate_first: bool = Field(
        default=False, alias="validate", description="Roda pytest -m validation antes."
    )
    set: dict[FieldPath, Any] = Field(default={}, description="Campos fixos de todos os grupos.")
    groups: list[Group] = Field(min_length=1)
    output: CampaignOutput = CampaignOutput()

    @field_validator("groups")
    @classmethod
    def unique_groups(cls, groups: list[Group]) -> list[Group]:
        names = [group.name for group in groups]
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            raise ValueError(f"nomes de grupo repetidos: {', '.join(repeated)}")
        return groups


def load_campaign(path: Path) -> Campaign:
    """Lê e valida uma matriz, reunindo todos os problemas em um ConfigError."""
    data, lines, problems = load_yaml(path, "name e groups")
    campaign, invalid = validate_model(Campaign, data, lines)
    raise_problems(path, problems + invalid)
    assert campaign is not None
    return campaign


def campaign_root(campaign: Campaign, output: Path | None = None) -> Path:
    """Pasta da campanha; caminhos relativos partem da raiz do projeto."""
    root = output or campaign.output.dir or DEFAULT_ROOT / campaign.name
    return root if root.is_absolute() else PROJECT_ROOT / root


@dataclass
class PlannedRun:
    """Uma combinação da matriz: o experimento gerado, com nome e chave."""

    name: str
    key: str
    base: str
    groups: list[str]
    values: dict[str, Any]
    data: dict[str, Any]

    @property
    def path(self) -> str:
        return f"experiments/{self.name}.yaml"


@dataclass
class Plan:
    campaign: Campaign
    root: Path
    runs: list[PlannedRun]
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    invalid: list[dict[str, Any]] = field(default_factory=list)

    def document(self) -> dict[str, Any]:
        """Conteúdo de plan.json."""
        return {
            "campaign": self.campaign.name,
            "runs": [
                {
                    "name": run.name,
                    "key": run.key,
                    "base": run.base,
                    "groups": run.groups,
                    "values": run.values,
                    "experiment": run.path,
                }
                for run in self.runs
            ],
            "duplicates": self.duplicates,
            "invalid": self.invalid,
        }


def assign(data: dict[str, Any], path: str, value: Any) -> None:
    node = data
    for part in path.split(".")[:-1]:
        node = node.setdefault(part, {})
    node[path.split(".")[-1]] = copy.deepcopy(value)


def normalize(data: dict[str, Any]) -> list[str]:
    """Tira os campos que não afetam a combinação; devolve os que saíram.

    A VLEN só vale para a rvv e a latência das instruções personalizadas só para
    a custom (a mesma tabela IRRELEVANT do compare), e a latência também não
    vale nas CPUs atomic e timing. Sem esses campos, combinações que só diferem
    neles ficam iguais e rodam uma vez.
    """
    variant = (data.get("benchmark") or {}).get("variant", "ref")
    model = (data.get("cpu") or {}).get("model", "atomic")
    fields = set(IRRELEVANT.get(variant, set()))
    if model in NO_FU_TIMING:
        fields.add(("cpu", "custom_latency"))
    removed = []
    for section, name in sorted(fields):
        if name in (data.get(section) or {}):
            del data[section][name]
            removed.append(f"{section}.{name}")
    return removed


def config_key(resolved: dict[str, Any]) -> str:
    """Identidade de uma configuração: tudo menos nome, descrição e pasta de saída."""
    content = {k: v for k, v in resolved.items() if k not in ("name", "description", "output")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]


def _token(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", text.lstrip("-"))


def run_name(base: str, experiment: Experiment) -> str:
    """Nome legível de uma combinação, como fc_s__custom__minor__l1-l2__lat6."""
    resolved = experiment.model_dump(mode="json")
    cpu = experiment.cpu
    parts = [_token(base), experiment.benchmark.variant, cpu.model]
    parts.append(re.sub(r"[^A-Za-z0-9-]", "", scenario_label(resolved).replace(",", "-")))
    if experiment.benchmark.variant == "custom" and cpu.custom_latency != MUL_LATENCY:
        parts.append(f"lat{cpu.custom_latency}")
    if experiment.benchmark.variant == "rvv" and cpu.vlen != CpuConfig().vlen:
        parts.append(f"vlen{cpu.vlen}")
    if cpu.clock != CpuConfig().clock:
        parts.append(_token(cpu.clock))
    flags = experiment.compiler.flags
    if flags != ["-O2"]:
        parts.append("_".join(_token(flag) for flag in flags) or "sem-flags")
    return "__".join(parts)


def build_plan(campaign: Campaign, root: Path, source: Path) -> Plan:
    """Combinações da matriz, sem repetições e sem as inválidas (listadas à parte)."""
    runs: dict[str, PlannedRun] = {}
    plan = Plan(campaign, root, [])
    runs_dir = root / "runs"
    bases: dict[str, dict[str, Any]] = {}
    for group in campaign.groups:
        axes = list(group.vary.items())
        for reference in group.experiments:
            base = base_path(reference)
            if reference not in bases:
                # O YAML como escrito (já validado ao ler a matriz), sem os padrões.
                bases[reference] = yaml.safe_load(base.read_text(encoding="utf-8"))
            for combination in itertools.product(*(values for _, values in axes)):
                values = {path: value for (path, _), value in zip(axes, combination, strict=True)}
                data = copy.deepcopy(bases[reference])
                for path, value in {**campaign.set, **group.set, **values}.items():
                    assign(data, path, value)
                removed = normalize(data)
                data.pop("output", None)
                described = {"base": reference, "group": group.name, "values": values}
                try:
                    experiment = check_experiment({**data, "name": base.stem}, source)
                except ConfigError as error:
                    plan.invalid.append({**described, "problems": error.problems})
                    continue
                key = config_key(experiment.model_dump(mode="json"))
                if key in runs:
                    if group.name not in runs[key].groups:
                        runs[key].groups.append(group.name)
                    same = {"same_as": runs[key].name, "ignored": removed}
                    plan.duplicates.append({**described, **same})
                    continue
                name = run_name(base.stem, experiment)
                runs[key] = PlannedRun(name, key, reference, [group.name], values, data)
    # Nomes iguais para configurações diferentes ganham o começo da chave.
    names = [run.name for run in runs.values()]
    for run in runs.values():
        if names.count(run.name) > 1:
            run.name = f"{run.name}__{run.key[:6]}"
    for run in runs.values():
        output = runs_dir / run.name
        relative = (
            output.relative_to(PROJECT_ROOT) if output.is_relative_to(PROJECT_ROOT) else output
        )
        run.data = {
            **run.data,
            "name": run.name,
            "description": f"Campanha {campaign.name}, grupo(s) {', '.join(run.groups)}.",
            "output": {"dir": str(relative)},
        }
    plan.runs = list(runs.values())
    return plan


# ---------------------------------------------------------------------------
# Estado das combinações
# ---------------------------------------------------------------------------

STATUS_DONE = "concluída"
STATUS_PENDING = "pendente"
STATUS_STALE = "desatualizada"
STATUS_FAILED = "falhou"
STATUS_INTERRUPTED = "interrompida"
STATUS_INCOMPLETE = "incompleta"


@dataclass
class RunState:
    """Situação de uma combinação, pela pasta da execução mais relevante."""

    planned: PlannedRun
    status: str
    run: Run | None
    attempts: int

    @property
    def done(self) -> bool:
        return self.status == STATUS_DONE

    def cells(self) -> list[str]:
        return metric_cells(self.run) if self.run else ["-", "-", "-"]

    def label(self) -> str:
        problem = diagnose(self.run) if self.run and self.status != STATUS_DONE else None
        if self.status == STATUS_FAILED and problem:
            return f"{self.status} ({problem.kind})"
        return self.status

    def provenance(self) -> list[str]:
        """Por que uma concluída não vale como resultado; vazio se vale (ou não concluiu)."""
        return provenance_problems(self.run) if self.done and self.run else []


def provenance_problems(run: Run) -> list[str]:
    """Árvore suja ou executável do gem5 diferente do build registrado, pelo metadata.json."""
    metadata = run.metadata
    problems = []
    if (metadata.get("project") or {}).get("dirty") is True:
        problems.append("project.dirty: true")
    if (metadata.get("gem5_repository") or {}).get("dirty") is True:
        problems.append("gem5_repository.dirty: true")
    if (metadata.get("gem5_build") or {}).get("matches_executable") is False:
        problems.append("gem5_build.matches_executable: false")
    return problems


def run_key(run: Run) -> str | None:
    resolved = run.resolved
    return config_key(resolved) if resolved else None


def run_state(planned: PlannedRun, root: Path, gem5_sha256: str | None) -> RunState:
    """Concluída se alguma execução da mesma configuração terminou com este gem5.

    Senão vale a mais recente: falhou, interrompida ou incompleta; uma concluída
    com outro executável do gem5 fica desatualizada. As que não batem com a
    chave do plano (outra configuração com o mesmo nome) são ignoradas.
    """
    folder = root / "runs" / planned.name
    found = (
        [run for run in list_runs(folder) if run_key(run) == planned.key] if folder.is_dir() else []
    )
    if not found:
        return RunState(planned, STATUS_PENDING, None, 0)
    completed = [run for run in found if run.metadata.get("status") == "completed"]
    current = [run for run in completed if run.metadata.get("gem5_sha256") == gem5_sha256]
    if current:
        return RunState(planned, STATUS_DONE, current[-1], len(found))
    latest = found[-1]
    status = latest.metadata.get("status")
    if status == "completed":
        return RunState(planned, STATUS_STALE, latest, len(found))
    if status == "failed":
        problem = diagnose(latest)
        interrupted = problem is not None and problem.kind == "interrupted"
        return RunState(
            planned, STATUS_INTERRUPTED if interrupted else STATUS_FAILED, latest, len(found)
        )
    if status == "interrupted":
        return RunState(planned, STATUS_INTERRUPTED, latest, len(found))
    return RunState(planned, STATUS_INCOMPLETE, latest, len(found))


def states(plan: Plan, gem5_sha256: str | None) -> list[RunState]:
    return [run_state(planned, plan.root, gem5_sha256) for planned in plan.runs]


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Pasta da campanha, validação e execução
# ---------------------------------------------------------------------------


class CampaignError(Exception):
    """Problema que impede a campanha de começar."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _git(directory: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def project_state() -> dict[str, Any]:
    """Commit do projeto e se há mudanças não commitadas (None fora de um repositório)."""
    commit = _git(PROJECT_ROOT, "rev-parse", "HEAD")
    status = _git(PROJECT_ROOT, "status", "--porcelain")
    return {
        "commit": commit.strip() if commit is not None else None,
        "dirty": None if status is None else bool(status.strip()),
    }


GEM5_SUBMODULE = Path("third_party/gem5")
SHOWN_CHANGES = 3


def tree_warnings(root: Path = PROJECT_ROOT) -> list[str]:
    """Avisos de mudanças não commitadas no projeto e no submódulo do gem5.

    Cada execução grava `git status --porcelain` no início (scripts/provenance.py),
    incluindo arquivos não rastreados; com mudanças, ela sai com `dirty: true`.
    """
    warnings = []
    trees = [
        (root, "o projeto", "project.dirty"),
        (root / GEM5_SUBMODULE, f"o submódulo do gem5 ({GEM5_SUBMODULE})", "gem5_repository.dirty"),
    ]
    for directory, label, field_name in trees:
        if not (directory / ".git").exists():
            continue
        status = _git(directory, "status", "--porcelain")
        changes = [line.strip() for line in (status or "").splitlines() if line.strip()]
        if not changes:
            continue
        shown = ", ".join(changes[:SHOWN_CHANGES])
        if len(changes) > SHOWN_CHANGES:
            shown += f" e mais {len(changes) - SHOWN_CHANGES}"
        warnings.append(
            f"Aviso: {label} tem {len(changes)} mudança(s) não commitada(s) ({shown}). As "
            f"execuções vão sair com {field_name}: true e não valem como resultado "
            "(campaign audit). Faça o commit antes e não altere a árvore durante a campanha; "
            "rascunhos ficam em build/."
        )
    return warnings


def read_log(root: Path) -> dict[str, Any]:
    path = root / "campaign.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"sessions": [], "validations": []}


def write_json(path: Path, content: Any) -> None:
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prepare_folder(plan: Plan, matrix: Path, update: bool) -> None:
    """Grava a cópia da matriz, o plano e os experimentos gerados.

    Se a pasta já tem outra matriz, recusa, a menos que `update`: as execuções
    já feitas continuam valendo para as combinações que ficaram no plano.
    """
    root = plan.root
    text = matrix.read_text(encoding="utf-8")
    copy_path = root / "campaign.yaml"
    if copy_path.is_file() and copy_path.read_text(encoding="utf-8") != text and not update:
        raise CampaignError(
            f"a matriz mudou desde a última execução desta campanha ({copy_path}). Use --update "
            "para seguir com a nova (as execuções feitas continuam valendo para as combinações "
            "que ficaram) ou outro name."
        )
    (root / "experiments").mkdir(parents=True, exist_ok=True)
    copy_path.write_text(text, encoding="utf-8")
    write_json(root / "plan.json", plan.document())
    for planned in plan.runs:
        (root / planned.path).write_text(
            yaml.safe_dump(planned.data, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )


def validation_matches(record: dict[str, Any], gem5_sha256: str | None, project: dict) -> bool:
    """Uma validação anterior vale se passou com o mesmo gem5 e o mesmo commit, sem mudanças."""
    return (
        record.get("passed") is True
        and record.get("gem5_sha256") == gem5_sha256
        and record.get("project_commit") == project["commit"]
        and record.get("project_dirty") is False
        and project["dirty"] is False
    )


def run_validation(root: Path, jobs: int) -> int:
    """Roda pytest -m validation; a saída vai para <campanha>/validation.log."""
    env = {**os.environ, "RCB_JOBS": str(jobs)}
    with (root / "validation.log").open("w", encoding="utf-8") as log:
        return subprocess.run(
            VALIDATION_COMMAND, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT, env=env
        ).returncode


def validate_campaign(
    root: Path,
    gem5_sha256: str | None,
    jobs: int,
    echo: Callable[[str], None],
    runner: Callable[[Path, int], int] | None = None,
) -> dict[str, Any]:
    """Valida antes da campanha, ou reaproveita uma validação equivalente já feita."""
    log = read_log(root)
    project = project_state()
    for record in reversed(log.get("validations", [])):
        if validation_matches(record, gem5_sha256, project):
            echo(f"Validação: já feita em {record['finished_at']} com este gem5 e este commit.")
            return record
    echo("Validação: pytest -m validation (pode levar mais de 10 min)...")
    started = now()
    code = (runner or run_validation)(root, jobs)
    record = {
        "passed": code == 0,
        "exit_code": code,
        "started_at": started,
        "finished_at": now(),
        "gem5_sha256": gem5_sha256,
        "project_commit": project["commit"],
        "project_dirty": project["dirty"],
        "log": "validation.log",
    }
    log.setdefault("validations", []).append(record)
    write_json(root / "campaign.json", log)
    if code != 0:
        raise CampaignError(
            f"a validação falhou (código {code}); veja {root / 'validation.log'}. "
            "A campanha não começou."
        )
    echo("Validação: passou.")
    return record


def execute_planned(path: Path, gem5: Path) -> Path:
    """Executa um experimento gerado como o `riscvcnnbench run`; devolve a pasta."""
    prepared = prepare_run(path, gem5)
    execute(prepared)
    return prepared.run_dir


@dataclass
class Outcome:
    """Resultado de uma sessão de `campaign run`."""

    planned: int
    skipped: int
    executed: list[RunState]
    interrupted: bool = False

    @property
    def failed(self) -> list[RunState]:
        return [state for state in self.executed if not state.done]


def run_plan(
    plan: Plan,
    gem5: Path,
    jobs: int,
    echo: Callable[[str], None],
    executor: Callable[[Path, Path], Path] | None = None,
) -> Outcome:
    """Executa as combinações que não estão concluídas, `jobs` de cada vez.

    Uma falha não interrompe as outras. Com Ctrl+C, as que não começaram são
    canceladas e as em andamento terminam como interrompidas.
    """
    gem5_sha256 = file_sha256(gem5)
    execute_one = executor or execute_planned
    pending = [state for state in states(plan, gem5_sha256) if not state.done]
    skipped = len(plan.runs) - len(pending)
    echo(
        f"{len(plan.runs)} combinação(ões): {skipped} já concluída(s), "
        f"{len(pending)} a executar com {jobs} tarefa(s) em paralelo."
    )
    outcome = Outcome(len(plan.runs), skipped, [])
    lock = threading.Lock()

    def one(state: RunState) -> RunState:
        try:
            execute_one(plan.root / state.planned.path, gem5)
        except Exception as error:  # noqa: BLE001 - a falha de uma não para as outras
            with lock:
                echo(f"  erro ao executar {state.planned.name}: {error}")
        return run_state(state.planned, plan.root, gem5_sha256)

    pool = ThreadPoolExecutor(max_workers=max(1, jobs))
    futures = [pool.submit(one, state) for state in pending]

    def collect(future: Future[RunState]) -> None:
        result = future.result()
        outcome.executed.append(result)
        line = f"[{len(outcome.executed)}/{len(pending)}] {result.planned.name}: {result.label()}"
        if result.done:
            insts, cycles, ipc = result.cells()
            line += f" — {insts} instruções, {cycles} ciclos, IPC {ipc}"
            problems = result.provenance()
            if problems:
                line += f" ({', '.join(problems)})"
        with lock:
            echo(line)

    remaining = set(futures)
    try:
        while remaining:
            finished, remaining = wait(remaining, return_when="FIRST_COMPLETED")
            for future in finished:
                collect(future)
    except KeyboardInterrupt:
        # As que não começaram são canceladas; as em andamento terminam
        # interrompidas (o wrapper registra) e entram no histórico.
        outcome.interrupted = True
        pool.shutdown(wait=True, cancel_futures=True)
        for future in futures:
            if future in remaining and future.done() and not future.cancelled():
                collect(future)
        return outcome
    pool.shutdown(wait=True)
    return outcome


def record_session(
    root: Path,
    name: str,
    started: str,
    gem5: Path,
    jobs: int,
    outcome: Outcome,
    validation: dict[str, Any] | None,
    updated: bool,
) -> None:
    """Acrescenta a sessão ao campaign.json (histórico; o estado vem das pastas)."""
    log = read_log(root)
    log["campaign"] = name
    log.setdefault("sessions", []).append(
        {
            "started_at": started,
            "finished_at": now(),
            "jobs": jobs,
            "gem5": str(gem5),
            "gem5_sha256": file_sha256(gem5),
            "project": project_state(),
            "matrix_updated": updated,
            "planned": outcome.planned,
            "skipped": outcome.skipped,
            "executed": len(outcome.executed),
            "completed": len(outcome.executed) - len(outcome.failed),
            "failed": [state.planned.name for state in outcome.failed],
            "interrupted": outcome.interrupted,
            "validation": validation,
        }
    )
    write_json(root / "campaign.json", log)


def run_campaign(
    matrix: Path,
    gem5: Path,
    jobs: int,
    echo: Callable[[str], None],
    output: Path | None = None,
    validate: bool = False,
    update: bool = False,
) -> Outcome:
    """Planeja, (valida) e executa uma campanha, retomando a partir das pastas."""
    campaign = load_campaign(matrix)
    plan = build_plan(campaign, campaign_root(campaign, output), matrix)
    if not plan.runs:
        raise CampaignError("a matriz não gerou nenhuma combinação válida; veja campaign plan")
    check_environment(gem5)
    started = now()
    prepare_folder(plan, matrix, update)
    echo(f"Campanha {campaign.name} em {display(plan.root)}")
    for warning in tree_warnings():
        echo(warning)
    validation = None
    if validate or campaign.validate_first:
        validation = validate_campaign(plan.root, file_sha256(gem5), jobs, echo)
    outcome = run_plan(plan, gem5, jobs, echo)
    record_session(plan.root, campaign.name, started, gem5, jobs, outcome, validation, update)
    return outcome


def load_plan_from(target: Path, output: Path | None = None) -> Plan:
    """Plano de uma campanha a partir da matriz (.yaml) ou da pasta da campanha."""
    if target.is_dir():
        matrix = target / "campaign.yaml"
        if not matrix.is_file():
            raise CampaignError(f"{target} não é a pasta de uma campanha (falta campaign.yaml)")
        campaign = load_campaign(matrix)
        return build_plan(campaign, target.resolve(), matrix)
    campaign = load_campaign(target)
    return build_plan(campaign, campaign_root(campaign, output), target)


def count_by(items: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts
