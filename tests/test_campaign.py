import json
import subprocess
import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench import campaign as campaign_module
from riscvcnnbench.campaign import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_INCOMPLETE,
    STATUS_INTERRUPTED,
    STATUS_PENDING,
    STATUS_STALE,
    CampaignError,
    build_plan,
    file_sha256,
    load_campaign,
    prepare_folder,
    record_session,
    run_plan,
    states,
    tree_warnings,
    validate_campaign,
)
from riscvcnnbench.cli import app
from riscvcnnbench.config import PROJECT_ROOT, ConfigError, load_experiment
from riscvcnnbench.runner import new_run_id, resolved_config, results_dir
from test_runs import ROI_STATS

FC = "fc_s__{}__{}__l1-l2"


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def matrix(tmp_path: Path, text: str) -> Path:
    return write(tmp_path / "matrix.yaml", text.replace("OUT", str(tmp_path / "campanha")))


def plan_of(path: Path):  # noqa: ANN201 - Plan
    campaign = load_campaign(path)
    root = campaign.output.dir or path.parent / "campanha"
    return build_plan(campaign, root, path)


SMALL = """\
name: pequena
output:
  dir: OUT
set:
  scenario: l1-l2
groups:
  - name: variantes
    experiments: [fc_s]
    vary:
      benchmark.variant: [ref, custom]
      cpu.model: [timing, minor]
"""


def fake_gem5(tmp_path: Path, content: bytes = b"gem5") -> Path:
    path = tmp_path / f"gem5-{content.decode()}.opt"
    path.write_bytes(content)
    return path


def fake_executor(fail: set[str] | None = None, calls: list[str] | None = None):  # noqa: ANN201
    """Grava uma pasta de execução como a do wrapper, concluída ou falha (benchmark)."""

    def run(path: Path, gem5: Path) -> Path:
        experiment = load_experiment(path)
        if calls is not None:
            calls.append(experiment.name)
        failed = experiment.name in (fail or set())
        run_id = new_run_id()
        run_dir = results_dir(experiment) / run_id
        (run_dir / "gem5").mkdir(parents=True)
        metadata = {
            "schema_version": 5,
            "run_id": run_id,
            "status": "failed" if failed else "completed",
            "failed_step": "simulation" if failed else None,
            "exit_code": 2 if failed else 0,
            "program_exit_code": 2 if failed else 0,
            "gem5_sha256": file_sha256(gem5),
            "experiment": {"resolved": resolved_config(experiment)},
        }
        (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        (run_dir / "stdout.log").write_text("", encoding="utf-8")
        (run_dir / "stderr.log").write_text(
            "ERRO: argumento inválido\n" if failed else "", encoding="utf-8"
        )
        (run_dir / "gem5" / "stats.txt").write_text(ROI_STATS, encoding="utf-8")
        return run_dir

    return run


def test_example_matrix() -> None:
    path = PROJECT_ROOT / "campaigns/exemplo.yaml"
    plan = build_plan(load_campaign(path), Path("/tmp/x"), path)

    assert [run.name for run in plan.runs] == [
        FC.format("ref", "timing"),
        FC.format("ref", "minor"),
        FC.format("custom", "timing"),
        FC.format("custom", "minor"),
        FC.format("custom", "minor") + "__lat6",
        FC.format("rvv", "timing"),
        FC.format("rvv", "minor"),
        FC.format("ref", "minor") + "__O3",
        FC.format("custom", "minor") + "__O3",
    ]
    # As -O2 da minor também são do grupo de compilador; não rodam duas vezes.
    assert plan.runs[1].groups == ["variantes", "compilador"]
    assert len(plan.duplicates) == 7 and plan.invalid == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("name: t\ngrups: []\n", "linha 2: grups: campo desconhecido; você quis dizer 'groups'?"),
        (
            "name: t\ngroups:\n  - name: g\n    experiments: [fc_s]\n    varyy: {}\n",
            "linha 5: groups.0.varyy: campo desconhecido; você quis dizer 'vary'?",
        ),
        (
            "name: t\ngroups:\n  - name: g\n    experiments: [fc_s]\n    vary:\n"
            "      cpu.modle: [minor]\n",
            "linha 6: groups.0.vary.cpu.modle: campo 'cpu.modle' não existe no experimento; "
            "você quis dizer 'cpu.model'?",
        ),
        (
            "name: t\nset:\n  benchmark.args: [1]\ngroups:\n  - name: g\n    experiments: [fc_s]\n",
            "linha 3: set.benchmark.args: 'benchmark.args' é definido pela campanha; a operação "
            "e os argumentos vêm do experimento base",
        ),
        (
            "name: t\ngroups:\n  - name: g\n    experiments: [fc_ss]\n",
            "linha 4: groups.0.experiments.0: experimento 'fc_ss' não encontrado; você quis "
            "dizer 'fc_s'?",
        ),
        (
            "name: t\ngroups:\n  - name: g\n    experiments: [fc_s]\n    vary:\n"
            "      cpu.model: minor\n",
            "linha 6: groups.0.vary.cpu.model: deve ser uma lista",
        ),
        (
            "name: t\ngroups:\n  - name: g\n    experiments: [fc_s]\n    vary:\n"
            "      cpu.model: []\n",
            "linha 6: groups.0.vary.cpu.model: deve ter pelo menos 1 item(ns)",
        ),
        (
            "name: t\ngroups:\n  - name: g\n    experiments: []\n",
            "linha 4: groups.0.experiments: deve ter pelo menos 1 item(ns)",
        ),
        (
            "name: t\ngroups:\n  - {name: g, experiments: [fc_s]}\n"
            "  - {name: g, experiments: [fc_l]}\n",
            "linha 2: groups: nomes de grupo repetidos: g",
        ),
        (
            "name: t\nvalidate: talvez\ngroups:\n  - {name: g, experiments: [fc_s]}\n",
            "linha 2: validate: deve ser true ou false, mas recebeu 'talvez'",
        ),
        ("", "arquivo vazio; o mínimo é name e groups"),
    ],
)
def test_invalid_matrix_message(tmp_path: Path, text: str, expected: str) -> None:
    with pytest.raises(ConfigError) as error:
        load_campaign(write(tmp_path / "m.yaml", text))

    assert expected in str(error.value)


