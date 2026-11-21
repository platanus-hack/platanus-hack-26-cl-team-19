"""Modelo de arquitectura que recibe el motor: el JSON ``branchpoint.model/v1`` de JAJ-45.

``load_model`` lee ese JSON y deja solo lo que el motor necesita, con nombres claros:

* ``api``: réplicas, vCPU, workers, hilos por worker y latencia de red.
* ``db``: vCPU, conexiones máximas y pool por worker (tamaño + overflow, timeout de espera).
* ``endpoints``: peso en el tráfico, si es async, CPU base de la API y los pasos en orden.
* ``scenarios``: req/s de cada escenario (pico normal, CyberDay ×20).

Cada número del JSON viene como ``{"value", "unit", "label", "source", "date"}``; aquí se usa
``value``. La procedencia sigue en el JSON original para mostrarla en la app.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Recursos que nombra el modelo v1 en cada paso. Los demás (caché, llamadas externas, encolar)
# no ocupan un recurso compartido: el motor los trata como espera.
RESOURCE_DB_CONNECTION = "db_connection"
RESOURCE_API_CPU = "api_cpu"


def value(x: Any, default: Any = None) -> Any:
    """Valor de un número del modelo v1 (``{"value": ...}``) o el propio valor si es escalar."""
    if isinstance(x, dict):
        return x.get("value", default)
    return default if x is None else x


@dataclass(frozen=True)
class Step:
    """Un paso de un endpoint: una consulta, CPU de la API (ej. hash de contraseña) u otra espera."""

    kind: str
    resource: str | None
    time_ms: float
    repeat: int = 1
    shape: str | None = None
    at: str | None = None


@dataclass(frozen=True)
class Endpoint:
    id: str
    weight: float
    is_async: bool
    base_cpu_ms: float  # CPU de la API propia del framework, sin contar los pasos de CPU
    steps: tuple[Step, ...]

    @property
    def uses_db(self) -> bool:
        return any(s.resource == RESOURCE_DB_CONNECTION for s in self.steps)


@dataclass(frozen=True)
class ApiDeployment:
    replicas: int
    vcpu: float
    workers: int
    threads_per_worker: int
    latency_ms: float

    @property
    def cores(self) -> float:
        """Núcleos útiles: cada worker es un proceso con su GIL, así que no usa más de 1 vCPU."""
        return min(self.workers, self.vcpu) * self.replicas

    @property
    def threads(self) -> int:
        """Hilos para endpoints ``def`` (síncronos): el threadpool de cada worker."""
        return self.threads_per_worker * self.workers * self.replicas


@dataclass(frozen=True)
class DbDeployment:
    vcpu: float
    max_connections: int | None
    pool_per_worker: int  # pool_size + max_overflow de cada worker
    pool_timeout_s: float | None


@dataclass(frozen=True)
class Scenario:
    name: str
    rps: float


@dataclass(frozen=True)
class ArchitectureModel:
    name: str
    api: ApiDeployment
    db: DbDeployment
    endpoints: tuple[Endpoint, ...]
    scenarios: dict[str, Scenario]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def app_connections(self) -> int:
        """Conexiones que puede abrir la app: pool por worker × workers × réplicas."""
        return self.db.pool_per_worker * self.api.workers * self.api.replicas

    def scenario(self, name: str) -> Scenario:
        if name not in self.scenarios:
            raise KeyError(f"El modelo no tiene el escenario '{name}'. Hay: {', '.join(self.scenarios)}")
        return self.scenarios[name]


def load_model(source: str | Path | dict[str, Any]) -> ArchitectureModel:
    """Lee un modelo ``branchpoint.model/v1`` desde un archivo o un dict ya cargado."""
    raw = source if isinstance(source, dict) else json.loads(Path(source).read_text(encoding="utf-8"))
    schema = raw.get("schema", "")
    if not schema.startswith("branchpoint.model/v1"):
        raise ValueError(f"Esquema no soportado: '{schema}' (se espera branchpoint.model/v1)")
    warnings: list[str] = []

    dep = raw["deployment"]
    api_raw, db_raw = dep["api"], dep["db"]
    api = ApiDeployment(
        replicas=int(value(api_raw["replicas"], 1)),
        vcpu=float(value(api_raw["vcpu"], 1)),
        workers=int(value(api_raw["workers"], 1)),
        threads_per_worker=int(value(api_raw.get("threads_per_worker"), 40)),
        latency_ms=float(value(api_raw.get("latency_ms"), 0.0)),
    )
    pool = db_raw.get("pool_per_worker", {})
    db = DbDeployment(
        vcpu=float(value(db_raw["vcpu"], 1)),
        max_connections=_opt_int(value(db_raw.get("max_connections"))),
        pool_per_worker=int(value(pool.get("pool_size"), 5)) + int(value(pool.get("max_overflow"), 0)),
        pool_timeout_s=_opt_float(value(pool.get("pool_timeout_s"))),
    )

    endpoints = tuple(_load_endpoint(e, warnings) for e in raw["endpoints"])
    total = sum(e.weight for e in endpoints)
    if total <= 0:
        raise ValueError("Los pesos de los endpoints suman 0: no hay tráfico que simular")
    endpoints = tuple(
        Endpoint(e.id, e.weight / total, e.is_async, e.base_cpu_ms, e.steps) for e in endpoints
    )

    scenarios = {
        name: Scenario(name, float(value(sc["rps"])))
        for name, sc in raw.get("traffic", {}).get("scenarios", {}).items()
        if value(sc.get("rps")) is not None
    }
    return ArchitectureModel(
        name=raw.get("repo", {}).get("path", "modelo"),
        api=api,
        db=db,
        endpoints=endpoints,
        scenarios=scenarios,
        warnings=tuple(warnings),
    )


def _load_endpoint(e: dict[str, Any], warnings: list[str]) -> Endpoint:
    steps = []
    for s in e.get("steps", []):
        t = value(s.get("time"))
        if t is None:
            warnings.append(f"{e['id']}: el paso '{s.get('kind')}' en {s.get('at')} no tiene tiempo; se usa 0 ms")
            t = 0.0
        steps.append(
            Step(
                kind=s.get("kind", "?"),
                resource=s.get("resource"),
                time_ms=float(t),
                repeat=max(1, int(value(s.get("repeat"), 1))),
                shape=s.get("shape"),
                at=s.get("at"),
            )
        )
    # api_cpu_ms del modelo incluye los pasos de CPU (ej. hash); la CPU base es el resto
    cpu_steps = sum(s.time_ms * s.repeat for s in steps if s.resource == RESOURCE_API_CPU)
    base_cpu = max(0.0, float(value(e.get("api_cpu_ms"), 0.0)) - cpu_steps)
    return Endpoint(
        id=e["id"],
        weight=float(value(e.get("weight"), 0.0)),
        is_async=bool(e.get("async", False)),
        base_cpu_ms=base_cpu,
        steps=tuple(steps),
    )


def _opt_int(x: Any) -> int | None:
    return None if x is None else int(x)


def _opt_float(x: Any) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)
