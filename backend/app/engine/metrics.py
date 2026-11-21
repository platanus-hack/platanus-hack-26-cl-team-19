"""Registro de lo que pasa en una simulación y cálculo de percentiles.

``Recorder`` junta llegadas, requests terminadas y errores (en total, por endpoint y por segundo),
y cada segundo toma una muestra de la cola y el uso de cada recurso.

``UsageTracker`` (JAJ-69) suma cuánto tiempo ocupa cada endpoint cada recurso y desde qué línea de
código, para que el cuello de botella apunte al endpoint y al ``archivo:línea`` que lo causan.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence

from app.engine.kernel import Resource
from app.models.architecture import Endpoint
from app.models.run import EndpointUsage, LatencyStats, LineUsage

ERROR_POOL_TIMEOUT = "pool_timeout"  # esperó una conexión más que el timeout del pool
ERROR_CLIENT_TIMEOUT = "client_timeout"  # tardó más que el timeout del cliente (el servidor igual hizo el trabajo)
ERROR_QUEUE_FULL = "queue_full"  # quiso encolar un trabajo y la cola estaba en su largo máximo


def percentile(sorted_values: Sequence[float], p: float) -> float | None:
    """Percentil ``p`` (0-100) con interpolación lineal. ``sorted_values`` debe venir ordenado."""
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * p / 100
    lo, hi = math.floor(k), min(math.floor(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def latency_stats(values_ms: Iterable[float]) -> LatencyStats:
    xs = sorted(values_ms)
    r = lambda v: None if v is None else round(v, 3)  # noqa: E731
    return LatencyStats(r(percentile(xs, 50)), r(percentile(xs, 95)), r(percentile(xs, 99)))


class EndpointCounters:
    __slots__ = ("requests", "ok", "errors", "latencies_ms")

    def __init__(self) -> None:
        self.requests = 0
        self.ok = 0
        self.errors = 0
        self.latencies_ms: list[float] = []


class Recorder:
    def __init__(self, duration_s: float, endpoints: Sequence[Endpoint], resources: Sequence[Resource]) -> None:
        self.seconds = max(1, math.ceil(duration_s))
        self.arrivals = [0] * self.seconds
        self.ok = [0] * self.seconds
        self.errors = [0] * self.seconds
        self.latencies_ms: list[list[float]] = [[] for _ in range(self.seconds)]
        self.error_types = {ERROR_POOL_TIMEOUT: 0, ERROR_CLIENT_TIMEOUT: 0, ERROR_QUEUE_FULL: 0}
        self.by_endpoint = {e.id: EndpointCounters() for e in endpoints}
        self.resources = list(resources)
        self.queue_samples: list[dict[str, int]] = []
        self.utilization_samples: list[dict[str, float]] = []
        self._busy_last = {r.name: 0.0 for r in self.resources}

    def _second(self, t: float) -> int:
        return min(int(t), self.seconds - 1)

    def arrival(self, endpoint: Endpoint, t: float) -> None:
        self.arrivals[self._second(t)] += 1
        self.by_endpoint[endpoint.id].requests += 1

    def finish(
        self, endpoint: Endpoint, t0: float, t1: float, error: str | None, client_timeout_s: float | None
    ) -> None:
        latency_s = t1 - t0
        if error is None and client_timeout_s is not None and latency_s > client_timeout_s:
            error = ERROR_CLIENT_TIMEOUT
        i = self._second(t1)
        counters = self.by_endpoint[endpoint.id]
        if error is not None:
            self.error_types[error] += 1
            self.errors[i] += 1
            counters.errors += 1
        else:
            ms = latency_s * 1000
            self.ok[i] += 1
            self.latencies_ms[i].append(ms)
            counters.ok += 1
            counters.latencies_ms.append(ms)

    def timeout_in_flight(self, endpoint: Endpoint) -> None:
        """Request que seguía en curso al final pero ya superaba el timeout del cliente."""
        self.error_types[ERROR_CLIENT_TIMEOUT] += 1
        self.by_endpoint[endpoint.id].errors += 1

    def sample(self) -> None:
        """Muestra de cola y uso de cada recurso en el último segundo."""
        self.queue_samples.append({r.name: r.waiting for r in self.resources})
        util = {}
        for r in self.resources:
            busy = r.busy_time()
            util[r.name] = round((busy - self._busy_last[r.name]) / r.capacity, 4)
            self._busy_last[r.name] = busy
        self.utilization_samples.append(util)


class UsageTracker:
    """Tiempo que cada endpoint ocupa cada recurso, y desde qué línea de código (JAJ-69).

    ``add`` se llama cuando una request (o un trabajo de una cola) suelta un recurso, con el tiempo
    que lo tuvo. ``at`` es el ``archivo:línea`` del paso que lo ocupó; ``None`` si no tiene línea en
    el modelo (ej. la CPU propia del framework o los hilos, que se toman por toda la request).
    """

    def __init__(self) -> None:
        # recurso -> dueño (endpoint o "cola <nombre>") -> línea (o None) -> segundos
        self._seconds: dict[str, dict[str, dict[str | None, float]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(float))
        )

    def add(self, resource: str, owner: str, at: str | None, seconds: float) -> None:
        if seconds > 0:
            self._seconds[resource][owner][at] += seconds

    def by_endpoint(self, resource: str) -> list[EndpointUsage]:
        """Quién ocupa el recurso, de más a menos. Las fracciones suman 1 (salvo redondeo)."""
        owners = self._seconds.get(resource, {})
        total = sum(sum(lines.values()) for lines in owners.values())
        if total <= 0:
            return []
        usage = [
            EndpointUsage(
                endpoint=owner,
                share=round(sum(lines.values()) / total, 4),
                refs=[at for at, _ in sorted(lines.items(), key=lambda kv: -kv[1]) if at],
            )
            for owner, lines in owners.items()
        ]
        return sorted(usage, key=lambda u: (-u.share, u.endpoint))

    def by_line(self, resource: str) -> list[LineUsage]:
        """Qué líneas ocupan el recurso, sumando endpoints, de más a menos.

        La fracción es sobre el tiempo total ocupado, así que el tiempo sin línea (``at=None``) cuenta
        en el total pero no aparece como línea: las fracciones suman 1 solo si todo tiene línea.
        """
        owners = self._seconds.get(resource, {})
        total = sum(sum(lines.values()) for lines in owners.values())
        if total <= 0:
            return []
        per_line: dict[str, dict[str, float]] = defaultdict(dict)
        for owner, lines in owners.items():
            for at, seconds in lines.items():
                if at:
                    per_line[at][owner] = seconds
        usage = [
            LineUsage(
                at=at,
                share=round(sum(by_owner.values()) / total, 4),
                endpoints=[o for o, _ in sorted(by_owner.items(), key=lambda kv: -kv[1])],
            )
            for at, by_owner in per_line.items()
        ]
        return sorted(usage, key=lambda u: (-u.share, u.at))