def test_irrelevant_fields_do_not_multiply_runs(tmp_path: Path) -> None:
    path = matrix(
        tmp_path,
        """\
name: t
set: {scenario: l1-l2}
groups:
  - name: g
    experiments: [fc_s]
    vary:
      benchmark.variant: [ref, custom, rvv]
      cpu.model: [atomic, minor]
      cpu.custom_latency: [3, 6]
      cpu.vlen: [256, 512]
""",
    )

    plan = plan_of(path)

    # Latência só na custom e fora da atomic; VLEN só na rvv: 24 → 9.
    assert [run.name.removeprefix("fc_s__") for run in plan.runs] == [
        "ref__atomic__l1-l2",
        "ref__minor__l1-l2",
        "custom__atomic__l1-l2",
        "custom__minor__l1-l2",
        "custom__minor__l1-l2__lat6",
        "rvv__atomic__l1-l2",
        "rvv__atomic__l1-l2__vlen512",
        "rvv__minor__l1-l2",
        "rvv__minor__l1-l2__vlen512",
    ]
    assert len(plan.duplicates) == 15
    ignored = {tuple(item["ignored"]) for item in plan.duplicates}
    assert ("cpu.custom_latency",) in ignored and ("cpu.vlen",) in ignored


def test_custom_units_names_and_normalization(tmp_path: Path) -> None:
    """RCB-33: unidades e pipeline só na custom fora da atomic e da timing; na minor,
    1 unidade é o padrão."""
    path = matrix(
        tmp_path,
        """\
name: t
set: {scenario: l1-l2}
groups:
  - name: g
    experiments: [fc_s]
    vary:
      benchmark.variant: [ref, custom]
      cpu.model: [timing, minor, o3-edge]
      cpu.custom_units: [null, 1, 2]
      cpu.custom_pipelined: [true, false]
""",
    )

    plan = plan_of(path)

    assert [run.name.removeprefix("fc_s__") for run in plan.runs] == [
        "ref__timing__l1-l2",
        "ref__minor__l1-l2",
        "ref__o3-edge__l1-l2",
        "custom__timing__l1-l2",
        "custom__minor__l1-l2",
        "custom__minor__l1-l2__np",
        "custom__minor__l1-l2__2u",
        "custom__minor__l1-l2__2u-np",
        "custom__o3-edge__l1-l2",
        "custom__o3-edge__l1-l2__np",
        "custom__o3-edge__l1-l2__1u",
        "custom__o3-edge__l1-l2__1u-np",
        "custom__o3-edge__l1-l2__2u",
        "custom__o3-edge__l1-l2__2u-np",
    ]


