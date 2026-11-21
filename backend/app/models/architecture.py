"""Modelo de arquitectura que recibe el motor: el JSON ``branchpoint.model/v1`` de JAJ-45.

``load_model`` lee ese JSON y deja solo lo que el motor necesita, con nombres claros:

* ``api``: réplicas, vCPU, workers, hilos por worker y latencia de red.
* ``db``: vCPU, conexiones máximas y pool por worker (tamaño + overflow, timeout de espera).
* ``endpoints``: peso en el tráfico, si es async, CPU base de la API y los pasos en orden.
* ``scenarios``: req/s de cada escenario (pico normal, CyberDay ×20).
* ``queues``: colas con workers asíncronos (opcional, ``deployment.queues``).

Cada número del JSON viene como ``{"value", "unit", "label", "source", "date"}``; aquí se usa
``value``. La procedencia sigue en el JSON original para mostrarla en la app.

Campos opcionales que el motor entiende y que build_model.py (JAJ-45) todavía no genera:

* En un paso ``cache``: ``hit_ratio`` (0 a 1) y ``on_miss`` (pasos que se hacen solo si falla,
  ej. la consulta a la DB). Sin ``on_miss``, la caché es solo una espera, como antes.
* En un paso ``background``: ``queue`` (nombre de la cola). Si hay una sola cola, se usa esa.
* ``deployment.queues.<nombre>``: ``workers`` (trabajos en paralelo), ``max_length`` (largo
  máximo de la cola; al superarlo, encolar falla) y ``job_steps`` (pasos de cada trabajo).
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

# Recursos que nombra el modelo v1 en cada paso. La caché (Redis), las llamadas externas y el
# acto de encolar no ocupan un recurso compartido: el motor los trata como espera.
RESOURCE_DB_CONNECTION = "db_connection"
RESOURCE_API_CPU = "api_cpu"
RESOURCE_CACHE = "cache"
RESOURCE_BACKGROUND = "background"


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
    # solo caché: probabilidad de acierto y pasos si falla (None = la caché es solo una espera)
    hit_ratio: float | None = None
    on_miss: tuple[Step, ...] | None = None
    # solo background: cola donde se encola el trabajo (None = no se simula el worker)
    queue: str | None = None
    infer_queue: bool = True  # compatibilidad con modelos que omiten el nombre cuando solo hay una cola


def walk_steps(steps: tuple[Step, ...]) -> Iterator[Step]:
    """Todos los pasos, incluidos los de ``on_miss``."""
    for s in steps:
        yield s
        if s.on_miss:
            yield from walk_steps(s.on_miss)


@dataclass(frozen=True)
class Endpoint:
    id: str
    weight: float
    is_async: bool
    base_cpu_ms: float  # CPU de la API propia del framework, sin contar los pasos de CPU
    steps: tuple[Step, ...]

    @property
    def uses_db(self) -> bool:
        return any(s.resource == RESOURCE_DB_CONNECTION for s in walk_steps(self.steps))


@dataclass(frozen=True)
class QueueDeployment:
    """Cola con workers asíncronos (ej. Celery, RQ, arq). Sus trabajos no usan la API ni su pool."""

    name: str
    workers: int  # trabajos en paralelo
    max_length: int | None  # trabajos esperando como máximo; None = sin límite
    job_steps: tuple[Step, ...]


@dataclass(frozen=True)
class ApiDeployment:
    replicas: int
    vcpu: float
    workers: int
    threads_per_worker: int
    latency_ms: float
    # cuántas veces más lento es 1 vCPU del plan que el núcleo de calibración (JAJ-46); 1 = sin ajuste
    core_factor: float = 1.0
    processor: str | None = None

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
    core_factor: float = 1.0  # como en ApiDeployment: multiplica el tiempo de cada consulta
    processor: str | None = None
    plan: str | None = None
    # instancias con créditos de CPU (db.t4g.*): vCPU que aguanta con carga sostenida
    sustained_vcpu: float | None = None
    # con pooler (``deployment.db.pooler``), conexiones de clientes que acepta; None = sin pooler
    pooler_connections: int | None = None


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
    queues: dict[str, QueueDeployment] = field(default_factory=dict)

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
        core_factor=_core_factor(api_raw, "deployment.api"),
        processor=_processor(api_raw),
    )
    pool = db_raw.get("pool_per_worker", {})
    db = DbDeployment(
        vcpu=float(value(db_raw["vcpu"], 1)),
        max_connections=_opt_int(value(db_raw.get("max_connections"))),
        pool_per_worker=int(value(pool.get("pool_size"), 5)) + int(value(pool.get("max_overflow"), 0)),
        pool_timeout_s=_opt_float(value(pool.get("pool_timeout_s"))),
        core_factor=_core_factor(db_raw, "deployment.db"),
        processor=_processor(db_raw),
        plan=db_raw.get("plan"),
        sustained_vcpu=_opt_float(value(db_raw.get("cpu_credits", {}).get("sustained_vcpu"))),
        pooler_connections=_opt_int(value(db_raw["pooler"].get("client_connections"))) if "pooler" in db_raw else None,
    )
    if db.sustained_vcpu is not None and not 0 < db.sustained_vcpu <= db.vcpu:
        raise ValueError(
            f"deployment.db.cpu_credits.sustained_vcpu debe estar entre 0 y los vCPU ({db.vcpu}); es {db.sustained_vcpu}"
        )
    if "pooler" in db_raw and db.pooler_connections is None:
        raise ValueError("deployment.db.pooler necesita client_connections (conexiones de clientes que acepta)")

    queues = {
        name: QueueDeployment(
            name=name,
            workers=int(value(q.get("workers"), 1)),
            max_length=_opt_int(value(q.get("max_length"))),
            job_steps=tuple(_load_step(s, f"cola {name}", warnings) for s in q.get("job_steps", [])),
        )
        for name, q in dep.get("queues", {}).items()
    }
    for q in queues.values():
        if q.workers < 1:
            raise ValueError(f"cola {q.name}: workers debe ser al menos 1")

    endpoints = tuple(_load_endpoint(e, queues, warnings) for e in raw["endpoints"])
    total = sum(e.weight for e in endpoints)
    if total <= 0:
        raise ValueError("Los pesos de los endpoints suman 0: no hay tráfico que simular")
    endpoints = tuple(Endpoint(e.id, e.weight / total, e.is_async, e.base_cpu_ms, e.steps) for e in endpoints)

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
        queues=queues,
    )


def _load_step(s: dict[str, Any], where: str, warnings: list[str]) -> Step:
    t = value(s.get("time"))
    if t is None:
        warnings.append(f"{where}: el paso '{s.get('kind')}' en {s.get('at')} no tiene tiempo; se usa 0 ms")
        t = 0.0
    resource = s.get("resource")
    hit_ratio, on_miss = None, None
    if resource == RESOURCE_CACHE and "on_miss" in s:
        on_miss = tuple(_load_step(m, where, warnings) for m in s["on_miss"])
        hit_ratio = _opt_float(value(s.get("hit_ratio")))
        if hit_ratio is None:
            warnings.append(
                f"{where}: la caché en {s.get('at')} no tiene tasa de aciertos; se simula con 0 % "
                f"(todas fallan, el peor caso)."
            )
            hit_ratio = 0.0
        if not 0.0 <= hit_ratio <= 1.0:
            raise ValueError(f"{where}: hit_ratio debe estar entre 0 y 1 (es {hit_ratio})")
    return Step(
        kind=s.get("kind", "?"),
        resource=resource,
        time_ms=float(t),
        repeat=max(1, int(value(s.get("repeat"), 1))),
        shape=s.get("shape"),
        at=s.get("at"),
        hit_ratio=hit_ratio,
        on_miss=on_miss,
        queue=s.get("queue"),
        infer_queue=s.get("infer_queue", True),
    )


def _resolve_queue(step: Step, queues: dict[str, QueueDeployment], where: str, warnings: list[str]) -> Step:
    """Asigna la cola a un paso ``background``. Sin cola configurada, el worker no se simula."""
    if step.on_miss:
        step = replace(step, on_miss=tuple(_resolve_queue(m, queues, where, warnings) for m in step.on_miss))
    if step.resource != RESOURCE_BACKGROUND:
        return step
    name = step.queue
    if name is None and step.infer_queue and len(queues) == 1:
        name = next(iter(queues))
    if name is None or name not in queues:
        warnings.append(
            f"{where}: el trabajo en segundo plano de {step.at} no tiene cola configurada "
            f"(deployment.queues); solo se simula el encolar, no el worker."
        )
        name = None
    return replace(step, queue=name)


def _load_endpoint(e: dict[str, Any], queues: dict[str, QueueDeployment], warnings: list[str]) -> Endpoint:
    steps = [_resolve_queue(_load_step(s, e["id"], warnings), queues, e["id"], warnings) for s in e.get("steps", [])]
    # api_cpu_ms del modelo incluye los pasos de CPU (ej. hash); la CPU base es el resto.
    # Solo cuentan los pasos que siempre se hacen (no los de on_miss).
    cpu_steps = sum(s.time_ms * s.repeat for s in steps if s.resource == RESOURCE_API_CPU)
    base_cpu = max(0.0, float(value(e.get("api_cpu_ms"), 0.0)) - cpu_steps)
    return Endpoint(
        id=e["id"],
        weight=float(value(e.get("weight"), 0.0)),
        is_async=bool(e.get("async", False)),
        base_cpu_ms=base_cpu,
        steps=tuple(steps),
    )


def _core_factor(raw: dict[str, Any], where: str) -> float:
    """``cpu_core_factor`` del modelo (JAJ-47). Sin él, los tiempos se usan tal cual (factor 1)."""
    factor = _opt_float(value(raw.get("cpu_core_factor")))
    if factor is None:
        return 1.0
    if factor <= 0:
        raise ValueError(f"{where}.cpu_core_factor debe ser mayor que 0 (es {factor})")
    return factor


def _processor(raw: dict[str, Any]) -> str | None:
    f = raw.get("cpu_core_factor")
    return f.get("processor") if isinstance(f, dict) else None


def _opt_int(x: Any) -> int | None:
    return None if x is None else int(x)


def _opt_float(x: Any) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)
