"""Proyectos y versiones del editor.

Cada proyecto parte con la **v1** (el modelo del repo) y cada cambio guardado es una versión nueva
con su antecesora, como un commit. Por ahora viven en memoria (se pierden al reiniciar la API):
``ProjectStore`` es la interfaz que la persistencia en Postgres (JAJ-56) implementa sin cambiar
las rutas.
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
    model: dict[str, Any]


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

    def get(self, project_id: str) -> Project | None: ...

    def list(self) -> list[Project]: ...

    def add_version(
        self, project_id: str, model: dict[str, Any], origin: Origin, parent: int | None, note: str | None
    ) -> Version: ...


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class InMemoryProjectStore:
    """Guarda copias de los modelos, así quien llama puede seguir editando el suyo sin afectarlas."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._lock = threading.Lock()  # las rutas def corren en el pool de hilos de FastAPI

    def create(self, name: str, model: dict[str, Any], sample: str | None) -> Project:
        project = Project(id=uuid.uuid4().hex[:12], name=name, sample=sample, created_at=_now())
        project.versions.append(Version(1, "repo", None, "Extraída del repo", project.created_at, copy.deepcopy(model)))
        with self._lock:
            self._projects[project.id] = project
        return project

    def get(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

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