def test_invalid_combinations_are_listed(tmp_path: Path) -> None:
    path = matrix(
        tmp_path,
        """\
name: t
groups:
  - name: g
    experiments: [fc_s]
    set: {cpu.model: timing, benchmark.variant: custom}
    vary:
      scenario: [sem-cache, l1-l2]
      benchmark.cache_state: [warm, cold]
""",
    )

    plan = plan_of(path)

    assert [run.name.removeprefix("fc_s__custom__timing__") for run in plan.runs] == [
        "sem-cache",
        "l1-l2",
        "l1-l2-cold",
    ]
    assert plan.invalid == [
        {
            "base": "fc_s",
            "group": "g",
            "values": {"scenario": "sem-cache", "benchmark.cache_state": "cold"},
            "problems": [
                "benchmark.cache_state: 'cold' esvazia as caches no início da ROI, mas o "
                "experimento não tem caches; configure cache ou use um scenario com caches"
            ],
        }
    ]


def test_equal_names_get_part_of_the_key(tmp_path: Path) -> None:
    path = matrix(
        tmp_path,
        """\
name: t
set: {cache.l1i.size: 32KiB, cache.l1d.size: 32KiB}
groups:
  - name: g
    experiments: [fc_s]
    vary:
      cache.l1d.assoc: [4, 8]
""",
    )

    plan = plan_of(path)

    # A associatividade não aparece no nome; a chave desempata.
    names = [run.name for run in plan.runs]
    assert len(set(names)) == 2
    for run in plan.runs:
        assert run.name == f"fc_s__ref__atomic__l1i32KiB-l1d32KiB-simple__{run.key[:6]}"


def test_campaign_folder(tmp_path: Path) -> None:
    path = matrix(tmp_path, SMALL)
    plan = plan_of(path)

    prepare_folder(plan, path, update=False)

    root = tmp_path / "campanha"
    assert (root / "campaign.yaml").read_text(encoding="utf-8") == path.read_text(encoding="utf-8")
    document = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    assert [run["name"] for run in document["runs"]] == [run.name for run in plan.runs]
    for run in plan.runs:
        experiment = load_experiment(root / run.path)
        assert experiment.name == run.name
        assert experiment.results_dir == root / "runs" / run.name
        assert experiment.scenario == "l1-l2"

    # Outra matriz na mesma pasta só com --update.
    write(path, SMALL.replace("OUT", str(root)).replace("minor]", "o3-edge]"))
    with pytest.raises(CampaignError, match="a matriz mudou"):
        prepare_folder(plan_of(path), path, update=False)
    prepare_folder(plan_of(path), path, update=True)


def test_run_resume_and_failures(tmp_path: Path) -> None:
    path = matrix(tmp_path, SMALL)
    plan = plan_of(path)
    prepare_folder(plan, path, update=False)
    gem5 = fake_gem5(tmp_path)
    failing = FC.format("custom", "minor")
    calls: list[str] = []

    first = run_plan(plan, gem5, 2, lambda _: None, fake_executor({failing}, calls))

    assert (first.planned, first.skipped, len(first.executed)) == (4, 0, 4)
    assert [state.planned.name for state in first.failed] == [failing]
    found = {state.planned.name: state for state in states(plan, file_sha256(gem5))}
    assert found[failing].status == STATUS_FAILED
    assert found[failing].label() == "falhou (benchmark)"
    assert found[FC.format("ref", "timing")].status == STATUS_DONE
    assert found[FC.format("ref", "timing")].cells()[:2] == ["115270", "66214"]

    # Retomada: só a que falhou roda de novo, e as tentativas se acumulam.
    calls.clear()
    second = run_plan(plan, gem5, 2, lambda _: None, fake_executor(set(), calls))
    assert (second.skipped, calls) == (3, [failing])
    assert {state.attempts for state in states(plan, file_sha256(gem5))} == {1, 2}

    # Outro executável do gem5: as concluídas ficam desatualizadas e rodam de novo.
    other = fake_gem5(tmp_path, b"outro")
    assert {state.status for state in states(plan, file_sha256(other))} == {STATUS_STALE}
    calls.clear()
    run_plan(plan, other, 2, lambda _: None, fake_executor(set(), calls))
    assert sorted(calls) == sorted(run.name for run in plan.runs)


