"""Proyectos y versiones del editor.

Cada proyecto parte con la **v1** (el modelo del repo) y cada cambio guardado es una versión nueva
con su antecesora, como un commit. ``ProjectStore`` es la interfaz que usan las rutas. Tiene dos
implementaciones: ``InMemoryProjectStore`` (se pierde al reiniciar; la usan los tests) y
``PostgresProjectStore`` en ``app/db/postgres_store.py`` (JAJ-56).
"""

from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from app.models.architecture import value

Origin = Literal["repo", "manual", "agente"]


@dataclass
class Version:
    number: int
    origin: Origin
    parent: int | None
    note: str | None
    created_at: str
    # el modelo completo pesa ~100 KB: get() trae las versiones sin él y get_version() con él
    model: dict[str, Any] | None
    proposal_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ProjectRepo:
    """Un repo del proyecto (IA-5). El principal es el que simula el motor."""

    full_name: str
    branch: str | None
    primary: bool = True


@dataclass
class Project:
    id: str
    name: str
    sample: str | None  # id del modelo de ejemplo del que salió, si salió de uno
    created_at: str
    versions: list[Version] = field(default_factory=list)
    owner: str | None = None  # auth.users.id de quien lo creó; None sin login (JAJ-78)
    # el repo del que salió la v1 (JAJ-92): "owner/nombre" y la rama analizada. None si salió de un
    # ejemplo o de un modelo subido a mano
    repo_full_name: str | None = None
    branch: str | None = None
    # todos los repos (IA-5), el principal primero. Vacío en proyectos de un ejemplo o anteriores a IA-5
    repositories: list[ProjectRepo] = field(default_factory=list)

    def repos(self) -> list[ProjectRepo]:
        """Los repos del proyecto, el principal primero. Un proyecto de un solo repo lo deriva de su v1."""
        if self.repositories:
            return self.repositories
        return [ProjectRepo(self.repo_full_name, self.branch, True)] if self.repo_full_name else []

    def version(self, number: int) -> Version | None:
        return self.versions[number - 1] if 1 <= number <= len(self.versions) else None


@dataclass(frozen=True)
class ProjectScenario:
    """Un escenario del proyecto (JAJ-76). Es del proyecto y no de una versión: así cualquier par de
    versiones se compara con el mismo escenario.

    Trae una de dos tasas: ``multiplier`` (× el pico del modelo de cada versión, ``traffic.peak_rps``)
    o ``rps`` (req/s fijas, iguales en todas las versiones).
    """

    name: str
    multiplier: float | None
    rps: float | None
    description: str | None = None
    # JAJ-131: reemplazos que trae el escenario (mezcla de endpoints, dependencias más lentas, negocio)
    endpoint_weights: dict[str, float] | None = None
    slowdowns: dict[str, float] | None = None
    business: dict[str, float] | None = None
    traffic_step: dict[str, int | float] | None = None

    def overrides(self) -> dict[str, Any]:
        """Los reemplazos no vacíos, como se guardan en ``scenarios.overrides``."""
        found = {"endpoint_weights": self.endpoint_weights, "slowdowns": self.slowdowns, "business": self.business}
        return {k: v for k, v in found.items() if v}

    def rate_for(self, model: dict[str, Any]) -> float:
        """Las req/s del escenario para el modelo de una versión. ``ValueError`` si es un
        multiplicador y el modelo no trae ``traffic.peak_rps``."""
        if self.rps is not None:
            return self.rps
        peak = value((model.get("traffic") or {}).get("peak_rps"))  # con procedencia o escalar (JAJ-101)
        if not peak or peak <= 0:
            raise ValueError(
                f"El escenario '{self.name}' es ×{self.multiplier:g} el pico, pero el modelo no tiene "
                "traffic.peak_rps. Agrega el pico al modelo o define el escenario con rps."
            )
        return float(peak) * self.multiplier


