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
from concurrent.futures import ThreadPoolExecutor
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
from app.ingest.multirepo import RepoResult, merge_repos, single_repo_sources

log = logging.getLogger(__name__)

Status = Literal["queued", "running", "done", "failed"]
Stage = Literal["acceso", "analisis", "preparacion"]


@dataclass(frozen=True)
class RepoProgress:
    """El avance de un repo en una ingesta de varios repos (IA-5)."""

    full_name: str
    branch: str
    primary: bool
    status: Status = "queued"
    endpoints: int | None = None
    llm_steps: int | None = None
    error_message: str | None = None


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
    repos: tuple[RepoProgress, ...] = ()  # con varios repos (IA-5); los campos de arriba son del principal
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class IngestionJobs:
    """Las ingestas en curso y recientes, en memoria."""

    def __init__(self) -> None:
        self._jobs: dict[str, Ingestion] = {}
        self._lock = threading.Lock()

    def start(
        self, owner: str | None, repo_full_name: str, branch: str, others: list[tuple[str, str]] | None = None
    ) -> Ingestion:
        repos = (
            (RepoProgress(repo_full_name, branch, True), *(RepoProgress(n, b, False) for n, b in others))
            if others
            else ()
        )
        job = Ingestion(uuid.uuid4().hex[:12], owner, repo_full_name, branch, repos=repos)
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

    def update_repo(self, job_id: str, index: int, **changes: Any) -> None:
        """Cambia el avance de un repo; los análisis corren en paralelo, así que va con el lock."""
        with self._lock:
            job = self._jobs[job_id]
            repos = list(job.repos)
            repos[index] = replace(repos[index], **changes)
            self._jobs[job_id] = replace(job, repos=tuple(repos))


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


def _failure(e: Exception, llm: Any, where: str) -> str:
    """El mensaje para el usuario de un error al analizar un repo. Nunca trae tokens ni keys."""
    if isinstance(e, GitHubError):
        return e.message
    if isinstance(e, (NoEndpoints, AnalysisFailed)):
        return str(e)
    if isinstance(e, (anthropic.APIError, openai.APIError)):  # key inválida, sin crédito, límite de la API (IA-4)
        return _provider_error(e, getattr(llm, "model", "?"))
    log.exception("Falló la ingesta de %s", where)  # sin tokens: no están en el contexto
    return "No pudimos analizar el repo. Intenta de nuevo."


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
    secondaries: list[tuple[Repo, str, Any]] | None = None,
) -> None:
    """Corre la ingesta completa. Nunca lanza: un error queda en el trabajo como ``failed``.

    ``max_tokens_total`` va solo con la key de Branchpoint (IA-4), por repo; con la del usuario no hay tope
    nuestro. ``secondaries`` son los otros repos del proyecto (IA-5): ``(repo, rama, llm)``."""
    if secondaries:
        _run_multi(jobs, job_id, github, store, repo, project_name, llm, provider, max_tokens_total, secondaries)
        return
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
        single_repo_sources(model, repo.full_name, job.branch, sha)
        analysis = model["repo"]["source"]["analysis"]
        jobs.update(job_id, stage="preparacion", endpoints=len(model["endpoints"]), cost=analysis.get("cost"))
        connection = store.connect_repo(job.owner, repo.installation_id, repo.id, repo.full_name, repo.default_branch)
        stats = (model.get("repo") or {}).get("stats")
        source = RepoSource(connection, repo.full_name, job.branch, sha, stats)
        project = store.create(project_name, model, None, job.owner, source)
        jobs.update(job_id, status="done", project_id=project.id, version=1)
    except Exception as e:  # noqa: BLE001 - todo error queda en el trabajo
        jobs.update(job_id, status="failed", error_message=_failure(e, llm, repo.full_name))


def _run_multi(
    jobs: IngestionJobs,
    job_id: str,
    github: GitHubApp,
    store: ProjectStore,
    primary: Repo,
    project_name: str,
    llm: Any,
    provider: str,
    max_tokens_total: int | None,
    secondaries: list[tuple[Repo, str, Any]],
) -> None:
    """Varios repos (IA-5): cada uno se descarga y analiza en paralelo con su propio LLM. Si falla el
    principal, la ingesta falla; si falla un secundario, sigue con un aviso."""
    job = jobs.update(job_id, status="running", stage="analisis", llm_steps=0)
    targets = [(primary, job.branch, llm), *secondaries]

    def analyze(index: int, repo: Repo, branch: str, repo_llm: Any) -> tuple[RepoResult, str | None]:
        jobs.update_repo(job_id, index, status="running", llm_steps=0)
        sha: str | None = None

        def step(n: int, _tool: str) -> None:
            jobs.update_repo(job_id, index, llm_steps=n)
            if index == 0:
                jobs.update(job_id, llm_steps=n)

        try:
            sha, tarball = github.fetch(repo.installation_id, repo.full_name, branch)
            if index == 0:
                jobs.update(job_id, commit_sha=sha)
            model = model_from_tarball(
                tarball,
                repo.full_name,
                repo_llm,
                sha if _is_sha(sha) else None,
                provider,
                max_tokens_total=max_tokens_total,
                on_step=step,
            )
        except Exception as e:  # noqa: BLE001 - un repo que falla no bota a los otros
            message = _failure(e, repo_llm, repo.full_name)
            jobs.update_repo(job_id, index, status="failed", error_message=message)
            return RepoResult(repo.full_name, branch, sha, None, message), sha
        jobs.update_repo(job_id, index, status="done", endpoints=len(model["endpoints"]))
        return RepoResult(repo.full_name, branch, sha, model), sha

    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
        results = list(pool.map(lambda item: analyze(item[0], *item[1]), enumerate(targets)))
    (first, _), rest = results[0], results[1:]
    if first.model is None:
        jobs.update(job_id, status="failed", error_message=f"{primary.full_name}: {first.error}")
        return
    try:
        model = merge_repos(first, [r for r, _ in rest])
        costs = [r.model["repo"]["source"]["analysis"].get("cost") for r, _ in results if r.model is not None]
        jobs.update(
            job_id, stage="preparacion", endpoints=len(model["endpoints"]), cost=_sum_costs([c for c in costs if c])
        )
        sources = []
        for (repo, branch, _), (result, sha) in zip(targets, results, strict=True):
            if sha is None:
                continue  # ni siquiera se pudo descargar: no hay commit que guardar
            connection = store.connect_repo(
                job.owner, repo.installation_id, repo.id, repo.full_name, repo.default_branch
            )
            stats = ((result.model or {}).get("repo") or {}).get("stats")
            sources.append(RepoSource(connection, repo.full_name, branch, sha, stats))
        project = store.create(project_name, model, None, job.owner, sources[0], sources)
        jobs.update(job_id, status="done", project_id=project.id, version=1)
    except Exception as e:  # noqa: BLE001
        jobs.update(job_id, status="failed", error_message=_failure(e, llm, primary.full_name))


def _sum_costs(costs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not costs:
        return None
    return {**costs[0], "value": round(sum(c["value"] for c in costs), 4), "source": costs[0]["source"]}