def test_run_states_from_folders(tmp_path: Path) -> None:
    path = matrix(tmp_path, SMALL)
    plan = plan_of(path)
    prepare_folder(plan, path, update=False)
    gem5 = fake_gem5(tmp_path)
    run_plan(plan, gem5, 1, lambda _: None, fake_executor())
    first, second, third, fourth = plan.runs

    def set_status(name: str, status: str, **fields: object) -> None:
        (meta,) = (plan.root / "runs" / name).rglob("metadata.json")
        content = json.loads(meta.read_text(encoding="utf-8"))
        meta.write_text(json.dumps({**content, "status": status, **fields}), encoding="utf-8")

    set_status(first.name, "interrupted")
    set_status(second.name, "running")
    # Uma pasta com outra configuração sob o mesmo nome é ignorada.
    (meta,) = (plan.root / "runs" / third.name).rglob("metadata.json")
    content = json.loads(meta.read_text(encoding="utf-8"))
    content["experiment"]["resolved"]["cpu"]["clock"] = "2GHz"
    meta.write_text(json.dumps(content), encoding="utf-8")

    found = [state.status for state in states(plan, file_sha256(gem5))]
    assert found == [STATUS_INTERRUPTED, STATUS_INCOMPLETE, STATUS_PENDING, STATUS_DONE]

    # SIGINT só no gem5: falha com a linha "Simulação interrompida" também conta como interrompida.
    set_status(fourth.name, "failed", failed_step="simulation", exit_code=130)
    (stdout,) = (plan.root / "runs" / fourth.name).rglob("stdout.log")
    stdout.write_text("Simulação interrompida no tick 7: user interrupt received\n", "utf-8")
    assert states(plan, file_sha256(gem5))[3].status == STATUS_INTERRUPTED


def test_jobs_run_in_parallel(tmp_path: Path) -> None:
    path = matrix(tmp_path, SMALL)
    plan = plan_of(path)
    prepare_folder(plan, path, update=False)
    lock = threading.Lock()
    active, peak = 0, 0
    inner = fake_executor()

    def slow(path: Path, gem5: Path) -> Path:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.2)
        with lock:
            active -= 1
        return inner(path, gem5)

    run_plan(plan, fake_gem5(tmp_path), 3, lambda _: None, slow)

    assert peak == 3


def test_validation_is_reused_only_for_the_same_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "campanha"
    root.mkdir()
    project = {"commit": "abc", "dirty": False}
    monkeypatch.setattr(campaign_module, "project_state", lambda: project)
    calls: list[int] = []

    def passes(_root: Path, jobs: int) -> int:
        calls.append(jobs)
        return 0

    record = validate_campaign(root, "sha", 4, lambda _: None, passes)
    assert record["passed"] and calls == [4]
    validate_campaign(root, "sha", 4, lambda _: None, passes)
    assert calls == [4]  # mesma validação reaproveitada
    validate_campaign(root, "outro", 4, lambda _: None, passes)
    assert calls == [4, 4]  # outro gem5
    project["dirty"] = True
    validate_campaign(root, "sha", 4, lambda _: None, passes)
    assert calls == [4, 4, 4]  # mudanças não commitadas: valida de novo

    with pytest.raises(CampaignError, match="a validação falhou"):
        validate_campaign(root, "sha", 4, lambda _: None, lambda _root, _jobs: 1)
    log = json.loads((root / "campaign.json").read_text(encoding="utf-8"))
    assert [item["passed"] for item in log["validations"]] == [True, True, True, False]


def test_session_log(tmp_path: Path) -> None:
    path = matrix(tmp_path, SMALL)
    plan = plan_of(path)
    prepare_folder(plan, path, update=False)
    gem5 = fake_gem5(tmp_path)
    outcome = run_plan(plan, gem5, 2, lambda _: None, fake_executor({plan.runs[0].name}))

    record_session(plan.root, "pequena", "2026-10-26T00:00:00+00:00", gem5, 2, outcome, None, False)

    log = json.loads((plan.root / "campaign.json").read_text(encoding="utf-8"))
    (session,) = log["sessions"]
    assert log["campaign"] == "pequena"
    assert (session["planned"], session["executed"], session["completed"]) == (4, 4, 3)
    assert session["failed"] == [plan.runs[0].name]
    assert session["gem5_sha256"] == file_sha256(gem5) and session["jobs"] == 2