@dataclass(frozen=True)
class ProjectGoals:
    """Las metas del proyecto (JAJ-67): con ellas el agente decide si una versión sirve. Las declara el
    usuario (``set_goals`` con su frase); ``None`` = sin meta."""

    slo_p95_ms: float | None = None
    slo_error_rate: float | None = None  # fracción, 0 a 1
    budget_usd_month: float | None = None


@dataclass(frozen=True)
class RepoSource:
    """De qué repo, rama y commit salió una v1 analizada (JAJ-57)."""

    connection_id: str  # repo_connections.id
    repo_full_name: str
    branch: str
    commit_sha: str
    stats: dict[str, Any] | None = None  # repo.stats del extractor, para ingestions.stats

    @property
    def note(self) -> str:
        return f"Extraída de {self.repo_full_name}@{self.branch} ({self.commit_sha[:7]})"


AttachmentKind = Literal["image", "log"]


@dataclass(frozen=True)
class Attachment:
    """Un archivo que el usuario subió al chat (IA-6). Vive en Storage hasta ``expires_at``."""

    id: str
    owner: str
    project_id: str
    kind: AttachmentKind
    filename: str
    media_type: str
    bytes: int | None
    storage_path: str
    status: Literal["pending", "ready"]
    created_at: datetime
    expires_at: datetime

    def expired(self, now: datetime | None = None) -> bool:
        return self.expires_at <= (now or datetime.now(UTC))


@dataclass(frozen=True)
class GitHubInstallation:
    installation_id: int
    account_login: str


def scenarios_from_model(model: dict[str, Any]) -> list[ProjectScenario]:
    """Los escenarios de ``traffic.scenarios`` del modelo, para cargarlos al crear un proyecto.

    Se guarda el multiplicador cuando lo hay: así la tasa se recalcula con el pico de cada versión
    (decisión 4 del README de ``app/db``). Si no, las req/s.
    """
    scenarios = []
    for name, sc in ((model.get("traffic") or {}).get("scenarios") or {}).items():
        multiplier, rps = value(sc.get("multiplier")), value(sc.get("rps"))  # con procedencia o escalar
        if multiplier is not None and multiplier > 0:
            scenarios.append(ProjectScenario(name, float(multiplier), None))
        elif rps is not None and rps > 0:
            scenarios.append(ProjectScenario(name, None, float(rps)))
    return scenarios


@dataclass(frozen=True)
class ReportSummary:
    """Lo que muestra la lista de reportes (JAJ-127). En una comparación, los valores son los de B."""

    id: str
    kind: str  # run | comparison
    created_at: str
    version: int | None
    scenario: str | None
    rps: float | None
    seed: int | None
    p95_ms: float | None
    error_rate: float | None
    usd_month: float | None


def report_summary(report: dict[str, Any]) -> ReportSummary:
    if report["kind"] == "comparison":
        b = report["b"]
        return ReportSummary(
            report["id"], "comparison", report["created_at"], b["version"], b["scenario"]["label"],
            b["scenario"]["rps"], b["scenario"]["seed"], b["p95_ms"], b["error_rate"], b["usd_month"],
        )  # fmt: skip
    res, sc = report["results"], report["scenario"]
    return ReportSummary(
        report["id"], "run", report["created_at"], report["version"]["number"], sc["label"], sc["rps"],
        sc["seed"], res["latency"]["p95_ms"], res["error_rate"], (report["costs"]["total"] or {}).get("value"),
    )  # fmt: skip


