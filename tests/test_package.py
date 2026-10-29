import hashlib
import json
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from riscvcnnbench.campaign import (
    CampaignError,
    file_sha256,
    prepare_folder,
    run_plan,
    write_json,
)
from riscvcnnbench.cli import app
from riscvcnnbench.package import LICENSE, audit, diff, package
from riscvcnnbench.parser import stats_differences
from test_campaign import FC, SMALL, fake_executor, fake_gem5, matrix, plan_of
from test_runs import ROI_STATS

COMMIT = "abc1234def"
GEM5_COMMIT = "ce03244"


def provenance_executor(
    fail: set[str] | None = None,
    dirty: set[str] | None = None,
    wrong: set[str] | None = None,
    commit: str = COMMIT,
):  # noqa: ANN201
    """O executor falso de test_campaign com a proveniência e a linha RESULT do wrapper."""
    base = fake_executor(fail)

    def run(path: Path, gem5: Path) -> Path:
        run_dir = base(path, gem5)
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        resolved = metadata["experiment"]["resolved"]
        name = resolved["name"]
        metadata.update(
            started_at=f"2026-10-27T14:{len(name):02d}:00+00:00",
            finished_at=f"2026-10-27T15:{len(name):02d}:00+00:00",
            project={"commit": commit, "dirty": name in (dirty or set())},
            gem5_repository={"commit": GEM5_COMMIT, "dirty": False},
            gem5_build={"matches_executable": True},
        )
        (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        mismatches = 3 if name in (wrong or set()) else 0
        (run_dir / "stdout.log").write_text(
            f"RESULT bench=fc variant={resolved['benchmark']['variant']} data=random "
            f"In=512 Out=32 R=1 checksum=0x00ff mismatches={mismatches}\n",
            encoding="utf-8",
        )
        return run_dir

    return run


def campaign(tmp_path: Path, validated: bool = True, **faults: set[str]) -> tuple[Path, Path]:
    """Campanha pequena (4 combinações) já executada; devolve a pasta e o gem5 falso."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = matrix(tmp_path, SMALL)
    plan = plan_of(path)
    prepare_folder(plan, path, update=False)
    gem5 = fake_gem5(tmp_path)
    run_plan(plan, gem5, 2, lambda _: None, provenance_executor(**faults))
    root = tmp_path / "campanha"
    if validated:
        validation = {
            "passed": True,
            "finished_at": "2026-10-27T14:10:00+00:00",
            "project_commit": COMMIT,
            "gem5_sha256": file_sha256(gem5),
        }
        write_json(root / "campaign.json", {"sessions": [], "validations": [validation]})
    return root, gem5


def test_audit_of_a_clean_campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, gem5 = campaign(tmp_path)
    monkeypatch.chdir(tmp_path)

    found = audit(Path("campanha"))  # caminho relativo, como na linha de comando

    assert found.ok
    assert (found.name, found.combinations, found.done, found.extra_runs) == ("pequena", 4, 4, 0)
    assert found.project_commits == {COMMIT: 4}
    assert found.gem5_commits == {GEM5_COMMIT: 4}
    assert found.gem5_sha256 == {file_sha256(gem5): 4}
    assert found.validation is not None and found.validation["passed"]
    assert found.notes == [
        "sem report/runs.csv (rode riscvcnnbench report)",
        "sem figures/ (rode riscvcnnbench plot)",
    ]
    assert found.first_started is not None and found.last_finished is not None
    assert found.first_started < found.last_finished


def test_audit_finds_problems_and_accepts_a_clean_rerun(tmp_path: Path) -> None:
    failed, dirty, wrong = (
        FC.format(*pair) for pair in [("custom", "minor"), ("ref", "minor"), ("custom", "timing")]
    )
    root, gem5 = campaign(tmp_path, validated=False, fail={failed}, dirty={dirty}, wrong={wrong})

    found = audit(root)

    assert not found.ok
    assert found.done == 3
    assert found.problems == [
        f"{dirty}: project.dirty = True",
        f"{wrong}: resultado incorreto (mismatches=3)",
        f"{failed}: falhou (benchmark)",
    ]
    assert found.notes[0] == "sem validação de equivalência aprovada no campaign.json"

    # Refeitas com a árvore limpa, as novas valem e as antigas viram observação.
    plan = plan_of(root / "campaign.yaml")
    for name in (dirty, wrong):
        experiment = root / "experiments" / f"{name}.yaml"
        provenance_executor()(experiment, gem5)
    run_plan(plan, gem5, 2, lambda _: None, provenance_executor())

    found = audit(root)

    assert found.ok
    assert found.extra_runs == 3
    assert found.notes[0] == (
        "3 execução(ões) a mais nas pastas (repetidas ou substituídas), 1 com project.dirty "
        "true; não contam: vale a mais recente concluída"
    )


def test_audit_requires_one_project_commit(tmp_path: Path) -> None:
    root, gem5 = campaign(tmp_path)
    experiment = root / "experiments" / f"{FC.format('ref', 'timing')}.yaml"
    provenance_executor(commit="outro")(experiment, gem5)

    found = audit(root)

    assert found.problems == [f"execuções de commits diferentes do projeto: outro, {COMMIT[:7]}"]
    assert "a validação aprovada é de outro commit do projeto ou outro gem5" not in found.notes


def test_package_contents_and_checksums(tmp_path: Path) -> None:
    root, _ = campaign(tmp_path)
    output = tmp_path / "pacote" / "dados-v1.tar.gz"
    framework = {"commit": "f00", "dirty": False}

    audits = package([root], output, "dados-v1", framework=framework)

    assert [item.done for item in audits] == [4]
    with tarfile.open(output) as archive:
        members = {member.name: member for member in archive.getmembers()}
        content = {
            name: archive.extractfile(member).read()  # type: ignore[union-attr]
            for name, member in members.items()
            if member.isfile()
        }
    assert {name.split("/")[0] for name in members} == {"dados-v1"}
    assert {member.uname for member in members.values()} == {""}
    assert {member.uid for member in members.values()} == {0}
    files = [path for path in root.rglob("*") if path.is_file()]
    expected = {f"dados-v1/campanhas/campanha/{path.relative_to(root)}" for path in files}
    extra = {f"dados-v1/{name}" for name in ("README.md", "LICENSE.txt", "MANIFEST.json")}
    assert set(content) == expected | extra | {"dados-v1/SHA256SUMS"}

    sums = content["dados-v1/SHA256SUMS"].decode().splitlines()
    assert len(sums) == len(content) - 1
    for line in sums:
        digest, name = line.split("  ")
        assert hashlib.sha256(content[f"dados-v1/{name}"]).hexdigest() == digest

    manifest = json.loads(content["dados-v1/MANIFEST.json"])
    assert manifest["license"] == LICENSE == "CC-BY-4.0"
    assert manifest["framework"] == framework
    [summary] = manifest["campaigns"]
    assert (summary["path"], summary["combinations"], summary["done"]) == (
        "campanhas/campanha",
        4,
        4,
    )
    assert summary["project_commits"] == {COMMIT: 4}
    assert summary["problems"] == []
    readme = content["dados-v1/README.md"].decode()
    assert "### `campanhas/campanha/` (campanha `pequena`)" in readme
    assert "- 4 de 4 combinações concluídas" in readme
    assert "commit `f00` do código" in readme
    assert "CC BY 4.0" in content["dados-v1/LICENSE.txt"].decode()

    with pytest.raises(CampaignError, match="já existe"):
        package([root], output, "dados-v1")


def test_package_refuses_problems(tmp_path: Path) -> None:
    root, _ = campaign(tmp_path, dirty={FC.format("ref", "timing")})
    output = tmp_path / "dados.tar.gz"

    with pytest.raises(CampaignError, match="a auditoria achou problemas:\n  pequena: fc_s__ref"):
        package([root], output, "dados")
    assert not output.exists()
    with pytest.raises(CampaignError, match="mesmo nome: campanha"):
        package([root, root], output, "dados", allow_problems=True)

    package([root], output, "dados", allow_problems=True)
    with tarfile.open(output) as archive:
        manifest = json.loads(archive.extractfile("dados/MANIFEST.json").read())  # type: ignore[union-attr]
    assert manifest["campaigns"][0]["problems"] == [
        f"{FC.format('ref', 'timing')}: project.dirty = True"
    ]


def test_cli_audit_and_package(tmp_path: Path) -> None:
    runner = CliRunner()
    root, _ = campaign(tmp_path)

    result = runner.invoke(app, ["campaign", "audit", str(root)])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[:2] == [
        "Campanha pequena: 4 de 4 concluída(s)",
        f"  commit do projeto: {COMMIT[:7]} (4); do fork do gem5: {GEM5_COMMIT} (4)",
    ]
    assert "  validação: aprovada em 2026-10-27T14:10:00+00:00 (commit abc1234)" in result.output
    assert result.output.endswith("\nSem problemas.\n")

    output = tmp_path / "dados-v1.tar.gz"
    result = runner.invoke(app, ["campaign", "package", str(root), "-o", str(output)])
    assert result.exit_code == 0, result.output
    assert "pasta raiz dados-v1/" in result.output
    with tarfile.open(output) as archive:
        assert "dados-v1/README.md" in archive.getnames()

    dirty_root, _ = campaign(tmp_path / "suja", dirty={FC.format("ref", "timing")})
    result = runner.invoke(app, ["campaign", "audit", str(dirty_root)])
    assert result.exit_code == 1
    assert f"1 problema(s):\n  {FC.format('ref', 'timing')}: project.dirty = True" in result.output
    result = runner.invoke(app, ["campaign", "audit", str(tmp_path / "nada")])
    assert result.exit_code == 1
    assert "Erro: pasta não encontrada" in result.output


REF_TIMING, REF_MINOR, CUSTOM_TIMING, CUSTOM_MINOR = (
    FC.format(*pair)
    for pair in [("ref", "timing"), ("ref", "minor"), ("custom", "timing"), ("custom", "minor")]
)
STATS_COMPARED = stats_differences(ROI_STATS, ROI_STATS)[0]


def only_run(root: Path, name: str) -> Path:
    (run_dir,) = (root / "runs" / name).iterdir()
    return run_dir


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_diff_of_a_reproduced_campaign(tmp_path: Path) -> None:
    # A mesma matriz em outra pasta: as chaves são as mesmas, e as execuções, iguais.
    root, _ = campaign(tmp_path / "a")
    reference, _ = campaign(tmp_path / "b")

    found = diff(root, reference)

    assert found.ok
    assert (found.name, found.reference, found.notes) == ("pequena", "pequena", [])
    assert [(m.name, m.status, m.compared, m.differences) for m in found.matches] == [
        (name, "igual", STATS_COMPARED, [])
        for name in (REF_TIMING, REF_MINOR, CUSTOM_TIMING, CUSTOM_MINOR)
    ]


def test_diff_finds_differences(tmp_path: Path) -> None:
    root, _ = campaign(tmp_path / "a", fail={CUSTOM_MINOR})
    reference, _ = campaign(tmp_path / "b")
    stats = only_run(reference, REF_TIMING) / "gem5" / "stats.txt"
    edit(stats, "numCycles                            66214", "numCycles  66215")
    edit(stats, "hostSeconds                                      0.37", "hostSeconds  9.99")
    edit(only_run(reference, REF_MINOR) / "stdout.log", "checksum=0x00ff", "checksum=0x0100")
    metadata_path = only_run(root, CUSTOM_TIMING) / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["original_binary"] = "/workspace/outra/inputs/fc"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    found = diff(root, reference)

    assert not found.ok
    assert [(m.name, m.status, m.differences) for m in found.matches] == [
        (REF_TIMING, "diferente", ["bloco 1, system.cpu.numCycles: 66214 × 66215"]),
        (REF_MINOR, "diferente", ["RESULT checksum: 0x00ff × 0x0100"]),
        (CUSTOM_TIMING, "igual", []),
        (CUSTOM_MINOR, "falhou (benchmark)", []),
    ]
    assert found.notes == [
        "1 combinação(ões) com o caminho do binário de outro comprimento que o da referência: "
        "ele entra na pilha do programa simulado e muda os ciclos (docs/reproducibility.md)"
    ]

    for run_dir in (reference / "runs" / CUSTOM_TIMING).iterdir():
        (run_dir / "metadata.json").unlink()
    assert diff(root, reference).matches[2].status == "sem correspondente"


def test_cli_diff(tmp_path: Path) -> None:
    runner = CliRunner()
    root, _ = campaign(tmp_path / "a")
    reference, _ = campaign(tmp_path / "b")

    result = runner.invoke(app, ["campaign", "diff", str(root), str(reference)])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == f"Campanha pequena ({root}) × pequena ({reference})"
    assert lines[1].split() == ["NOME", "SITUAÇÃO", "ESTATÍSTICAS", "DIFERENÇAS"]
    assert lines[2].split() == [REF_TIMING, "igual", str(STATS_COMPARED), "0"]
    assert result.output.endswith("\n4 combinação(ões): igual: 4.\n")

    stats = only_run(reference, REF_TIMING) / "gem5" / "stats.txt"
    edit(stats, "simInsts                                       115270", "simInsts  115271")
    edit(stats, "simInsts                                       126213", "simInsts  126214")
    edit(stats, "numCycles                            66214", "numCycles  66215")
    edit(stats, "numCycles                            82736", "numCycles  82737")
    result = runner.invoke(app, ["campaign", "diff", str(root), str(reference)])
    assert result.exit_code == 1
    assert "\n4 combinação(ões): diferente: 1, igual: 3.\n" in result.output
    assert result.output.endswith(
        f"\nDiferenças:\n  {REF_TIMING}:\n"
        "    bloco 1, simInsts: 115270 × 115271\n"
        "    bloco 1, system.cpu.numCycles: 66214 × 66215\n"
        "    bloco 2, simInsts: 126213 × 126214\n"
        "    ... e mais 1\n"
    )

    result = runner.invoke(app, ["campaign", "diff", str(root), str(tmp_path / "nada")])
    assert result.exit_code == 1
    assert "Erro: pasta não encontrada" in result.output
