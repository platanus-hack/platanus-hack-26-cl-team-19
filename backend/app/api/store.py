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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

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


@dataclass
class Project:
    id: str
    name: str
    sample: str | None  # id del modelo de ejemplo del que salió, si salió de uno
    created_at: str
    versions: list[Version] = field(default_factory=list)

    def version(self, number: int) -> Version | None:
        return self.versions[number - 1] if 1 <= number <= len(self.versions) else None


class ProjectStore(Protocol):
    def create(self, name: str, model: dict[str, Any], sample: str | None) -> Project: ...

    def get(self, project_id: str) -> Project | None:
        """El proyecto con el historial de versiones. Las versiones pueden venir sin ``model``."""
        ...

    def get_version(self, project_id: str, number: int) -> Version | None:
        """Una versión con su ``model``."""
        ...

    def list(self) -> list[Project]: ...

    def add_version(
        self, project_id: str, model: dict[str, Any], origin: Origin, parent: int | None, note: str | None
    ) -> Version: ...

    def find_run(self, cache_key: str) -> dict[str, Any] | None:
        """El ``Run`` guardado con esa clave (como dict ``branchpoint.run/v1``), o ``None`` (JAJ-75)."""
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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class InMemoryProjectStore:
    """Guarda copias de los modelos, así quien llama puede seguir editando el suyo sin afectarlas."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._runs: dict[str, dict[str, Any]] = {}  # cache_key → Run como dict (JAJ-75)
        self._lock = threading.Lock()  # las rutas def corren en el pool de hilos de FastAPI

    def create(self, name: str, model: dict[str, Any], sample: str | None) -> Project:
        project = Project(id=uuid.uuid4().hex[:12], name=name, sample=sample, created_at=_now())
        project.versions.append(Version(1, "repo", None, "Extraída del repo", project.created_at, copy.deepcopy(model)))
        with self._lock:
            self._projects[project.id] = project
        return project

    def get(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    def get_version(self, project_id: str, number: int) -> Version | None:
        project = self._projects.get(project_id)
        return project.version(number) if project is not None else None

    def list(self) -> list[Project]:
        return sorted(self._projects.values(), key=lambda p: p.created_at, reverse=True)

    def add_version(
        self, project_id: str, model: dict[str, Any], origin: Origin, parent: int | None, note: str | None
    ) -> Version:
        with self._lock:
            project = self._projects[project_id]
            version = Version(len(project.versions) + 1, origin, parent, note, _now(), copy.deepcopy(model))
            project.versions.append(version)
        return version

    def find_run(self, cache_key: str) -> dict[str, Any] | None:
        run = self._runs.get(cache_key)
        return copy.deepcopy(run) if run is not None else None

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
            self._runs.setdefault(cache_key, copy.deepcopy(run))
