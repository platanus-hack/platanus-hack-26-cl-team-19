"""Puntúa entregas de submit_architecture contra reference.json (IA-0), sin llamar a ningún LLM.

  cd backend && .venv/bin/python ../spikes/ia-0-analizador/score.py --repos ~/ia0-repos claude-cli/*.json

Por entrega: si pasa el schema, endpoints encontrados / reales, endpoints que no están en la referencia, y la
evidencia de TODOS los endpoints y pasos (no una muestra): el archivo existe en el repo, la línea está en rango
y, en los endpoints, algún segmento fijo de la ruta o el nombre de un parámetro aparece a ±30 líneas de la línea
citada (la regla de check_evidence de IA-4 con la corrección que salió de esta medición).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from app.ingest.ai_graph import ArchitectureSubmission  # noqa: E402

from run import matches, norm, reference_endpoints  # noqa: E402

WINDOW = 30


def lines_of(root: Path, file: str) -> list[str] | None:
    path = (root / file).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return None
    return path.read_text(errors="replace").splitlines()


def tokens(path: str) -> list[str]:
    """Lo que tiene que aparecer cerca de la línea citada: algún segmento fijo de la ruta o el nombre de un
    parámetro. Un decorador como @router.delete("/{id}") solo trae el parámetro: el segmento fijo viene del
    prefix del router, en otra parte del archivo o en otro archivo."""
    out = []
    for part in path.split("/"):
        m = re.match(r"^(?:\{(\w+)[^}]*\}|:(\w+)|<(?:\w+:)?(\w+)>)$", part)
        if m:
            out.append(next(g for g in m.groups() if g))
        elif part:
            out.append(part)
    return out


def score(repo: str, root: Path, arch: dict) -> dict:
    sub = ArchitectureSubmission.model_validate({**arch, "repo": repo})
    found = {norm(f"{e.method} {e.path}") for e in sub.endpoints}
    real = reference_endpoints(repo)
    hit = matches(found, real)
    checked, problems = 0, []
    for e in sub.endpoints:
        items = [(f"{e.method} {e.path}", e, e.path), *((f"{e.method} {e.path} paso", s, None) for s in e.effects)]
        for label, item, path in items:
            checked += 1
            lines = lines_of(root, item.file)
            if lines is None:
                problems.append(f"{label}: {item.file} no existe")
            elif item.line > len(lines):
                problems.append(f"{label}: {item.file}:{item.line} fuera de rango ({len(lines)})")
            elif path and (wanted := tokens(path)):
                near = lines[max(0, item.line - 1 - WINDOW) : item.line + WINDOW]
                if not any(tok in text for tok in wanted for text in near):
                    problems.append(f"{label}: ninguna parte de la ruta aparece cerca de {item.file}:{item.line}")
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
