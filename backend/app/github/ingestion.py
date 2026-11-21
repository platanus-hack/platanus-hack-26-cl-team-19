"""Ingesta de un repo de GitHub: tarball → extracción segura → la IA lee el repo → modelo v1 (JAJ-57, ADR 0002).

Corre en segundo plano (``BackgroundTasks``) y deja su progreso en ``IngestionJobs``, que la UI
consulta con ``GET /github/ingestions/{id}``. Las etapas son las de la pantalla "Conectar repo":
``acceso`` (token y descarga), ``analisis`` (Claude propone la arquitectura y se arma el modelo con la
IaC y el catálogo) y ``preparacion`` (guardar la v1). Funciona con cualquier framework.

Los trabajos en curso viven en memoria: si la API reinicia a mitad de una ingesta, el usuario la
vuelve a lanzar. Lo que termina bien queda en Postgres (el proyecto, su v1 y la fila de ``ingestions``).
"""

from __future__ import annotations

import io
import logging
import os
import tarfile
import tempfile
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import anthropic
import openai

from app.agent.loop import _provider_error, cost_usd
from app.api.store import ProjectStore, RepoSource
from app.github.client import GitHubApp, GitHubError, Repo
from app.ingest.ai_graph import build_from_ai
from app.ingest.analyzer import AnalysisFailed, analyze_repo
from app.ingest.build_model import NoEndpoints
from app.ingest.iac import scan_deployment

log = logging.getLogger(__name__)

Status = Literal["queued", "running", "done", "failed"]
Stage = Literal["acceso", "analisis", "preparacion"]


@dataclass(frozen=True)
class Ingestion:
    id: str
    owner: str | None
    repo_full_name: str
    branch: str
    status: Status = "queued"
    stage: Stage | None = None
    commit_sha: str | None = None
    project_id: str | None = None
    version: int | None = None
    endpoints: int | None = None
    llm_steps: int | None = None  # vueltas de la IA leyendo el repo (IA-4)
    cost: dict[str, Any] | None = None  # US$ de los tokens, si el modelo tiene precio en manual.json
    error_message: str | None = None  # en español, para mostrarlo tal cual
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class IngestionJobs:
    """Las ingestas en curso y recientes, en memoria."""

    def __init__(self) -> None:
        self._jobs: dict[str, Ingestion] = {}
        self._lock = threading.Lock()

    def start(self, owner: str | None, repo_full_name: str, branch: str) -> Ingestion:
        job = Ingestion(uuid.uuid4().hex[:12], owner, repo_full_name, branch)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str, owner: str | None) -> Ingestion | None:
        job = self._jobs.get(job_id)
        return job if job is not None and job.owner == owner else None

    def update(self, job_id: str, **changes: Any) -> Ingestion:
        with self._lock:
            job = self._jobs[job_id] = replace(self._jobs[job_id], **changes)
        return job


def extract_tarball(data: bytes, dest: Path) -> Path:
    """Extrae sin salir de ``dest`` (filtro ``data``: sin rutas absolutas, ``..``, symlinks afuera ni
    archivos de dispositivo). Devuelve la carpeta raíz ``<owner>-<repo>-<sha>/`` del tarball."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(dest, filter="data")
    roots = [p for p in dest.iterdir() if p.is_dir()]
    return roots[0] if len(roots) == 1 else dest


DEFAULT_TEAM_EXTRACT_TOKENS = 1_500_000  # provisorio hasta medir con IA-0 (spikes/ia-0-analizador)


def team_token_cap() -> int:
    """Tope de tokens por análisis con la key de Branchpoint (``BRANCHPOINT_TEAM_EXTRACT_TOKENS``)."""
    try:
        return int(os.environ.get("BRANCHPOINT_TEAM_EXTRACT_TOKENS", "").strip() or DEFAULT_TEAM_EXTRACT_TOKENS)
    except ValueError:
        return DEFAULT_TEAM_EXTRACT_TOKENS


def model_from_tarball(
    data: bytes,
    repo_full_name: str,
    llm: Any,
    commit: str | None = None,
    provider: str | None = None,
    *,
    max_tokens_total: int | None = None,
    on_step: Any = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="branchpoint-") as tmp:  # se borra al salir, aunque falle
        root = extract_tarball(data, Path(tmp)).resolve()
        result = analyze_repo(root, llm, repo_full_name, commit, max_tokens_total=max_tokens_total, on_step=on_step)
        iac = scan_deployment(root).to_dict()
        # sin respuestas: los SUPUESTO quedan por revisar (JAJ-59); root verifica los valores citados
        model = build_from_ai(result.sub, {}, via="ingesta", iac=iac, root=root)
    model["repo"]["path"] = repo_full_name  # no el nombre de la carpeta temporal
    llm_model = getattr(llm, "model", None)
    model["repo"]["source"]["analysis"] = {
        "provider": provider,
        "model": llm_model,
        "usage": result.usage,
        "steps": result.steps,
        "cost": cost_usd(llm_model, result.usage) if llm_model else None,
        "dropped": result.dropped,
    }
    if result.dropped:
        model.setdefault("warnings", []).extend(
            f"Quitado porque la evidencia no calza con el repo: {d}" for d in result.dropped
        )
    return model


def _is_sha(sha: str | None) -> bool:
    return bool(sha) and all(c in "0123456789abcdef" for c in sha) and 7 <= len(sha) <= 40


def run_ingestion(
    jobs: IngestionJobs,
    job_id: str,
    github: GitHubApp,
    store: ProjectStore,
    repo: Repo,
    project_name: str,
    llm: Any,
    provider: str = "anthropic",
    max_tokens_total: int | None = None,
) -> None:
    """Corre la ingesta completa. Nunca lanza: un error queda en el trabajo como ``failed``.

    ``max_tokens_total`` va solo con la key de Branchpoint (IA-4); con la del usuario no hay tope nuestro."""
    job = jobs.update(job_id, status="running", stage="acceso")
    try:
        sha, tarball = github.fetch(repo.installation_id, repo.full_name, job.branch)
        jobs.update(job_id, stage="analisis", commit_sha=sha, llm_steps=0)
        model = model_from_tarball(
            tarball,
            repo.full_name,
            llm,
            sha if _is_sha(sha) else None,
            provider,
            max_tokens_total=max_tokens_total,
            on_step=lambda step, _tool: jobs.update(job_id, llm_steps=step),
        )
        analysis = model["repo"]["source"]["analysis"]
        jobs.update(job_id, stage="preparacion", endpoints=len(model["endpoints"]), cost=analysis.get("cost"))
        connection = store.connect_repo(job.owner, repo.installation_id, repo.id, repo.full_name, repo.default_branch)
        stats = (model.get("repo") or {}).get("stats")
        source = RepoSource(connection, repo.full_name, job.branch, sha, stats)
        project = store.create(project_name, model, None, job.owner, source)
        jobs.update(job_id, status="done", project_id=project.id, version=1)
    except GitHubError as e:
        jobs.update(job_id, status="failed", error_message=e.message)
    except (NoEndpoints, AnalysisFailed) as e:
        jobs.update(job_id, status="failed", error_message=str(e))
    except (anthropic.APIError, openai.APIError) as e:  # key inválida, sin crédito, límite de la API (IA-4)
        jobs.update(job_id, status="failed", error_message=_provider_error(e, getattr(llm, "model", "?")))
    except Exception:
        log.exception("Falló la ingesta %s de %s", job_id, repo.full_name)  # sin tokens: no están en el contexto
        jobs.update(job_id, status="failed", error_message="No pudimos analizar el repo. Intenta de nuevo.")
