"""IA-0 (JAJ-112): mide ``analyze_repo`` (el analizador de la ingesta) con LLM reales.

Corre desde ``backend/`` para importar la app:

  cd backend
  ANTHROPIC_API_KEY=... .venv/bin/python ../spikes/ia-0-analizador/run.py \
      --repos /ruta/a/clones --repo node-express-realworld-example-app --provider anthropic --runs 2

* ``--repos``: carpeta con los clones (``git clone --depth 1`` de las URLs de ``reference.json``). El código de
  los repos no se ejecuta: el analizador solo lo lee.
* ``--provider``: ``anthropic`` u ``openai``, con ``ANTHROPIC_API_KEY`` u ``OPENAI_API_KEY``. El modelo sale de
  ``model_for(provider, "extract")`` (``BRANCHPOINT_<PROVIDER>_EXTRACT_MODEL``).
* ``--dry``: un LLM falso que encuentra rutas con grep y las entrega sin pasos. Sirve para probar el script sin
  gastar tokens; sus números no miden nada.

Cada corrida agrega una línea a ``results/runs.jsonl`` con endpoints, componentes, vueltas, tokens, segundos,
costo, recall contra ``reference.json``, endpoints inventados y la revisión automática de 20 pasos al azar
(el archivo existe y la línea está en rango). La forma (``shape``) de esos 20 pasos queda en
``results/sample-<repo>-<provider>-<n>.csv`` para revisarla a mano.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))

from app.agent.loop import AnthropicLLM, Turn, cost_usd, model_for  # noqa: E402
from app.agent.openai_llm import OpenAILLM  # noqa: E402
from app.ingest.analyzer import AnalysisFailed, analyze_repo  # noqa: E402
from app.ingest.build_model import NoEndpoints  # noqa: E402

REFERENCE = json.loads((HERE / "reference.json").read_text())
SAMPLE_STEPS = 20


def norm(endpoint: str) -> str:
    """'GET /articles/{slug}/' y 'GET /api/articles/:slug' quedan comparables: parámetros como {}, sin barra final."""
    method, _, path = endpoint.partition(" ")
    path = re.sub(r"\{[^}]*\}|:[A-Za-z_]\w*|<[^>]*>|\(\?P<[^>]+>[^)]*\)", "{}", path)
    return f"{method.upper()} {path.rstrip('/') or '/'}"


def reference_endpoints(name: str) -> set[str] | int:
    spec = REFERENCE["repos"][name]["endpoints"]
    if isinstance(spec, int):
        return spec
    if spec == "realworld":
        return {norm(e) for e in REFERENCE["realworld"]}
    kind, _, sample = spec.partition(":")
    base = HERE.parents[1] / "backend"
    path = base / ("app/samples" if kind == "from_sample" else "tests/fixtures") / f"{sample}.model.json"
    return {norm(e["id"]) for e in json.loads(path.read_text())["endpoints"]}


def matches(found: set[str], real: set[str]) -> set[str]:
    """Los encontrados que están en la referencia, con o sin el prefijo /api (algunos lo montan afuera)."""
    alt = {e.replace(" /api/", " /", 1) for e in real} | real
    return {e for e in found if e in alt or e.replace(" /", " /api/", 1) in real}


class CountingLLM:
    """Envuelve el LLM para contar vueltas."""

    def __init__(self, llm: Any) -> None:
        self.llm, self.model, self.turns = llm, llm.model, 0

    def complete(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Turn:
        self.turns += 1
        return self.llm.complete(system, messages, tools)


class DryLLM:
    """Sin red: busca decoradores o llamadas de rutas con grep y las entrega sin pasos."""

    model = "dry-run"
    ROUTE = r"(@\w*\.?(get|post|put|delete|patch)\(|router\.(get|post|put|delete|patch)\()"

    def complete(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Turn:
        last = messages[-1]["content"]
        if isinstance(last, str):
            call = {"type": "tool_use", "id": "g", "name": "grep", "input": {"pattern": self.ROUTE}}
            return Turn([call], "tool_use", {"input": 0, "output": 0})
        hits = json.loads(last[0]["content"]).get("hits", [])
        endpoints, seen = [], set()
        for hit in hits:
            file, line, code = hit.split(":", 2)
            m = re.search(r"\.(get|post|put|delete|patch)\(\s*['\"]([^'\"]*)", code)
            if not m:
                continue
            method, path = m.group(1).upper(), "/" + m.group(2).lstrip("/")
            if (method, path) in seen:
                continue
            seen.add((method, path))
            endpoints.append({"method": method, "path": path, "handler": "h", "file": file, "line": int(line),
                              "why": "ruta encontrada con grep"})  # fmt: skip
        if not endpoints:
            return Turn([{"type": "tool_use", "id": "n", "name": "report_no_endpoints", "input": {"reason": "-"}}],
                        "tool_use", {})  # fmt: skip
        arch = {"framework": "dry", "language": "dry", "endpoints": endpoints[:300]}
        return Turn([{"type": "tool_use", "id": "s", "name": "submit_architecture", "input": arch}], "tool_use", {})


def build_llm(provider: str, dry: bool) -> Any:
    if dry:
        return DryLLM()
    import os

    env = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    key = os.environ.get(env, "").strip()
    if not key:
        raise SystemExit(f"Falta {env} (o usa --dry).")
    model = model_for(provider, "extract")
    return OpenAILLM(key, model) if provider == "openai" else AnthropicLLM(key, model)


def check_step(root: Path, file: str, line: int) -> str | None:
    """None si el archivo existe en el repo y la línea está en rango; si no, el problema."""
    path = (root / file).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return "archivo inexistente"
    with path.open(errors="replace") as f:
        lines = sum(1 for _ in f)
    return None if 1 <= line <= lines else f"línea {line} de {lines}"


def run_once(root: Path, name: str, provider: str, dry: bool, n: int) -> dict[str, Any]:
    llm = CountingLLM(build_llm(provider, dry))
    started = time.monotonic()
    out: dict[str, Any] = {"repo": name, "provider": provider, "model": llm.model, "run": n}
    try:
        sub, usage = analyze_repo(root, llm, name)
    except (AnalysisFailed, NoEndpoints) as e:
        out.update(seconds=round(time.monotonic() - started, 1), turns=llm.turns, failed=type(e).__name__, error=str(e))
        return out
    out.update(seconds=round(time.monotonic() - started, 1), turns=llm.turns, usage=usage, failed=None)
    out["cost"] = cost_usd(llm.model, usage) if usage else None
    found = {norm(f"{e.method} {e.path}") for e in sub.endpoints}
    real = reference_endpoints(name)
    out["endpoints"] = len(found)
    out["components"] = sorted(f"{c.role}:{c.technology}" for c in sub.components) if sub.components else []
    if isinstance(real, set):
        hit = matches(found, real)
        out.update(real=len(real), recall=round(len(hit) / len(real), 3), not_in_reference=sorted(found - hit))
    else:
        out.update(real=real, recall=round(min(len(found), real) / real, 3))
    steps = [(e, s) for e in sub.endpoints for s in e.effects]
    rng = random.Random(f"{name}-{provider}-{n}")
    sample = rng.sample(steps, min(SAMPLE_STEPS, len(steps)))
    problems = [p for e, s in sample if (p := check_step(root, s.file, s.line))]
    out["evidence"] = {"sampled": len(sample), "invalid": len(problems), "problems": problems[:5]}
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    with (results / f"sample-{name}-{provider}-{n}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["endpoint", "kind", "shape", "file", "line", "detail", "evidence", "shape_ok (a mano)"])
        for e, s in sample:
            w.writerow([f"{e.method} {e.path}", s.kind, getattr(s, "shape", None), s.file, s.line,
                        getattr(s, "detail", ""), check_step(root, s.file, s.line) or "ok", ""])  # fmt: skip
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repos", type=Path, required=True)
    ap.add_argument("--repo", action="append", help="uno o más repos de reference.json (por defecto, todos)")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    out = HERE / "results" / ("runs-dry.jsonl" if args.dry else "runs.jsonl")
    out.parent.mkdir(exist_ok=True)
    for name in args.repo or list(REFERENCE["repos"]):
        root = args.repos / name
        if not root.is_dir():
            raise SystemExit(f"No está el clon de {name} en {root}.")
        for n in range(1, args.runs + 1):
            result = run_once(root, name, args.provider, args.dry, n)
            print(json.dumps(result, ensure_ascii=False))
            with out.open("a") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