def test_cli_plan(tmp_path: Path) -> None:
    path = matrix(tmp_path, SMALL)

    text = CliRunner().invoke(app, ["campaign", "plan", str(path)])
    document = CliRunner().invoke(app, ["campaign", "plan", str(path), "--json"])

    assert text.exit_code == 0, text.output
    lines = text.stdout.splitlines()
    assert lines[0] == "Campanha pequena: 4 execução(ões) únicas"
    assert "  grupo variantes: 4 combinação(ões), 4 nova(s)" in lines
    assert any(line.startswith(FC.format("custom", "minor")) for line in lines)
    assert len(json.loads(document.stdout)["runs"]) == 4


def test_cli_run_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = matrix(tmp_path, SMALL)
    gem5 = fake_gem5(tmp_path)
    failing = FC.format("custom", "minor")
    monkeypatch.setattr(campaign_module, "check_environment", lambda _gem5: None)
    monkeypatch.setattr(campaign_module, "execute_planned", fake_executor({failing}))
    runner = CliRunner()

    run = runner.invoke(app, ["campaign", "run", str(path), "-j", "2", "--gem5", str(gem5)])
    status = runner.invoke(app, ["campaign", "status", str(path), "--gem5", str(gem5)])
    document = runner.invoke(
        app, ["campaign", "status", str(tmp_path / "campanha"), "--gem5", str(gem5), "--json"]
    )

    assert run.exit_code == 1, run.output
    assert "4 combinação(ões): 0 já concluída(s), 4 a executar com 2 tarefa(s)" in run.stdout
    assert f"{failing}: falhou (benchmark)" in run.stdout
    assert (
        "Sessão: 0 já concluída(s), 4 executada(s), 3 concluída(s), 1 com problema." in run.stdout
    )
    assert status.exit_code == 0, status.output
    assert "4 combinação(ões): concluída: 3, falhou: 1." in status.stdout
    assert any(line.startswith(f"  {failing}: ") for line in status.stdout.splitlines())
    rows = {row["name"]: row for row in json.loads(document.stdout)}
    assert rows[failing]["diagnosis"] == "benchmark"
    assert rows[FC.format("ref", "timing")]["insts"] == "115270"

    # Retomada pela CLI: as concluídas não rodam de novo.
    monkeypatch.setattr(campaign_module, "execute_planned", fake_executor())
    again = runner.invoke(app, ["campaign", "run", str(path), "--gem5", str(gem5)])
    assert again.exit_code == 0, again.output
    assert "4 combinação(ões): 3 já concluída(s), 1 a executar" in again.stdout


def test_cli_campaign_errors(tmp_path: Path) -> None:
    runner = CliRunner()

    missing = runner.invoke(app, ["campaign", "plan", str(tmp_path / "nao.yaml")])
    not_campaign = runner.invoke(app, ["campaign", "status", str(tmp_path)])

    assert missing.exit_code == 1 and "arquivo não encontrado" in missing.stderr
    assert not_campaign.exit_code == 1
    assert "não é a pasta de uma campanha (falta campaign.yaml)" in not_campaign.stderr


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=teste", "-c", "user.email=teste@exemplo", *args],
        check=True,
        capture_output=True,
    )


def repository(path: Path, files: dict[str, str]) -> Path:
    """Repositório Git temporário com `files` já commitados."""
    path.mkdir(parents=True)
    git(path, "init", "-q")
    for name, text in files.items():
        write(path / name, text)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "inicial")
    return path


