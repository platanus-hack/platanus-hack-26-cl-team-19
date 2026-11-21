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
class ResourceStats:
    name: str
    label: str  # nombre para mostrar, ej. "CPU de la API"
    capacity: int
    utilization: float  # fracción de la capacidad ocupada en promedio (0 a 1)
    max_queue: int
    final_queue: int
    timeouts: int
    mean_wait_ms: float


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
class Bottleneck:
    resource: str | None
    utilization: float
    message: str


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
    errors: dict[str, int]  # por tipo: pool_timeout, client_timeout
    in_flight: int  # requests que seguían en curso al terminar (sin superar el timeout del cliente)
    error_rate: float
    throughput_rps: float
    latency: LatencyStats
    resources: list[ResourceStats]
    endpoints: list[EndpointStats]
    bottleneck: Bottleneck
    warnings: list[str]
    series: list[SecondSample]
    elapsed_ms: float
    schema: str = field(default=RUN_SCHEMA)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
