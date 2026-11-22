"""JAJ-126: mide descarga, preparación, analizador, persistencia y grafo sin credenciales."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import tempfile
import time
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
IA0 = HERE.parent / "ia-0-analizador"
E2E = HERE.parent / "ia-e2e"
sys.path[:0] = [str(HERE.parents[1] / "backend"), str(E2E), str(IA0)]

from analyst import CALLS, DB, ROUTES, ScriptedAnalyst  # noqa: E402
from app.agent.loop import Turn  # noqa: E402
from app.api.routes.models import graph  # noqa: E402
from app.api.schemas import GraphRequest  # noqa: E402
from app.api.store import InMemoryProjectStore  # noqa: E402
from app.github import ingestion  # noqa: E402
from app.github.client import Repo  # noqa: E402
from run import REFERENCE, norm  # noqa: E402
from score import score  # noqa: E402

TOY_ENDPOINTS = {
    "shop-api": {"GET /items", "GET /items/{}", "POST /orders"},
    "payments": {"POST /charges", "GET /charges/{}"},
    "notifications": {"GET /health", "POST /notify"},
}
PUBLIC_REPOS = (
    "fastapi-realworld-example-app",
    "node-express-realworld-example-app",
    "django-realworld-example-app",
)
STAGES = {
    "extract_tarball": "extract_ms",
    "analyze_repo": "analysis_ms",
    "scan_deployment": "iac_ms",
    "build_from_ai": "build_ms",
}


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


class LocalAnalyst:
    """Reproduce una entrega de IA-0 o ejecuta el guion de IA-E2E, con un costo de ida y vuelta configurable."""

    model = "local-benchmark"

    def __init__(self, *, batch: bool = False, delay_ms: float = 0, replay: dict | None = None):
        self.batch, self.delay_ms, self.replay = batch, delay_ms, replay
        self.elapsed_ms = self.request_bytes = self.response_bytes = self.calls = 0

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        started = time.perf_counter()
        if self.delay_ms:
            time.sleep(self.delay_ms / 1000)
        if self.replay is not None:
            blocks = [{"type": "tool_use", "id": "replay", "name": "submit_architecture", "input": self.replay}]
        elif self.batch and self.calls == 0:
            blocks = [
                {"type": "tool_use", "id": f"g{n}", "name": "grep", "input": {"pattern": pattern}}
                for n, pattern in enumerate((ROUTES, CALLS, DB))
            ]
        else:
            script_messages = messages
            if self.batch:
                # El guion existente espera un grep por mensaje. La entrada real conserva los tres resultados juntos.
                script_messages = [messages[0]]
                for call, result in zip(messages[1]["content"], messages[2]["content"], strict=True):
                    script_messages.extend(
                        [{"role": "assistant", "content": [call]}, {"role": "user", "content": [result]}]
                    )
            blocks = ScriptedAnalyst().complete(system, script_messages, tools).content
        self.elapsed_ms += (time.perf_counter() - started) * 1000
        self.request_bytes += len(json_bytes({"system": system, "tools": tools, "messages": messages}))
        self.response_bytes += len(json_bytes(blocks))
        self.calls += 1
        return Turn(blocks, "tool_use")


class ArchiveSource:
    def __init__(self, sha: str, archive):
        self.sha, self.archive = sha, archive
        self.ms = self.size = 0

    def fetch(self, installation_id: int, full_name: str, ref: str) -> tuple[str, bytes]:
        started = time.perf_counter()
        data = self.archive()
        self.ms = (time.perf_counter() - started) * 1000
        self.size = len(data)
        return self.sha, data


def download(repo: str, sha: str, cache: Path) -> bytes:
    # Solo repos públicos fijados en IA-0. El contenido se analiza como datos.
    with urlopen(f"https://codeload.github.com/{repo}/tar.gz/{sha}", timeout=30) as response:
        data = response.read()
    cache.write_bytes(data)
    return data


def measure(repo_name: str, source: ArchiveSource, llm: LocalAnalyst) -> dict:
    times = {}

    def timed(stage, function):
        def run(*args, **kwargs):
            started = time.perf_counter()
            result = function(*args, **kwargs)
            times[stage] = (time.perf_counter() - started) * 1000
            return result

        return run

    jobs, store = ingestion.IngestionJobs(), InMemoryProjectStore()
    repo = Repo(1, repo_name, False, "main", 1)
    with ExitStack() as context:
        for attribute, stage in STAGES.items():
            func = getattr(ingestion, attribute)
            context.enter_context(patch.object(ingestion, attribute, timed(stage, func)))
        context.enter_context(patch.object(store, "create", timed("save_ms", store.create)))
        started = time.perf_counter()
        job = jobs.start(None, repo.full_name, "main")
        ingestion.run_ingestion(jobs, job.id, source, store, repo, repo_name, llm)
        result = jobs.get(job.id, None)
        if result.status != "done":
            raise RuntimeError(f"{repo_name}: {result.error_message}")
        model = store.get_version(result.project_id, result.version).model
        diagram = timed("graph_ms", graph)(GraphRequest(model=model))
        ready_ms = (time.perf_counter() - started) * 1000

    analysis = model["repo"]["source"]["analysis"]
    return {
        "ready_ms": ready_ms,
        "download_ms": source.ms,
        "archive_bytes": source.size,
        **times,
        "model_ms": llm.elapsed_ms,
        "analyzer_local_ms": times["analysis_ms"] - llm.elapsed_ms,
        "calls": llm.calls,
        "request_bytes": llm.request_bytes,
        "response_bytes": llm.response_bytes,
        "tokens_est": round((llm.request_bytes + llm.response_bytes) / 4),
        "endpoints": sorted(norm(endpoint.id) for endpoint in diagram.endpoints),
        "evidence_dropped": len(analysis["dropped"]),
        "graph_sha256": hashlib.sha256(json_bytes(diagram.to_dict())).hexdigest(),
        "nodes": len(diagram.nodes),
        "edges": len(diagram.edges),
    }


def toy_runs(scratch: Path, runs: int, delay_ms: float):
    for name, expected in TOY_ENDPOINTS.items():
        path = scratch / f"{name}.tgz"
        with tarfile.open(path, mode="w:gz") as tar:
            tar.add(E2E / "toys" / name, arcname=name)
        for run in range(runs):
            original, batched = (
                measure(
                    f"toys/{name}",
                    ArchiveSource("0" * 40, path.read_bytes),
                    LocalAnalyst(batch=batch, delay_ms=delay_ms),
                )
                for batch in (False, True)
            )
            if original["graph_sha256"] != batched["graph_sha256"] or any(
                set(result["endpoints"]) != expected or result["evidence_dropped"] for result in (original, batched)
            ):
                raise RuntimeError(f"{name}: cambió la arquitectura o su evidencia")
            for mode, result in (("serial", original), ("batch", batched)):
                yield {"repo": name, "run": run + 1, "mode": mode, "delay_ms": delay_ms, **result}


def public_runs(scratch: Path, runs: int):
    for name in PUBLIC_REPOS:
        spec = REFERENCE["repos"][name]
        repo, sha = spec["url"].removeprefix("https://github.com/"), spec["commit"]
        submission = json.loads((IA0 / "claude-cli" / f"{name}.json").read_text(encoding="utf-8"))
        cache = scratch / f"{name}.tgz"

        for run in range(runs):
            original, cached = (
                measure(repo, ArchiveSource(sha, archive), LocalAnalyst(replay=submission))
                for archive in (partial(download, repo, sha, cache), cache.read_bytes)
            )
            if original["graph_sha256"] != cached["graph_sha256"]:
                raise RuntimeError(f"{name}: el archivo reutilizado cambió el grafo")
            for mode, result in (("download", original), ("cached", cached)):
                yield {"repo": name, "run": run + 1, "mode": mode, "delay_ms": 0, **result}

        extracted = scratch / name
        extracted.mkdir()
        root = ingestion.extract_tarball(cache.read_bytes(), extracted)
        yield {"mode": "ia0-quality", **score(name, root, submission)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--delay-ms", type=float, default=250)
    parser.add_argument("--public", action="store_true", help="Incluye descargas de los tres repos públicos de IA-0")
    args = parser.parse_args()
    if args.runs < 1 or args.delay_ms < 0:
        parser.error("--runs debe ser positivo y --delay-ms no negativo")

    os.environ.pop("E2E_STEP_DELAY_S", None)
    with tempfile.TemporaryDirectory(prefix="jaj-126-") as tmp:
        for result in toy_runs(Path(tmp), args.runs, args.delay_ms):
            print(json.dumps(result, ensure_ascii=False), flush=True)
        if args.public:
            for result in public_runs(Path(tmp), args.runs):
                print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