def test_tree_warnings_with_a_temporary_repository(tmp_path: Path) -> None:
    root = repository(tmp_path / "projeto", {"a.txt": "a", ".gitignore": "third_party/\n"})
    gem5 = repository(root / "third_party" / "gem5", {"SConstruct": "x"})

    assert tree_warnings(root) == []
    assert tree_warnings(tmp_path / "sem-git") == []

    write(root / "a.txt", "b")
    write(root / "novo.txt", "c")
    [warning] = tree_warnings(root)
    assert warning == (
        "Aviso: o projeto tem 2 mudança(s) não commitada(s) (M a.txt, ?? novo.txt). As execuções "
        "vão sair com project.dirty: true e não valem como resultado (campaign audit). Faça o "
        "commit antes e não altere a árvore durante a campanha; rascunhos ficam em build/."
    )
    for name in ("b.txt", "c.txt"):
        write(root / name, name)
    assert "(M a.txt, ?? b.txt, ?? c.txt e mais 1)" in tree_warnings(root)[0]

    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "limpa")
    write(gem5 / "SConstruct", "y")
    [warning] = tree_warnings(root)
    assert warning.startswith(
        "Aviso: o submódulo do gem5 (third_party/gem5) tem 1 mudança(s) não commitada(s) "
        "(M SConstruct). As execuções vão sair com gem5_repository.dirty: true"
    )


def provenance_executor(dirty: set[str], other_gem5: set[str]):  # noqa: ANN201
    """O executor falso com a proveniência que o wrapper grava."""
    base = fake_executor()

    def run(path: Path, gem5: Path) -> Path:
        run_dir = base(path, gem5)
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        name = metadata["experiment"]["resolved"]["name"]
        metadata["project"] = {"commit": "abc", "dirty": name in dirty}
        metadata["gem5_repository"] = {"commit": "def", "dirty": False}
        metadata["gem5_build"] = {"matches_executable": name not in other_gem5}
        (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        return run_dir

    return run


def test_cli_warns_about_a_dirty_tree_and_dirty_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = matrix(tmp_path, SMALL)
    gem5 = fake_gem5(tmp_path)
    root = repository(tmp_path / "projeto", {"a.txt": "a"})
    dirty, other = FC.format("ref", "timing"), FC.format("custom", "minor")
    monkeypatch.setattr(campaign_module, "check_environment", lambda _gem5: None)
    monkeypatch.setattr(campaign_module, "tree_warnings", lambda: tree_warnings(root))
    monkeypatch.setattr(campaign_module, "execute_planned", provenance_executor({dirty}, {other}))
    runner = CliRunner()

    # Árvore limpa: sem aviso no início.
    clean = runner.invoke(app, ["campaign", "run", str(path), "-j", "1", "--gem5", str(gem5)])
    assert clean.exit_code == 0, clean.output
    assert "o projeto tem" not in clean.output
    # Mas as execuções sujas aparecem na linha de cada uma e no fim da sessão.
    assert f"{dirty}: concluída — 115270 instruções, 66214 ciclos, IPC" in clean.stdout
    assert any(
        line.startswith("[") and dirty in line and line.endswith("(project.dirty: true)")
        for line in clean.stdout.splitlines()
    )
    assert any(
        other in line and line.endswith("(gem5_build.matches_executable: false)")
        for line in clean.stdout.splitlines()
    )
    assert (
        "Aviso: 2 concluída(s) nesta sessão com a árvore suja ou outro executável do gem5; elas "
        "não valem como resultado." in clean.stderr
    )

    status = runner.invoke(app, ["campaign", "status", str(path), "--gem5", str(gem5)])
    assert status.exit_code == 0, status.output
    lines = status.stdout.splitlines()
    start = lines.index("Concluídas que não valem como resultado: 2")
    assert lines[start + 1].startswith(f"  {dirty}: project.dirty: true (")
    assert lines[start + 2].startswith(f"  {other}: gem5_build.matches_executable: false (")
    assert lines[start + 3].startswith("Para refazer com a árvore limpa: riscvcnnbench run ")
    document = runner.invoke(app, ["campaign", "status", str(path), "--gem5", str(gem5), "--json"])
    rows = {row["name"]: row for row in json.loads(document.stdout)}
    assert rows[dirty]["provenance"] == ["project.dirty: true"]
    assert rows[other]["provenance"] == ["gem5_build.matches_executable: false"]
    assert rows[FC.format("ref", "minor")]["provenance"] == []

    # Árvore suja: o aviso aparece antes de executar (aqui, nada a executar).
    write(root / "a.txt", "b")
    again = runner.invoke(app, ["campaign", "run", str(path), "--gem5", str(gem5)])
    assert again.exit_code == 0, again.output
    assert "Aviso: o projeto tem 1 mudança(s) não commitada(s) (M a.txt)." in again.stdout