class ProjectStore(Protocol):
    """Proyectos, versiones, escenarios y runs.

    **Dueños (JAJ-78).** ``create``, ``get`` y ``list`` reciben el ``owner`` (el id del usuario, o
    ``None`` sin login), y ``get`` devuelve ``None`` si el proyecto es de otro. Los demás métodos
    reciben un ``project_id`` que la ruta ya validó con ``get``: toda ruta de un proyecto pasa
    primero por ``get(project_id, owner)``.
    """

    def create(
        self,
        name: str,
        model: dict[str, Any],
        sample: str | None,
        owner: str | None = None,
        source: RepoSource | None = None,
        sources: list[RepoSource] | None = None,
    ) -> Project:
        """Crea el proyecto con su v1. Con ``source``, la v1 queda ligada al repo, la rama y el commit
        analizados (JAJ-57). ``sources`` son todos los repos del proyecto, el principal (``source``) primero
        (IA-5)."""
        ...

    def get(self, project_id: str, owner: str | None = None) -> Project | None:
        """El proyecto con el historial de versiones, si es de ``owner``. Las versiones pueden venir
        sin ``model``."""
        ...

    def get_version(self, project_id: str, number: int) -> Version | None:
        """Una versión con su ``model``."""
        ...

    def list(self, owner: str | None = None) -> list[Project]:
        """Los proyectos de ``owner``, del más nuevo al más viejo."""
        ...

    def add_version(
        self,
        project_id: str,
        model: dict[str, Any],
        origin: Origin,
        parent: int | None,
        note: str | None,
        *,
        proposal_id: uuid.UUID | None = None,
    ) -> Version: ...

    def add_repositories(
        self, project_id: str, model: dict[str, Any], parent: int, note: str, sources: list[RepoSource]
    ) -> Version:
        """Suma repos secundarios a un proyecto que salió de un repo y guarda, en la misma transacción, la
        versión con su análisis (``origin`` repo). Un proyecto de un solo repo pasa a guardar su principal
        en ``project_repositories``."""
        ...

    def get_chat(self, project_id: str) -> list[dict[str, Any]]:
        """Los mensajes del chat del proyecto, tal como los muestra el panel, del más viejo al más nuevo."""
        ...

    def save_chat(self, project_id: str, messages: list[dict[str, Any]]) -> None:
        """Reemplaza los mensajes del chat del proyecto (una conversación por proyecto)."""
        ...

    def list_scenarios(self, project_id: str) -> list[ProjectScenario]:
        """Los escenarios del proyecto, por nombre (JAJ-76)."""
        ...

    def upsert_scenario(self, project_id: str, scenario: ProjectScenario) -> ProjectScenario:
        """Crea el escenario o reemplaza el que tiene ese nombre (JAJ-76)."""
        ...

    def get_goals(self, project_id: str) -> ProjectGoals:
        """Las metas del proyecto (todo ``None`` si no se declararon)."""
        ...

    def set_goals(self, project_id: str, goals: ProjectGoals) -> ProjectGoals:
        """Reemplaza las metas. ``KeyError`` si el proyecto no existe."""
        ...

    def find_run(self, project_id: str, number: int, cache_key: str) -> dict[str, Any] | None:
        """El ``Run`` guardado de la versión ``number`` del proyecto con esa clave (como dict
        ``branchpoint.run/v1``), o ``None`` (JAJ-75).

        Busca por proyecto y versión además de la clave (JAJ-97): un run guardado con la clave de
        otro proyecto nunca se devuelve, aunque alguien lograra escribirlo."""
        ...

    def save_run(
        self,
        project_id: str,
        number: int,
        cache_key: str,
        params: dict[str, Any],
        run: dict[str, Any],
        engine_version: str,
    ) -> None:
        """Guarda el ``Run`` de la versión ``number``. Si la clave ya existe, no hace nada (JAJ-75)."""
        ...

    def save_report(self, project_id: str, report: dict[str, Any]) -> None:
        """Guarda un reporte ``branchpoint.report/v1`` (JAJ-127). Su ``id`` lo trae el reporte."""
        ...

    def list_reports(self, project_id: str) -> list[ReportSummary]:
        """Los reportes del proyecto, del más nuevo al más viejo."""
        ...

    def get_report(self, project_id: str, report_id: str) -> dict[str, Any] | None:
        """Un reporte completo, si es de ese proyecto."""
        ...

    def delete_report(self, project_id: str, report_id: str) -> bool:
        """Borra el reporte. ``False`` si no existía en ese proyecto."""
        ...

    # ---------- GitHub App (JAJ-57) ----------

    def save_installation(self, installation_id: int, owner: str | None, account_login: str) -> None:
        """Liga la instalación al usuario que la verificó. Si ya existía, pasa a ese usuario."""
        ...

    def list_installations(self, owner: str | None, *, revoked: bool = False) -> list[GitHubInstallation]:
        """Las instalaciones de ``owner`` con el estado solicitado."""
        ...

    def revoke_installation(self, installation_id: int) -> None:
        """GitHub dijo que la instalación ya no existe: deja de listarse."""
        ...

    def connect_repo(
        self, owner: str | None, installation_id: int, repo_id: int, full_name: str, default_branch: str
    ) -> str:
        """La ``repo_connections.id`` de ese repo para ``owner``. Reutiliza la que ya existe."""
        ...

    # ---------- Adjuntos del chat (IA-6) ----------

    def create_attachment(self, attachment: Attachment) -> Attachment:
        """Registra el adjunto en ``pending``. La ruta ya validó el proyecto con ``get``."""
        ...

    def get_attachment(self, attachment_id: str, owner: str) -> Attachment | None:
        """El adjunto si es de ``owner`` (vencido o no)."""
        ...

    def list_attachments(self, project_id: str, owner: str, include_pending: bool = False) -> list[Attachment]:
        """Los adjuntos vigentes del proyecto, del más viejo al más nuevo."""
        ...

    def mark_attachment_ready(self, attachment_id: str, owner: str, size: int) -> None: ...

    def delete_attachment(self, attachment_id: str, owner: str) -> None: ...

    def expired_attachments(self, owner: str | None, limit: int = 100) -> list[Attachment]:
        """Los vencidos de ``owner``, o de todos con ``None`` (para una limpieza periódica)."""
        ...


