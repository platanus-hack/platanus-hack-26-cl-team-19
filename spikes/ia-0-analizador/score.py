"""Puntúa entregas de submit_architecture contra reference.json (IA-0), sin llamar a ningún LLM.

  cd backend && .venv/bin/python ../spikes/ia-0-analizador/score.py --repos ~/ia0-repos claude-cli/*.json

Por entrega: si pasa el schema, endpoints encontrados / reales, endpoints que no están en la referencia, y la
evidencia de TODOS los endpoints, pasos y componentes (no una muestra) con check_evidence de IA-4 (desde la
rama de IA-4; con la corrección que salió de esta medición).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from app.ingest.ai_graph import ArchitectureSubmission, check_evidence  # noqa: E402

from run import matches, norm, reference_endpoints  # noqa: E402


def score(repo: str, root: Path, arch: dict) -> dict:
    sub = ArchitectureSubmission.model_validate({**arch, "repo": repo})
    found = {norm(f"{e.method} {e.path}") for e in sub.endpoints}
    real = reference_endpoints(repo)
    hit = matches(found, real)
    checked = sum(1 + len(e.effects) + sum(len(s.on_miss or []) for s in e.effects) for e in sub.endpoints)
    checked += sum(1 + len(j.effects) for j in sub.jobs) + len(sub.components) + len(sub.observations)
    problems = check_evidence(sub, root)
    return {
        "repo": repo,
        "endpoints": len(found),
        "real": len(real),
        "recall": round(len(hit) / len(real), 3),
        "missing": sorted(real - hit),
        "not_in_reference": sorted(found - hit),
        "steps": sum(len(e.effects) for e in sub.endpoints),
        "evidence_checked": checked,
        "evidence_valid": round(1 - len(problems) / checked, 3) if checked else None,
        "evidence_problems": problems,
        "components": [f"{c.role}:{c.technology}" for c in sub.components],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", type=Path, required=True)
    ap.add_argument("submissions", nargs="+", type=Path)
    args = ap.parse_args()
    for path in args.submissions:
        repo = path.stem
        print(json.dumps(score(repo, args.repos / repo, json.loads(path.read_text())), ensure_ascii=False))


if __name__ == "__main__":
    main()
