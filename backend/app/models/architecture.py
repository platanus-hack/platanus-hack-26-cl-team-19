"""Modelo de arquitectura que recibe el motor: el JSON ``branchpoint.model/v1`` de JAJ-45.

``load_model`` lee ese JSON y deja solo lo que el motor necesita, con nombres claros:

* ``api``: réplicas, vCPU, workers, hilos por worker y latencia de red.
* ``db``: vCPU, conexiones máximas y pool por worker (tamaño + overflow, timeout de espera).
* ``endpoints``: peso en el tráfico, si es async, CPU base de la API y los pasos en orden.
* ``scenarios``: req/s de cada escenario (pico normal, CyberDay ×20).
* ``queues``: colas con workers asíncronos (opcional, ``deployment.queues``).

Cada número del JSON viene como ``{"value", "unit", "label", "source", "date"}``; aquí se usa
``value``. La procedencia sigue en el JSON original para mostrarla en la app. También se acepta el
número solo (``"replicas": 2``), en todos lados; quien lea el JSON original usa ``value()``.

``load_model`` es el único lugar donde se valida el modelo (JAJ-101): forma y rangos, con el campo en
el mensaje. Lo que pasa por aquí ya no hace fallar al motor, al costo ni a las rutas con un 500.

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
# JAJ-140: formas de consulta que son lecturas. Con réplicas de lectura, estas van a una réplica; las
# escrituras (commit, stage) y las desconocidas (unknown) se quedan en la primaria.
READ_SHAPES = frozenset({"pk", "lookup", "range", "count", "count_all", "scan"})


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
    service: str | None = None  # nombre del destino de un paso externo


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
    # ida y vuelta de red API ↔ DB por consulta (JAJ-143): la conexión queda tomada, la CPU de la DB no
    network_rtt_ms: float = 0.0
    # JAJ-140: réplicas de lectura (``deployment.db.read_replicas``). Cada una tiene sus vCPU y un pool
    # de conexiones del mismo tamaño que el de la primaria (tope: sus conexiones máximas)
    read_replicas: int = 0
    replica_vcpu: float | None = None
    replica_core_factor: float = 1.0
    replica_max_connections: int | None = None
    replica_sustained_vcpu: float | None = None  # réplicas con créditos de CPU, como ``sustained_vcpu``


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
    secondary_services: frozenset[str] = frozenset()

    @property
    def app_connections(self) -> int:
        """Conexiones que puede abrir la app: pool por worker × workers × réplicas."""
        return self.db.pool_per_worker * self.api.workers * self.api.replicas

    def scenario(self, name: str) -> Scenario:
        if name not in self.scenarios:
            raise KeyError(f"El modelo no tiene el escenario '{name}'. Hay: {', '.join(self.scenarios)}")
        return self.scenarios[name]


SCHEMA = "branchpoint.model/v1"


def load_model(source: str | Path | dict[str, Any]) -> ArchitectureModel:
    """Lee un modelo ``branchpoint.model/v1`` desde un archivo o un dict ya cargado.

    Es el único lugar donde se valida el modelo (JAJ-101): la forma (objetos, listas, números) y los
    rangos (réplicas ≥ 1, tiempos ≥ 0…). Lo que no calza da ``ValueError`` con el campo en el mensaje
    (``deployment.api.replicas debe ser al menos 1 (es 0)``), y un campo obligatorio que falta da
    ``KeyError`` con su ruta. La API responde ambos como 422 ``invalid_model``.

    Los números se aceptan con procedencia (``{"value": 2, "label": …}``) o escalares (``2``), en
    todos lados: quien lea el JSON original debe usar ``value()``. Un texto (``"2"``) no es un número.
    """
    raw = source if isinstance(source, dict) else json.loads(Path(source).read_text(encoding="utf-8"))
    _obj(raw, "el modelo")
    schema = raw.get("schema", "")
    if schema != SCHEMA:
        raise ValueError(f"Esquema no soportado: '{schema}' (se espera {SCHEMA})")
    warnings: list[str] = []

    dep = _obj(_need(raw, "deployment"), "deployment")
    api_raw = _obj(_need(dep, "api", "deployment."), "deployment.api")
    db_raw = _obj(_need(dep, "db", "deployment."), "deployment.db")
    w = "deployment.api"
    _need(api_raw, "replicas", f"{w}.")
    _need(api_raw, "workers", f"{w}.")
    _need(api_raw, "vcpu", f"{w}.")
    _number(api_raw.get("memory_gb"), f"{w}.memory_gb", gt=0)  # solo la lee el costo (JAJ-72)
    api = ApiDeployment(
        replicas=_number(api_raw["replicas"], f"{w}.replicas", default=1, integer=True, minimum=1),
        vcpu=float(_number(api_raw["vcpu"], f"{w}.vcpu", default=1, gt=0)),
        workers=_number(api_raw["workers"], f"{w}.workers", default=1, integer=True, minimum=1),
        threads_per_worker=_number(
            api_raw.get("threads_per_worker"), f"{w}.threads_per_worker", default=40, integer=True, minimum=1
        ),
        latency_ms=float(_number(api_raw.get("latency_ms"), f"{w}.latency_ms", default=0.0, minimum=0)),
        core_factor=_core_factor(api_raw, w),
        processor=_processor(api_raw),
    )
    w = "deployment.db"
    _need(db_raw, "vcpu", f"{w}.")
    pool = _obj(db_raw.get("pool_per_worker", {}), f"{w}.pool_per_worker")
    pool_size = _number(pool.get("pool_size"), f"{w}.pool_per_worker.pool_size", default=5, integer=True, minimum=0)
    overflow = _number(
        pool.get("max_overflow"), f"{w}.pool_per_worker.max_overflow", default=0, integer=True, minimum=0
    )
    if pool_size + overflow < 1:
        raise ValueError(f"{w}.pool_per_worker: pool_size + max_overflow debe ser al menos 1 (es 0)")
    credits = _obj(db_raw.get("cpu_credits", {}), f"{w}.cpu_credits")
    pooler = _obj(db_raw["pooler"], f"{w}.pooler") if "pooler" in db_raw else None
    replicas = _obj(db_raw["read_replicas"], f"{w}.read_replicas") if "read_replicas" in db_raw else None
    if replicas is not None:
        _need(replicas, "count", f"{w}.read_replicas.")
    db = DbDeployment(
        vcpu=float(_number(db_raw["vcpu"], f"{w}.vcpu", default=1, gt=0)),
        # 0 conexiones no es "sin límite": sin límite es no declararlo (o null)
        max_connections=_number(db_raw.get("max_connections"), f"{w}.max_connections", integer=True, minimum=1),
        pool_per_worker=pool_size + overflow,
        pool_timeout_s=_opt_float(_number(pool.get("pool_timeout_s"), f"{w}.pool_per_worker.pool_timeout_s", gt=0)),
        core_factor=_core_factor(db_raw, w),
        processor=_processor(db_raw),
        plan=db_raw.get("plan"),
        sustained_vcpu=_opt_float(_number(credits.get("sustained_vcpu"), f"{w}.cpu_credits.sustained_vcpu")),
        network_rtt_ms=float(_number(db_raw.get("network_rtt_ms"), f"{w}.network_rtt_ms", default=0.0, minimum=0)),
        pooler_connections=None
        if pooler is None
        else _number(pooler.get("client_connections"), f"{w}.pooler.client_connections", integer=True, minimum=1),
        read_replicas=0
        if replicas is None
        else _number(replicas["count"], f"{w}.read_replicas.count", integer=True, minimum=1),
        replica_vcpu=None
        if replicas is None
        else float(_number(replicas.get("vcpu"), f"{w}.read_replicas.vcpu", default=value(db_raw["vcpu"]), gt=0)),
        replica_core_factor=1.0 if replicas is None else _core_factor(replicas, f"{w}.read_replicas"),
        replica_max_connections=None
        if replicas is None
        else _number(replicas.get("max_connections"), f"{w}.read_replicas.max_connections", integer=True, minimum=1),
        replica_sustained_vcpu=None
        if replicas is None
        else _opt_float(
            _number(
                _obj(replicas.get("cpu_credits", {}), f"{w}.read_replicas.cpu_credits").get("sustained_vcpu"),
                f"{w}.read_replicas.cpu_credits.sustained_vcpu",
                gt=0,
            )
        ),
    )
    if db.sustained_vcpu is not None and not 0 < db.sustained_vcpu <= db.vcpu:
        raise ValueError(
            f"deployment.db.cpu_credits.sustained_vcpu debe estar entre 0 y los vCPU ({db.vcpu}); es {db.sustained_vcpu}"
        )
    if pooler is not None and db.pooler_connections is None:
        raise ValueError("deployment.db.pooler necesita client_connections (conexiones de clientes que acepta)")

    queues = {}
    for name, q in _obj(dep.get("queues", {}), "deployment.queues").items():
        w = f"deployment.queues.{name}"
        _obj(q, w)
        queues[name] = QueueDeployment(
            name=name,
            workers=_number(q.get("workers"), f"{w}.workers", default=1, integer=True, minimum=1),
            # un largo máximo de 0 rechaza todo aunque haya workers libres: sin límite es null
            max_length=_number(q.get("max_length"), f"{w}.max_length", integer=True, minimum=1),
            job_steps=tuple(
                _load_step(s, f"cola {name}", warnings, f"{w}.job_steps[{i}]")
                for i, s in enumerate(_list(q.get("job_steps", []), f"{w}.job_steps"))
            ),
        )
    # una cola que no existe se trata como en un endpoint: solo se simula el encolar (antes, KeyError
    # al simular). Sin inferir la única cola: haría que un trabajo se encole a sí mismo.
    queues = {
        name: replace(
            q, job_steps=tuple(_resolve_queue(s, queues, f"cola {name}", warnings, infer=False) for s in q.job_steps)
        )
        for name, q in queues.items()
    }
    _check_queue_cycles(queues)
    for q in queues.values():
        _check_steps_per_request(q.job_steps, f"cola {q.name}")

    endpoints = tuple(
        _load_endpoint(_obj(e, f"endpoints[{i}]"), queues, warnings, f"endpoints[{i}]")
        for i, e in enumerate(_list(_need(raw, "endpoints"), "endpoints"))
    )
    for e in endpoints:
        _check_steps_per_request(e.steps, e.id)
    total = sum(e.weight for e in endpoints)
    if total <= 0:
        raise ValueError("Los pesos de los endpoints suman 0: no hay tráfico que simular")
    endpoints = tuple(Endpoint(e.id, e.weight / total, e.is_async, e.base_cpu_ms, e.steps) for e in endpoints)

    traffic = _obj(raw.get("traffic", {}), "traffic")
    _check_traffic_and_business(traffic, _obj(raw.get("business", {}), "business"))
    scenarios = {}
    for name, sc in _obj(traffic.get("scenarios", {}), "traffic.scenarios").items():
        w = f"traffic.scenarios.{name}"
        _obj(sc, w)  # {"rps": 5}, no 5: el escenario también puede traer multiplier y descripción
        _number(sc.get("multiplier"), f"{w}.multiplier", gt=0)  # la lee el escenario del proyecto (JAJ-76)
        rps = _number(sc.get("rps"), f"{w}.rps", gt=0)
        if rps is not None:
            scenarios[name] = Scenario(name, float(rps))
    services = dep.get("services")
    service_roles = {
        s["name"].lower(): s.get("role")
        for s in (services if isinstance(services, list) else [])
        if isinstance(s, dict) and s.get("origin") and isinstance(s.get("name"), str)
    }
    return ArchitectureModel(
        name=_obj(raw.get("repo", {}), "repo").get("path", "modelo"),
        api=api,
        db=db,
        endpoints=endpoints,
        scenarios=scenarios,
        warnings=tuple(warnings),
        queues=queues,
        secondary_services=frozenset(name for name, role in service_roles.items() if role == "service"),
    )


def _load_step(s: Any, where: str, warnings: list[str], path: str) -> Step:
    """Un paso. ``where`` nombra al endpoint o la cola en los avisos; ``path`` es la ruta del paso en el
    JSON (``endpoints[0].steps[2]``) para los errores."""
    _obj(s, path)
    t = _number(s.get("time"), f"{path}.time", minimum=0)
    if t is None:
        warnings.append(f"{where}: el paso '{s.get('kind')}' en {s.get('at')} no tiene tiempo; se usa 0 ms")
        t = 0.0
    resource = s.get("resource")
    hit_ratio, on_miss = None, None
    if resource == RESOURCE_CACHE and "on_miss" in s:
        on_miss = tuple(
            _load_step(m, where, warnings, f"{path}.on_miss[{i}]")
            for i, m in enumerate(_list(s["on_miss"], f"{path}.on_miss"))
        )
        hit_ratio = _opt_float(_number(s.get("hit_ratio"), f"{path}.hit_ratio"))
        if hit_ratio is None:
            warnings.append(
                f"{where}: la caché en {s.get('at')} no tiene tasa de aciertos; se simula con 0 % "
                f"(todas fallan, el peor caso)."
            )
            hit_ratio = 0.0
        if not 0.0 <= hit_ratio <= 1.0:
            raise ValueError(f"{where}: hit_ratio debe estar entre 0 y 1 (es {hit_ratio})")
    service = s.get("service")
    return Step(
        kind=s.get("kind", "?"),
        resource=resource,
        time_ms=float(t),
        # repeat 0 se lee como 1, como antes: el paso está en el código, así que se hace al menos una vez
        repeat=max(1, _number(s.get("repeat"), f"{path}.repeat", default=1, integer=True, minimum=0)),
        shape=s.get("shape"),
        at=s.get("at"),
        hit_ratio=hit_ratio,
        on_miss=on_miss,
        queue=s.get("queue"),
        infer_queue=s.get("infer_queue", True),
        service=service if isinstance(service, str) and service else None,
    )


def _resolve_queue(
    step: Step, queues: dict[str, QueueDeployment], where: str, warnings: list[str], infer: bool = True
) -> Step:
    """Asigna la cola a un paso ``background``. Sin cola configurada, el worker no se simula.

    ``infer``: si el paso no nombra cola y hay una sola, usar esa. Los pasos de un trabajo de una cola
    no infieren (JAJ-99): con una sola cola, el trabajo se encolaría a sí mismo."""
    if step.on_miss:
        step = replace(step, on_miss=tuple(_resolve_queue(m, queues, where, warnings, infer) for m in step.on_miss))
    if step.resource != RESOURCE_BACKGROUND:
        return step
    name = step.queue
    if name is None and infer and step.infer_queue and len(queues) == 1:
        name = next(iter(queues))
    if name is None or name not in queues:
        warnings.append(
            f"{where}: el trabajo en segundo plano de {step.at} no tiene cola configurada "
            f"(deployment.queues); solo se simula el encolar, no el worker."
        )
        name = None
    return replace(step, queue=name)


# Pasos que puede recorrer una request (o un trabajo de una cola), contando ``repeat`` y los pasos de
# ``on_miss`` (JAJ-99). Cada paso es al menos una iteración del motor, aunque tarde 0 ms, así que sin
# tope un ``repeat`` enorme ocupa la CPU por minutos. Los modelos reales están muy por debajo: el
# template llega a ~200 (N+1 con repeat 20). Es un límite del servicio, no un número del modelo.
MAX_STEPS_PER_REQUEST = 10_000


def _steps_per_request(steps: tuple[Step, ...]) -> int:
    """Pasos que recorre una request en el peor caso (todas las cachés fallan)."""
    return sum(s.repeat * (1 + (_steps_per_request(s.on_miss) if s.on_miss else 0)) for s in steps)


def _check_steps_per_request(steps: tuple[Step, ...], where: str) -> None:
    n = _steps_per_request(steps)
    if n > MAX_STEPS_PER_REQUEST:
        count, limit = (f"{x:,}".replace(",", ".") for x in (n, MAX_STEPS_PER_REQUEST))
        raise ValueError(
            f"{where}: recorre {count} pasos por request contando repeat (el máximo es {limit}). "
            "Revisa el repeat de sus pasos."
        )


def _check_queue_cycles(queues: dict[str, QueueDeployment]) -> None:
    """Rechaza colas cuyos trabajos se encolan en ciclo (``a`` encola en ``b`` y ``b`` en ``a``, o
    ``a`` en sí misma): cada trabajo crea otro sin fin, y con tiempo 0 el reloj no avanza (JAJ-99)."""
    edges = {
        name: [s.queue for s in walk_steps(q.job_steps) if s.resource == RESOURCE_BACKGROUND and s.queue in queues]
        for name, q in queues.items()
    }
    done: set[str] = set()

    def visit(name: str, path: list[str]) -> None:
        if name in path:
            cycle = " → ".join([*path[path.index(name) :], name])
            raise ValueError(
                f"Las colas se encolan en ciclo ({cycle}): cada trabajo crea otro sin fin. "
                "Un trabajo no puede volver a encolar, directa o indirectamente, en su propia cola."
            )
        if name in done:
            return
        for nxt in edges[name]:
            visit(nxt, [*path, name])
        done.add(name)

    for name in queues:
        visit(name, [])


def _load_endpoint(e: dict[str, Any], queues: dict[str, QueueDeployment], warnings: list[str], path: str) -> Endpoint:
    eid = _need(e, "id", f"{path}.")
    if not isinstance(eid, str) or not eid.strip():
        raise ValueError(f"{path}.id debe ser un texto, como 'GET /items/' (es {eid!r})")
    steps = [
        _resolve_queue(_load_step(s, eid, warnings, f"{path}.steps[{i}]"), queues, eid, warnings)
        for i, s in enumerate(_list(e.get("steps", []), f"{path}.steps"))
    ]
    # api_cpu_ms del modelo incluye los pasos de CPU (ej. hash); la CPU base es el resto.
    # Solo cuentan los pasos que siempre se hacen (no los de on_miss).
    cpu_steps = sum(s.time_ms * s.repeat for s in steps if s.resource == RESOURCE_API_CPU)
    api_cpu = _number(e.get("api_cpu_ms"), f"{path}.api_cpu_ms", default=0.0, minimum=0)
    base_cpu = max(0.0, float(api_cpu) - cpu_steps)
    return Endpoint(
        id=eid,
        weight=float(_number(e.get("weight"), f"{path}.weight", default=0.0, minimum=0)),
        is_async=bool(e.get("async", False)),
        base_cpu_ms=base_cpu,
        steps=tuple(steps),
    )


def _check_traffic_and_business(traffic: dict[str, Any], business: dict[str, Any]) -> None:
    """Los datos de tráfico y negocio que el motor no usa pero sí el costo (JAJ-72), el costo de fallar
    (JAJ-74) y los escenarios del proyecto (JAJ-76). Son opcionales; si vienen, deben ser números en
    rango, para que esas rutas no fallen con un 500 (JAJ-101)."""
    _number(traffic.get("peak_rps"), "traffic.peak_rps", gt=0)
    _number(traffic.get("mau"), "traffic.mau", minimum=0)
    _number(traffic.get("requests_per_session"), "traffic.requests_per_session", gt=0)
    profile = _obj(traffic.get("profile", {}), "traffic.profile")
    _number(profile.get("sessions_per_month"), "traffic.profile.sessions_per_month", minimum=0)
    _number(profile.get("requests_per_session"), "traffic.profile.requests_per_session", minimum=0)
    conversion = _number(business.get("conversion"), "business.conversion", minimum=0)
    if conversion is not None and conversion > 1:
        raise ValueError(f"business.conversion es una fracción, entre 0 y 1 (es {conversion:g})")
    _number(business.get("ticket_usd"), "business.ticket_usd", minimum=0)


def _core_factor(raw: dict[str, Any], where: str) -> float:
    """``cpu_core_factor`` del modelo (JAJ-47). Sin él, los tiempos se usan tal cual (factor 1)."""
    factor = _opt_float(_number(raw.get("cpu_core_factor"), f"{where}.cpu_core_factor", gt=0))
    return 1.0 if factor is None else factor


# ---------- validación (JAJ-101) ----------


def _kind(x: Any) -> str:
    """Cómo se ve un valor del JSON, para los mensajes: 'una lista', 'un texto ('2')'…"""
    if x is None:
        return "null"
    if isinstance(x, bool):
        return f"{str(x).lower()}"
    if isinstance(x, str):
        return f"un texto ({x!r})"
    if isinstance(x, list):
        return "una lista"
    if isinstance(x, dict):
        return "un objeto"
    return repr(x)


def _need(d: dict[str, Any], key: str, prefix: str = "") -> Any:
    """``d[key]``, o ``KeyError`` con la ruta completa (``deployment.api.replicas``) si falta."""
    if key not in d:
        raise KeyError(f"{prefix}{key}")
    return d[key]


def _obj(x: Any, where: str) -> dict[str, Any]:
    if not isinstance(x, dict):
        raise ValueError(f"{where} debe ser un objeto ({{…}}), no {_kind(x)}")
    return x


def _list(x: Any, where: str) -> list[Any]:
    if not isinstance(x, list):
        raise ValueError(f"{where} debe ser una lista ([…]), no {_kind(x)}")
    return x


def _number(
    x: Any,
    where: str,
    *,
    default: Any = None,
    integer: bool = False,
    minimum: float | None = None,
    gt: float | None = None,
) -> Any:
    """Lee un número del modelo, con procedencia o escalar, y valida su rango.

    ``None`` (o ``default``) si no viene. Un NaN se lee como ausente, como antes. ``ValueError`` con el
    campo si no es un número (un texto, una lista, ``true``), si ``integer`` y tiene decimales, o si
    queda fuera de rango: ``minimum`` es ≥ y ``gt`` es >."""
    v = value(x, default)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None if v is None else default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or math.isinf(v):
        raise ValueError(f"{where} debe ser un número, no {_kind(v)}")
    if integer:
        if v != int(v):
            raise ValueError(f"{where} debe ser un entero (es {v:g})")
        v = int(v)
    if minimum is not None and v < minimum:
        rule = "no puede ser negativo" if minimum == 0 else f"debe ser al menos {minimum:g}"
        raise ValueError(f"{where} {rule} (es {v:g})")
    if gt is not None and v <= gt:
        raise ValueError(f"{where} debe ser mayor que {gt:g} (es {v:g})")
    return v


def _processor(raw: dict[str, Any]) -> str | None:
    f = raw.get("cpu_core_factor")
    return f.get("processor") if isinstance(f, dict) else None


def _opt_float(x: Any) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)
