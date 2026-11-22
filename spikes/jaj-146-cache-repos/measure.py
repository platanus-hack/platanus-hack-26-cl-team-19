"""JAJ-146 · Dónde se va el tiempo de una ingesta con el LLM real, y cuánto bajan las variantes.

Reproduce ``model_from_tarball`` (backend/app/github/ingestion.py) fase por fase sobre repos públicos de
IA-0 y cronometra la descarga, la extracción, cada ``LLM.complete``, el escaneo IaC y el armado del
modelo. Puntúa la entrega con el comparador de IA-0 (endpoints contra la referencia y evidencia).

Usa la ``ANTHROPIC_API_KEY`` de backend/.env. Sin opciones, la misma llamada que el backend
(``AnthropicLLM``: thinking adaptativo, effort por defecto del modelo).

    backend/.venv/bin/python spikes/jaj-146-cache-repos/measure.py --repos fastapi express django
    backend/.venv/bin/python spikes/jaj-146-cache-repos/measure.py --model claude-sonnet-5-5 --effort medium
    backend/.venv/bin/python spikes/jaj-146-cache-repos/measure.py --fast

Cada línea de stdout es un JSON con una corrida. El código descargado se trata como datos.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "spikes" / "ia-0-analizador"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

from app.agent.loop import MAX_TOKENS, AnthropicLLM, Turn, model_for, with_cache_breakpoint  # noqa: E402
from app.github.ingestion import extract_tarball  # noqa: E402
from app.ingest.ai_graph import build_from_ai  # noqa: E402
from app.ingest.analyzer import analyze_repo  # noqa: E402
from app.ingest.iac import scan_deployment  # noqa: E402
from score import score  # noqa: E402

REPOS = {  # commits fijados en spikes/ia-0-analizador/reference.json
    "fastapi": ("nsidnev/fastapi-realworld-example-app", "029eb77"),
    "express": ("gothinkster/node-express-realworld-example-app", "30b68e1"),
    "django": ("gothinkster/django-realworld-example-app", "29c9d42"),
    "template": ("fastapi/full-stack-fastapi-template", "77e550a"),
}

# US$ por millón de tokens: entrada, salida, lectura de caché, escritura de caché (×1,25 la entrada).
# Precios de la API de Anthropic al 2026-11-03; fast mode de Opus 5.5 cobra el doble.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


def cost(model: str, usage: dict, fast: bool) -> float | None:
    if model not in PRICES:
        return None
    p_in, p_out, p_read, p_write = (p * (2 if fast else 1) for p in PRICES[model])
    total = (
        usage.get("input", 0) * p_in
        + usage.get("output", 0) * p_out
        + usage.get("cache_read", 0) * p_read
        + usage.get("cache_write", 0) * p_write
    )
    return round(total / 1e6, 4)


class VariantLLM(AnthropicLLM):
    """La llamada de ``AnthropicLLM`` con effort y fast mode opcionales, cronometrada por vuelta."""

    def __init__(self, model: str, effort: str | None, fast: bool) -> None:
        super().__init__(model=model)
        self.effort, self.fast = effort, fast
        self.calls: list[dict] = []

    def complete(self, system, messages, tools):
        extra: dict = {}
        if self.effort:
            extra["output_config"] = {"effort": self.effort}
        if self.fast:
            extra["speed"] = "fast"
        t = time.perf_counter()
        with self._client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=system,
            tools=tools,
            messages=with_cache_breakpoint(messages),
            **extra,
        ) as stream:
            msg = stream.get_final_message()
        u = msg.usage
        turn = Turn(
            content=[b.model_dump(mode="json", exclude_none=True) for b in msg.content],
            stop_reason=msg.stop_reason,
            usage={
                "input": u.input_tokens,
                "output": u.output_tokens,
                "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
            },
        )
        tools_used = [b.get("name") for b in turn.content if b.get("type") == "tool_use"]
        speed = getattr(u, "speed", None)
        self.calls.append({"ms": round((time.perf_counter() - t) * 1000), "tools": tools_used, "speed": speed, **turn.usage})
        return turn


def ms(t: float) -> float:
    return round((time.perf_counter() - t) * 1000, 1)


def measure(key: str, model: str, effort: str | None, fast: bool) -> dict:
    full_name, commit = REPOS[key]
    t0 = time.perf_counter()
    with urllib.request.urlopen(f"https://codeload.github.com/{full_name}/tar.gz/{commit}", timeout=60) as resp:
        data = resp.read()
    download_ms = ms(t0)

    llm = VariantLLM(model, effort, fast)
    with tempfile.TemporaryDirectory(prefix="jaj146-") as tmp:
        t = time.perf_counter()
        root = extract_tarball(data, Path(tmp)).resolve()
        extract_ms = ms(t)
        t = time.perf_counter()
        try:
            result = analyze_repo(root, llm, full_name, commit)
        except Exception as e:  # noqa: BLE001 - una variante que falla también es un resultado
            return {"repo": key, "model": model, "effort": effort, "fast": fast, "error": f"{type(e).__name__}: {e}",
                    "llm_ms": sum(c["ms"] for c in llm.calls), "calls": llm.calls}  # fmt: skip
        analyze_ms = ms(t)
        t = time.perf_counter()
        iac = scan_deployment(root).to_dict()
        iac_ms = ms(t)
        t = time.perf_counter()
        model_json = build_from_ai(result.sub, {}, via="ingesta", iac=iac, root=root)
        build_ms = ms(t)
        quality = score(full_name.split("/", 1)[1], root, result.sub.model_dump(mode="json", exclude={"repo"}))
    llm_ms = sum(c["ms"] for c in llm.calls)
    return {
        "repo": key,
        "commit": commit,
        "model": model,
        "effort": effort,
        "fast": fast,
        "tarball_kib": round(len(data) / 1024, 1),
        "download_ms": download_ms,
        "extract_ms": extract_ms,
        "llm_ms": llm_ms,
        "analyzer_local_ms": round(analyze_ms - llm_ms, 1),
        "iac_ms": iac_ms,
        "build_ms": build_ms,
        "total_ms": ms(t0),
        "steps": result.steps,
        "calls": llm.calls,
        "usage": result.usage,
        "cost_usd": cost(model, result.usage, fast),
        "endpoints": len(model_json["endpoints"]),
        "dropped": len(result.dropped),
        "recall": quality["recall"],
        "real": quality["real"],
        "missing": quality["missing"],
        "not_in_reference": quality["not_in_reference"],
        "effect_steps": quality["steps"],
        "evidence_valid": quality["evidence_valid"],
        "components": quality["components"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos", nargs="+", default=["fastapi", "express", "django"], choices=sorted(REPOS))
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--model", help="Por defecto, el modelo de extracción del backend")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--fast", action="store_true", help="Fast mode (solo Opus 5.5, cobra el doble)")
    args = parser.parse_args()
    model = args.model or model_for("anthropic", "extract")
    for _ in range(args.runs):
        for key in args.repos:
            print(json.dumps(measure(key, model, args.effort, args.fast), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
