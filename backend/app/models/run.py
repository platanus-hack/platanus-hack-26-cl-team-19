"""Resultado de una simulación: el ``Run`` (``branchpoint.run/v1``).

Es lo que muestra la app: un resumen, el detalle por recurso y por endpoint, el cuello de botella,
advertencias y una serie por segundo para graficar. ``Run.to_dict()`` lo deja listo para JSON.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

RUN_SCHEMA = "branchpoint.run/v1"


@dataclass
class LatencyStats:
    """Latencia de las requests exitosas, en ms. ``None`` si no hubo ninguna."""

    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None


@dataclass
class EndpointUsage:
    """Cuánto ocupa un endpoint un recurso y desde qué líneas de código (JAJ-69)."""

    endpoint: str  # id del endpoint (ej. "POST /login/access-token"), o "cola <nombre>" para sus trabajos
    share: float  # fracción del tiempo ocupado del recurso (0 a 1); entre todos suman 1
    refs: list[str]  # archivo:línea de los pasos que lo ocupan, de más a menos tiempo


@dataclass
class LineUsage:
    """Cuánto ocupa un recurso una línea de código, sumando todos los endpoints que pasan por ella (JAJ-69).

    Ej. el hash de contraseña (``security.py:32``) lo usan login, crear usuario y cambiar contraseña:
    cada endpoint ocupa poco, pero la línea junta la mayor parte de la CPU.
    """

    at: str  # archivo:línea
    share: float  # fracción del tiempo ocupado del recurso (0 a 1)
    endpoints: list[str]  # endpoints que pasan por esa línea, de más a menos tiempo


@dataclass
class ResourceStats:
    name: str
    label: str  # nombre para mostrar, ej. "CPU de la API"
    capacity: int
    utilization: float  # fracción de la capacidad ocupada en promedio (0 a 1)
    max_queue: int
    final_queue: int
    timeouts: int
    mean_wait_ms: float
    # quién ocupa el recurso, de más a menos (JAJ-69); vacío si nadie lo usó
    by_endpoint: list[EndpointUsage] = field(default_factory=list)
    # qué líneas de código lo ocupan, sumando endpoints; sin el tiempo que no tiene línea en el modelo
    by_line: list[LineUsage] = field(default_factory=list)


@dataclass
class EndpointStats:
    id: str
    requests: int
    ok: int
    errors: int
    error_rate: float
    latency: LatencyStats


@dataclass
class SecondSample:
    """Un segundo de la simulación, para los gráficos."""

    t: int
    arrivals: int
    ok: int
    errors: int
    latency: LatencyStats
    queue: dict[str, int]
    utilization: dict[str, float]


@dataclass
class CacheStats:
    """Consultas a la caché que tienen ``on_miss`` (las demás son solo una espera)."""

    hits: int
    misses: int
    hit_rate: float | None  # None si no hubo consultas


@dataclass
class QueueStats:
    """Una cola con workers asíncronos. ``job_latency``: desde que se encola hasta que termina."""

    name: str
    workers: int
    max_length: int | None
    enqueued: int
    rejected: int  # la cola estaba llena (la request falla con queue_full)
    processed: int
    max_backlog: int
    final_backlog: int  # trabajos esperando al final (si crece, los workers no dan abasto)
    job_latency: LatencyStats


@dataclass
class CpuAdjustment:
    """Cómo se pasaron los tiempos del laptop de calibración a la nube (JAJ-48).

    Los tiempos de CPU del modelo son de 1 núcleo del laptop (JAJ-46). En la nube, la CPU de la API
    y cada consulta tardan ``*_core_factor`` veces más. ``db_vcpu_effective`` son los vCPU con que
    se simuló la DB: los sostenidos si tiene créditos de CPU y ``cpu_credits`` es ``sustained``.
    """

    api_core_factor: float
    api_processor: str | None
    db_core_factor: float
    db_processor: str | None
    db_vcpu: float  # vCPU del plan
    db_vcpu_effective: float  # vCPU simulados
    cpu_credits: str | None  # sustained | burst; None si la DB no tiene créditos de CPU


@dataclass
class Bottleneck:
    """El recurso más ocupado y, desde JAJ-69, qué código lo ocupa.

    Para el banner del editor: ``line`` es la línea de código que más ocupa el recurso, sumando todos
    los endpoints que pasan por ella (``line_endpoints``). ``endpoint`` es el endpoint que más lo
    ocupa, y ``refs``, las líneas de ese endpoint. Quedan en ``None`` o vacíos si el recurso lo ocupa
    algo sin línea en el modelo (ej. la CPU propia del framework).
    """

    resource: str | None
    utilization: float
    message: str
    line: str | None = None  # archivo:línea que más ocupa el recurso
    line_share: float | None = None  # su fracción del tiempo ocupado (0 a 1)
    line_endpoints: list[str] = field(default_factory=list)  # endpoints que pasan por esa línea
    endpoint: str | None = None  # el endpoint que más ocupa el recurso
    endpoint_share: float | None = None  # su fracción del tiempo ocupado (0 a 1)
    refs: list[str] = field(default_factory=list)  # archivo:línea de sus pasos en ese recurso


@dataclass
class Run:
    model: str
    scenario: str
    rps: float
    seed: int
    duration_s: float
    arrivals: str
    requests: int
    ok: int
    errors: dict[str, int]  # por tipo: pool_timeout, client_timeout, queue_full, db_refused
    in_flight: int  # requests que seguían en curso al terminar (sin superar el timeout del cliente)
    error_rate: float
    throughput_rps: float
    latency: LatencyStats
    resources: list[ResourceStats]
    endpoints: list[EndpointStats]
    cache: CacheStats
    queues: list[QueueStats]
    cpu: CpuAdjustment
    bottleneck: Bottleneck
    warnings: list[str]
    series: list[SecondSample]
    elapsed_ms: float
    schema: str = field(default=RUN_SCHEMA)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
