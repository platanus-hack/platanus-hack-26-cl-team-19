"""Conectar un repo de GitHub con la GitHub App y analizarlo como v1 de un proyecto (JAJ-57).

Flujo (el diseño está en ``spikes/jaj-53-acceso-github/README.md``):

1. ``GET /github/install-url`` (con sesión): la URL para instalar la app, con un ``state`` firmado
   que dice quién la pidió. Si ya estaba instalada, GitHub no redirige al cambiarla: para eso está
   ``GET /github/authorize-url`` (OAuth sin instalar), que vuelve al mismo callback sin ``installation_id``.
2. El usuario instala la app en GitHub y elige los repos. GitHub vuelve a ``GET /github/callback``
   con ``code``, ``installation_id`` y ``state``. La API valida el state, confirma con el ``code`` que
   la instalación es de ese usuario de GitHub, la guarda y redirige al frontend
   (``BRANCHPOINT_FRONTEND_URL/onboarding?github=ok`` o ``?github=error&message=...``).
3. ``GET /github/repos`` y ``GET /github/repos/{owner}/{repo}/branches``: qué puede elegir.
4. ``POST /github/ingestions``: analiza ese repo y rama en segundo plano. ``GET /github/ingestions/{id}``
   da el progreso y, al terminar, el ``project_id`` con su v1.

Los tokens de GitHub nunca salen en respuestas ni logs: se piden por llamada y se descartan.
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.auth import User, current_user, owner_of
from app.api.errors import NOT_FOUND, ApiError
from app.github.client import GitHubApp, GitHubError, Repo
from app.github.ingestion import Ingestion, IngestionJobs, run_ingestion
from app.github.state import InvalidState, sign_state, verify_state

router = APIRouter(prefix="/github", tags=["github"])

GITHUB_NOT_CONFIGURED = "github_not_configured"  # faltan las variables GITHUB_APP_* en el backend (503)
GITHUB_ERROR = "github_error"  # GitHub respondió con error; ``message`` dice qué hacer
DEFAULT_FRONTEND_URL = "http://localhost:3000"


class InstallUrl(BaseModel):
    url: str


class InstallationOut(BaseModel):
    installation_id: int
    account_login: str


class RepoOut(BaseModel):
    id: int
    full_name: str
    private: bool
    default_branch: str
    installation_id: int


class ConnectionOut(BaseModel):
    repos: list[RepoOut]
    installations: list[InstallationOut]
    revoked: bool


class StartIngestion(BaseModel):
    repo_full_name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$", examples=["acme/tienda"])
    branch: str | None = Field(None, min_length=1, max_length=255, description="por defecto, la rama por defecto")
    name: str | None = Field(
        None, min_length=1, max_length=120, description="nombre del proyecto; por defecto, el repo"
    )


class IngestionOut(BaseModel):
    id: str
    repo_full_name: str
    branch: str
    status: Literal["queued", "running", "done", "failed"]
    stage: Literal["acceso", "analisis", "preparacion"] | None
    commit_sha: str | None
    endpoints: int | None
    project_id: str | None = Field(description="al terminar: el proyecto creado, con su v1")
    version: int | None
    error_message: str | None
    created_at: str


def _out(job: Ingestion) -> IngestionOut:
    return IngestionOut(**{k: v for k, v in job.__dict__.items() if k != "owner"})


def get_github(request: Request) -> GitHubApp:
    github: GitHubApp | None = request.app.state.github
    if github is None:
        raise ApiError(
            503,
            GITHUB_NOT_CONFIGURED,
            "La conexión con GitHub no está configurada en el backend (faltan las variables GITHUB_APP_*).",
        )
    return github


def _github_error(e: GitHubError) -> ApiError:
    status = e.status if e.status in (401, 403, 404, 413, 422, 429) else 502
    return ApiError(status, GITHUB_ERROR, e.message)


def callback_url(request: Request) -> str:
    """La Callback URL de este backend, que va como ``redirect_uri`` del OAuth (JAJ-84). Tiene que estar
    registrada en la GitHub App. En producción sale de ``BRANCHPOINT_API_URL``, porque detrás del proxy
    de Render el request llega por http. En local, de la URL del request."""
    base = os.environ.get("BRANCHPOINT_API_URL", "").strip().rstrip("/")
    return f"{base}/github/callback" if base else str(request.url_for("callback"))


def _frontend(path_query: dict[str, str]) -> str:
    base = os.environ.get("BRANCHPOINT_FRONTEND_URL", DEFAULT_FRONTEND_URL).rstrip("/")
    return f"{base}/onboarding?{urllib.parse.urlencode(path_query)}"


# ---------- instalar ----------


@router.get("/install-url", response_model=InstallUrl)
def install_url(github: GitHubApp = Depends(get_github), user: User | None = Depends(current_user)) -> InstallUrl:
    return InstallUrl(url=github.install_url(sign_state(github.config.client_secret, owner_of(user))))


@router.get("/authorize-url", response_model=InstallUrl)
def authorize_url(
    request: Request, github: GitHubApp = Depends(get_github), user: User | None = Depends(current_user)
) -> InstallUrl:
    """El paso que liga la app al usuario: después de instalarla en otra pestaña, o si ya estaba
    instalada. Es el OAuth web con ``redirect_uri``, así vuelve a este backend y no a la primera
    Callback URL de la app (JAJ-84). El callback guarda las instalaciones que ve el usuario."""
    state = sign_state(github.config.client_secret, owner_of(user))
    return InstallUrl(url=github.authorize_url(state, callback_url(request)))


@router.get("/callback", include_in_schema=False)
def callback(
    request: Request,
    installation_id: int | None = None,
    code: str | None = None,
    state: str | None = None,
    setup_action: str | None = None,
    github: GitHubApp = Depends(get_github),
) -> RedirectResponse:
    """Sin sesión: lo llama el navegador al volver de GitHub. El ``state`` dice quién es."""

    def fail(message: str) -> RedirectResponse:
        return RedirectResponse(_frontend({"github": "error", "message": message}), status_code=302)

    if not state:
        return fail("GitHub no devolvió el enlace de conexión. Vuelve a conectar desde Branchpoint.")
    try:
        owner = verify_state(github.config.client_secret, state)
    except (InvalidState, ValueError) as e:
        return fail(str(e) if isinstance(e, InvalidState) else "El enlace de conexión no es válido.")
    if not code:
        # p. ej. setup_action=request: un admin de la org tiene que aprobar la instalación
        if setup_action == "request":
            return fail("La instalación quedó pendiente: un admin de la organización tiene que aprobarla.")
        return fail("La instalación se canceló o no terminó. Puedes volver a intentarlo.")
    try:
        # con installation_id volvió de la instalación (OAuth durante la instalación, sin redirect_uri);
        # sin él, del OAuth web de /authorize-url, que sí mandó redirect_uri
        visible = github.user_installations(code, None if installation_id is not None else callback_url(request))
    except GitHubError as e:
        return fail(e.message)
    if installation_id is not None:  # volvió de instalar: solo esa, y tiene que ser del usuario
        if installation_id not in visible:
            return fail("Esa instalación de la GitHub App no es de tu cuenta de GitHub.")
        visible = {installation_id: visible[installation_id]}
    elif not visible:  # volvió de /authorize-url y no tiene la app en ninguna cuenta
        return fail("No encontramos la GitHub App instalada en tu cuenta. Instálala con «Conectar con GitHub».")
    store = request.app.state.store
    for inst_id, account in visible.items():
        store.save_installation(inst_id, owner, account)
    return RedirectResponse(_frontend({"github": "ok", "account": ", ".join(visible.values())}), status_code=302)


@router.get("/installations", response_model=list[InstallationOut])
def installations(request: Request, user: User | None = Depends(current_user)) -> list[InstallationOut]:
    """Las instalaciones del usuario. Vacío = todavía no conectó GitHub."""
    found = request.app.state.store.list_installations(owner_of(user))
    return [InstallationOut(installation_id=i.installation_id, account_login=i.account_login) for i in found]


# ---------- elegir repo y rama ----------


def _repos(request: Request, github: GitHubApp, owner: str | None) -> list[Repo]:
    store = request.app.state.store
    repos: list[Repo] = []
    for inst in store.list_installations(owner):
        try:
            repos += github.list_repos(inst.installation_id)
        except GitHubError as e:
            if e.status == 404:  # la desinstalaron desde GitHub: deja de listarse
                store.revoke_installation(inst.installation_id)
                continue
            raise _github_error(e) from None
    return sorted(repos, key=lambda r: r.full_name.lower())


def _repo_or_404(request: Request, github: GitHubApp, owner: str | None, full_name: str) -> Repo:
    for repo in _repos(request, github, owner):
        if repo.full_name.lower() == full_name.lower():
            return repo
    raise ApiError(
        404,
        NOT_FOUND,
        f"La GitHub App no tiene acceso a {full_name}. Agrégalo a la instalación y vuelve a intentar.",
        resource="repo",
    )


@router.get("/repos", response_model=list[RepoOut])
def repos(
    request: Request, github: GitHubApp = Depends(get_github), user: User | None = Depends(current_user)
) -> list[RepoOut]:
    return [RepoOut(**r.__dict__) for r in _repos(request, github, owner_of(user))]


@router.get("/connection", response_model=ConnectionOut)
def connection(
    request: Request, github: GitHubApp = Depends(get_github), user: User | None = Depends(current_user)
) -> ConnectionOut:
    """Repos, instalaciones y si se perdió el acceso, en una sola consulta para el onboarding (JAJ-91).

    ``revoked`` es verdadero cuando el usuario ya no tiene instalaciones vigentes y al menos una
    fue revocada desde GitHub: así la UI explica por qué desaparecieron sus repos.
    """
    store = request.app.state.store
    owner = owner_of(user)
    available_repos = _repos(request, github, owner)
    # Se consulta después de GitHub: _repos detecta y registra las revocaciones.
    active = installations(request, user)
    return ConnectionOut(
        repos=[RepoOut(**repo.__dict__) for repo in available_repos],
        installations=active,
        revoked=not active and bool(store.list_installations(owner, revoked=True)),
    )


@router.get("/repos/{owner}/{repo}/branches", response_model=list[str])
def branches(
    owner: str,
    repo: str,
    request: Request,
    github: GitHubApp = Depends(get_github),
    user: User | None = Depends(current_user),
) -> list[str]:
    found = _repo_or_404(request, github, owner_of(user), f"{owner}/{repo}")
    try:
        names = github.list_branches(found.installation_id, found.full_name)
    except GitHubError as e:
        raise _github_error(e) from None
    # la rama por defecto primero: es la que casi siempre se elige
    return sorted(names, key=lambda b: (b != found.default_branch, b.lower()))


# ---------- analizar ----------


def get_jobs(request: Request) -> IngestionJobs:
    return request.app.state.ingestions


@router.post("/ingestions", response_model=IngestionOut, status_code=202)
def start_ingestion(
    req: StartIngestion,
    request: Request,
    tasks: BackgroundTasks,
    github: GitHubApp = Depends(get_github),
    jobs: IngestionJobs = Depends(get_jobs),
    user: User | None = Depends(current_user),
) -> IngestionOut:
    owner = owner_of(user)
    repo = _repo_or_404(request, github, owner, req.repo_full_name)
    job = jobs.start(owner, repo.full_name, req.branch or repo.default_branch)
    name = req.name or repo.full_name.split("/", 1)[1]
    tasks.add_task(run_ingestion, jobs, job.id, github, request.app.state.store, repo, name)
    return _out(job)


@router.get("/ingestions/{ingestion_id}", response_model=IngestionOut)
def get_ingestion(
    ingestion_id: str, jobs: IngestionJobs = Depends(get_jobs), user: User | None = Depends(current_user)
) -> IngestionOut:
    job = jobs.get(ingestion_id, owner_of(user))
    if job is None:
        raise ApiError(404, NOT_FOUND, "No encontramos esa ingesta.", resource="ingestion")
    return _out(job)
