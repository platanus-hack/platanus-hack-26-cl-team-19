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
    owner: str | None = None  # auth.users.id de quien lo creó; None sin login (JAJ-78)

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

    def rate_for(self, model: dict[str, Any]) -> float:
        """Las req/s del escenario para el modelo de una versión. ``ValueError`` si es un
        multiplicador y el modelo no trae ``traffic.peak_rps``."""
        if self.rps is not None:
            return self.rps
        peak = ((model.get("traffic") or {}).get("peak_rps") or {}).get("value")
        if not peak or peak <= 0:
            raise ValueError(
                f"El escenario '{self.name}' es ×{self.multiplier:g} el pico, pero el modelo no tiene "
                "traffic.peak_rps. Agrega el pico al modelo o define el escenario con rps."
            )
        return float(peak) * self.multiplier


def scenarios_from_model(model: dict[str, Any]) -> list[ProjectScenario]:
    """Los escenarios de ``traffic.scenarios`` del modelo, para cargarlos al crear un proyecto.

    Se guarda el multiplicador cuando lo hay: así la tasa se recalcula con el pico de cada versión
    (decisión 4 del README de ``app/db``). Si no, las req/s.
    """
    scenarios = []
    for name, sc in ((model.get("traffic") or {}).get("scenarios") or {}).items():
        multiplier = (sc.get("multiplier") or {}).get("value")
        rps = (sc.get("rps") or {}).get("value")
        if multiplier is not None and multiplier > 0:
            scenarios.append(ProjectScenario(name, float(multiplier), None))
        elif rps is not None and rps > 0:
            scenarios.append(ProjectScenario(name, None, float(rps)))
    return scenarios


class ProjectStore(Protocol):
    """Proyectos, versiones, escenarios y runs.

    **Dueños (JAJ-78).** ``create``, ``get`` y ``list`` reciben el ``owner`` (el id del usuario, o
    ``None`` sin login), y ``get`` devuelve ``None`` si el proyecto es de otro. Los demás métodos
    reciben un ``project_id`` que la ruta ya validó con ``get``: toda ruta de un proyecto pasa
    primero por ``get(project_id, owner)``.
    """

    def create(self, name: str, model: dict[str, Any], sample: str | None, owner: str | None = None) -> Project: ...

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
        self, project_id: str, model: dict[str, Any], origin: Origin, parent: int | None, note: str | None
    ) -> Version: ...

    def list_scenarios(self, project_id: str) -> list[ProjectScenario]:
        """Los escenarios del proyecto, por nombre (JAJ-76)."""
        ...

    def upsert_scenario(self, project_id: str, scenario: ProjectScenario) -> ProjectScenario:
        """Crea el escenario o reemplaza el que tiene ese nombre (JAJ-76)."""
        ...

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


class OwnedStore:
    """El store visto por un usuario (JAJ-78): ``create``, ``get`` y ``list`` llevan su ``owner``
    puesto, y el resto pasa directo. Lo arma ``get_store`` en cada request, así ninguna ruta de
    proyectos puede olvidarse de filtrar por dueño."""

    def __init__(self, store: ProjectStore, owner: str | None) -> None:
        self._store = store
        self.owner = owner

    def create(self, name: str, model: dict[str, Any], sample: str | None) -> Project:
        return self._store.create(name, model, sample, self.owner)

    def get(self, project_id: str) -> Project | None:
        return self._store.get(project_id, self.owner)

    def list(self) -> list[Project]:
        return self._store.list(self.owner)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class InMemoryProjectStore:
    """Guarda copias de los modelos, así quien llama puede seguir editando el suyo sin afectarlas."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}
        self._runs: dict[str, dict[str, Any]] = {}  # cache_key → Run como dict (JAJ-75)
        self._scenarios: dict[str, dict[str, ProjectScenario]] = {}  # proyecto → nombre → escenario
        self._lock = threading.Lock()  # las rutas def corren en el pool de hilos de FastAPI

    def create(self, name: str, model: dict[str, Any], sample: str | None, owner: str | None = None) -> Project:
        project = Project(id=uuid.uuid4().hex[:12], name=name, sample=sample, created_at=_now(), owner=owner)
        project.versions.append(Version(1, "repo", None, "Extraída del repo", project.created_at, copy.deepcopy(model)))
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
        self, project_id: str, model: dict[str, Any], origin: Origin, parent: int | None, note: str | None
    ) -> Version:
        with self._lock:
            project = self._projects[project_id]
            version = Version(len(project.versions) + 1, origin, parent, note, _now(), copy.deepcopy(model))
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