class OwnedStore:
    """El store visto por un usuario (JAJ-78): ``create``, ``get`` y ``list`` llevan su ``owner``
    puesto, y el resto pasa directo. Lo arma ``get_store`` en cada request, así ninguna ruta de
    proyectos puede olvidarse de filtrar por dueño."""

    def __init__(self, store: ProjectStore, owner: str | None) -> None:
        self._store = store
        self.owner = owner

    def create(
        self,
        name: str,
        model: dict[str, Any],
        sample: str | None,
        source: RepoSource | None = None,
        sources: list[RepoSource] | None = None,
    ) -> Project:
        return self._store.create(name, model, sample, self.owner, source, sources)

    def get(self, project_id: str) -> Project | None:
        return self._store.get(project_id, self.owner)

    def list(self) -> list[Project]:
        return self._store.list(self.owner)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


def _repositories(source: RepoSource | None, sources: list[RepoSource] | None) -> list[ProjectRepo]:
    """Los repos de un proyecto nuevo: solo con más de uno se guardan aparte (uno se deriva de la v1)."""
    if not sources or len(sources) < 2:
        return []
    primary = source.repo_full_name if source else sources[0].repo_full_name
    ordered = sorted(sources, key=lambda s: s.repo_full_name != primary)
    return [ProjectRepo(s.repo_full_name, s.branch, s.repo_full_name == primary) for s in ordered]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class InMemoryProjectStore:
    """Guarda copias de los modelos, así quien llama puede seguir editando el suyo sin afectarlas."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        # cache_key → (proyecto, versión, Run como dict) (JAJ-75, JAJ-97)
        self._runs: dict[str, tuple[str, int, dict[str, Any]]] = {}
        self._scenarios: dict[str, dict[str, ProjectScenario]] = {}  # proyecto → nombre → escenario
        self._goals: dict[str, ProjectGoals] = {}  # proyecto → metas (JAJ-67)
        self._lock = threading.Lock()  # las rutas def corren en el pool de hilos de FastAPI
        self._installations: dict[int, tuple[str | None, str, bool]] = {}  # id → (owner, cuenta, revocada)
        self._connections: dict[tuple[str | None, int], str] = {}  # (owner, repo_id) → connection id
        self.sources: dict[str, RepoSource] = {}  # proyecto → origen de su v1 (lo leen los tests)
        self._attachments: dict[str, Attachment] = {}  # adjuntos del chat (IA-6)
        self._chats: dict[str, list[dict[str, Any]]] = {}  # proyecto → mensajes del chat
        self._reports: dict[str, tuple[str, dict[str, Any]]] = {}  # id → (proyecto, reporte) (JAJ-127)

    def create(
        self,
        name: str,
        model: dict[str, Any],
        sample: str | None,
        owner: str | None = None,
        source: RepoSource | None = None,
        sources: list[RepoSource] | None = None,
    ) -> Project:
        project = Project(
            id=uuid.uuid4().hex[:12],
            name=name,
            sample=sample,
            created_at=_now(),
            owner=owner,
            repo_full_name=source.repo_full_name if source else None,
            branch=source.branch if source else None,
            repositories=_repositories(source, sources),
        )
        note = source.note if source else "Extraída del repo"
        project.versions.append(Version(1, "repo", None, note, project.created_at, copy.deepcopy(model)))
        if source:
            self.sources[project.id] = source
        with self._lock:
            self._projects[project.id] = project
            self._scenarios[project.id] = {s.name: s for s in scenarios_from_model(model)}
        return project

    def get(self, project_id: str, owner: str | None = None) -> Project | None:
        project = self._projects.get(project_id)
        return project if project is not None and project.owner == owner else None

    def get_version(self, project_id: str, number: int) -> Version | None:
        project = self._projects.get(project_id)
        return project.version(number) if project is not None else None

    def list(self, owner: str | None = None) -> list[Project]:
        mine = [p for p in self._projects.values() if p.owner == owner]
        return sorted(mine, key=lambda p: p.created_at, reverse=True)

    def add_version(
        self,
        project_id: str,
        model: dict[str, Any],
        origin: Origin,
        parent: int | None,
        note: str | None,
        *,
        proposal_id: uuid.UUID | None = None,
    ) -> Version:
        with self._lock:
            project = self._projects[project_id]
            if proposal_id is not None:
                prior = next((item for item in project.versions if item.proposal_id == proposal_id), None)
                if prior is not None:
                    return prior
            version = Version(
                len(project.versions) + 1, origin, parent, note, _now(), copy.deepcopy(model), proposal_id
            )
            project.versions.append(version)
        return version

    def get_chat(self, project_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self._chats.get(project_id, []))

    def save_chat(self, project_id: str, messages: list[dict[str, Any]]) -> None:
        with self._lock:
            self._chats[project_id] = copy.deepcopy(messages)

    def add_repositories(
        self, project_id: str, model: dict[str, Any], parent: int, note: str, sources: list[RepoSource]
    ) -> Version:
        with self._lock:
            project = self._projects[project_id]
            repos = project.repos()
            if not repos:
                raise ValueError("el proyecto no salió de un repo")
            project.repositories = [
                *repos,
                *(ProjectRepo(s.repo_full_name, s.branch, False) for s in sources),
            ]
            version = Version(len(project.versions) + 1, "repo", parent, note, _now(), copy.deepcopy(model))
            project.versions.append(version)
        return version

    def list_scenarios(self, project_id: str) -> list[ProjectScenario]:
        return sorted(self._scenarios.get(project_id, {}).values(), key=lambda s: s.name)

    def upsert_scenario(self, project_id: str, scenario: ProjectScenario) -> ProjectScenario:
        with self._lock:
            if project_id not in self._projects:
                raise KeyError(project_id)
            self._scenarios[project_id][scenario.name] = scenario
        return scenario

    def get_goals(self, project_id: str) -> ProjectGoals:
        return self._goals.get(project_id, ProjectGoals())

    def set_goals(self, project_id: str, goals: ProjectGoals) -> ProjectGoals:
        with self._lock:
            if project_id not in self._projects:
                raise KeyError(project_id)
            self._goals[project_id] = goals
        return goals

    def find_run(self, project_id: str, number: int, cache_key: str) -> dict[str, Any] | None:
        saved = self._runs.get(cache_key)
        if saved is None or saved[:2] != (project_id, number):
            return None
        return copy.deepcopy(saved[2])

    def save_run(
        self,
        project_id: str,
        number: int,
        cache_key: str,
        params: dict[str, Any],  # en memoria no se usan: Postgres los guarda en runs.params
        run: dict[str, Any],
        engine_version: str,  # y en runs.engine_version
    ) -> None:
        if self.get_version(project_id, number) is None:
            raise KeyError(f"{project_id} v{number}")
        with self._lock:
            self._runs.setdefault(cache_key, (project_id, number, copy.deepcopy(run)))

    def save_report(self, project_id: str, report: dict[str, Any]) -> None:
        if project_id not in self._projects:
            raise KeyError(project_id)
        with self._lock:
            self._reports[report["id"]] = (project_id, copy.deepcopy(report))

    def list_reports(self, project_id: str) -> list[ReportSummary]:
        with self._lock:
            mine = [r for pid, r in self._reports.values() if pid == project_id]
        # del más nuevo al más viejo; con la misma fecha, el último guardado primero
        return [report_summary(r) for r in sorted(reversed(mine), key=lambda r: r["created_at"], reverse=True)]

    def get_report(self, project_id: str, report_id: str) -> dict[str, Any] | None:
        saved = self._reports.get(report_id)
        return copy.deepcopy(saved[1]) if saved is not None and saved[0] == project_id else None

    def delete_report(self, project_id: str, report_id: str) -> bool:
        with self._lock:
            saved = self._reports.get(report_id)
            if saved is None or saved[0] != project_id:
                return False
            del self._reports[report_id]
            return True

    def save_installation(self, installation_id: int, owner: str | None, account_login: str) -> None:
        with self._lock:
            self._installations[installation_id] = (owner, account_login, False)

    def list_installations(self, owner: str | None, *, revoked: bool = False) -> list[GitHubInstallation]:
        with self._lock:
            return [
                GitHubInstallation(i, login)
                for i, (o, login, is_revoked) in self._installations.items()
                if o == owner and is_revoked == revoked
            ]

    def revoke_installation(self, installation_id: int) -> None:
        with self._lock:
            entry = self._installations.get(installation_id)
            if entry is not None:
                owner, login, _ = entry
                self._installations[installation_id] = (owner, login, True)

    def connect_repo(
        self, owner: str | None, installation_id: int, repo_id: int, full_name: str, default_branch: str
    ) -> str:
        with self._lock:
            return self._connections.setdefault((owner, repo_id), uuid.uuid4().hex[:12])

    def create_attachment(self, attachment: Attachment) -> Attachment:
        with self._lock:
            self._attachments[attachment.id] = attachment
        return attachment

    def get_attachment(self, attachment_id: str, owner: str) -> Attachment | None:
        a = self._attachments.get(attachment_id)
        return a if a is not None and a.owner == owner else None

    def list_attachments(self, project_id: str, owner: str, include_pending: bool = False) -> list[Attachment]:
        now = datetime.now(UTC)
        mine = [
            a
            for a in self._attachments.values()
            if a.project_id == project_id
            and a.owner == owner
            and not a.expired(now)
            and (include_pending or a.status == "ready")
        ]
        return sorted(mine, key=lambda a: a.created_at)

    def mark_attachment_ready(self, attachment_id: str, owner: str, size: int) -> None:
        with self._lock:
            a = self._attachments.get(attachment_id)
            if a is not None and a.owner == owner:
                self._attachments[attachment_id] = replace(a, status="ready", bytes=size)

    def delete_attachment(self, attachment_id: str, owner: str) -> None:
        with self._lock:
            a = self._attachments.get(attachment_id)
            if a is not None and a.owner == owner:
                del self._attachments[attachment_id]

    def expired_attachments(self, owner: str | None, limit: int = 100) -> list[Attachment]:
        now = datetime.now(UTC)
        gone = [a for a in self._attachments.values() if a.expired(now) and (owner is None or a.owner == owner)]
        return sorted(gone, key=lambda a: a.expires_at)[:limit]
