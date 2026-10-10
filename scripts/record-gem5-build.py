"""Registra de qual revisão do gem5 o executável foi compilado.

Grava <gem5>.build-info.json ao lado do executável. O run-gem5.py compara o
hash registrado com o executável usado para detectar builds desatualizados.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from provenance import build_info_path, gem5_version, git_info, save_git_diff, sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gem5", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()

    gem5 = args.gem5.resolve()
    repo = args.repo.resolve()
    if not gem5.is_file():
        parser.error(f"gem5 não encontrado: {gem5}")

    output = build_info_path(gem5)
    diff_path = gem5.with_name(gem5.name + ".build.diff")
    diff_path.unlink(missing_ok=True)

    info = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "gem5_executable": str(gem5),
        "gem5_sha256": sha256(gem5),
        "gem5_version": gem5_version(gem5),
        "repository": git_info(repo),
        "diff": diff_path.name if save_git_diff(repo, diff_path) else None,
    }
    output.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Informações do build: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
