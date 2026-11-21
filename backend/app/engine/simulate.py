"""Simulación de un modelo de arquitectura bajo un escenario de tráfico (JAJ-14).

Recursos que se arman desde el ``deployment`` del modelo:

* ``api_cpu``: núcleos de la API, ``min(workers, vCPU) × réplicas``. Los ocupa la CPU base de cada
  request y los pasos de CPU (ej. hash de contraseña, que libera el GIL pero usa un núcleo).
* ``api_threads``: hilos del threadpool para endpoints ``def`` (síncronos). Los async no los usan.
* ``db_pool``: conexiones, ``pool por worker × workers × réplicas`` (tope: conexiones de la DB).
  Esperar más que el timeout del pool es un error.
* ``db_cpu``: vCPU de la DB. Cada consulta ocupa un núcleo durante su tiempo.
* ``queue:<nombre>``: workers de cada cola (``deployment.queues``). Encolar es casi instantáneo
  para la request; el trabajo espera un worker libre y usa la CPU de la DB si hace consultas
  (con su propia conexión, no la del pool de la API). Si la cola está en su largo máximo, encolar
  falla y la request termina con error ``queue_full``.

La caché con ``on_miss`` sigue lo validado en JAJ-44: GET; si acierta, sigue sin hacer los pasos
de ``on_miss``; si falla, los hace (ej. la consulta) y luego SET. Sin ``on_miss`` es solo una espera.

Cada request sigue los pasos de su endpoint en orden. Toma una conexión en la primera consulta y
la retiene hasta el final (una sesión por request, como el template de FastAPI). Con vCPU
fraccionarios (ej. 0,5 en Supabase Micro) se simula 1 núcleo más lento.

Validado en JAJ-9, JAJ-43, JAJ-42 y JAJ-44. Cerca o sobre la capacidad el modelo es optimista
(JAJ-44), así que en esos casos el Run lo advierte.
"""

from __future__ import annotations

import math
import time
from bisect import bisect_right
from collections.abc import Generator
from itertools import accumulate
from typing import Any

from app.engine.kernel import Resource, Sim
from app.engine.metrics import ERROR_POOL_TIMEOUT, ERROR_QUEUE_FULL, Recorder, latency_stats
from app.models.architecture import (
    RESOURCE_API_CPU,
    RESOURCE_BACKGROUND,
    RESOURCE_CACHE,
    RESOURCE_DB_CONNECTION,
    ArchitectureModel,
    Endpoint,
    QueueDeployment,
    Step,
    walk_steps,
)
from app.models.run import (
    Bottleneck,
    CacheStats,
    EndpointStats,
    QueueStats,
    ResourceStats,
    Run,
    SecondSample,
)

RESOURCE_LABELS = {
    "api_cpu": "CPU de la API",
    "api_threads": "hilos de la API",
    "db_pool": "pool de conexiones",
    "db_cpu": "CPU de la DB",
}
SATURATION_WARNING = 0.9  # JAJ-44: sobre esto, latencia y errores se muestran como piso
BOTTLENECK_MIN = 0.5  # bajo esto no se habla de cuello de botella
ARRIVALS = ("poisson", "uniform")
QUEUE_PREFIX = "queue:"


def resource_label(name: str) -> str:
    if name.startswith(QUEUE_PREFIX):
        return f"workers de la cola {name[len(QUEUE_PREFIX) :]}"
    return RESOURCE_LABELS.get(name, name)


class _QueueCounters:
    __slots__ = ("config", "resource", "enqueued", "rejected", "processed", "latencies_ms")

    def __init__(self, config: QueueDeployment, resource: Resource) -> None:
        self.config = config
        self.resource = resource
        self.enqueued = 0
        self.rejected = 0
        self.processed = 0
        self.latencies_ms: list[float] = []


def simulate(
    model: ArchitectureModel,
    scenario: str = "cyberday",
    *,
    seed: int = 0,
    duration_s: float = 60.0,
    rps: float | None = None,
    arrivals: str = "poisson",
    client_timeout_s: float | None = 30.0,
    cache_hit_ratio: float | None = None,
) -> Run:
    """Simula ``duration_s`` segundos de tráfico y devuelve el ``Run``.

    ``rps`` reemplaza la tasa del escenario. ``arrivals``: ``poisson`` (usuarios reales) o
    ``uniform`` (como k6 con tasa constante, útil para comparar con mediciones).
    ``cache_hit_ratio`` reemplaza la tasa de aciertos de todas las cachés con ``on_miss``.
    """
    if arrivals not in ARRIVALS:
        raise ValueError(f"arrivals debe ser uno de {ARRIVALS}")
    if cache_hit_ratio is not None and not 0.0 <= cache_hit_ratio <= 1.0:
        raise ValueError("cache_hit_ratio debe estar entre 0 y 1")
    rate = rps if rps is not None else model.scenario(scenario).rps
    if rate <= 0 or duration_s <= 0:
        raise ValueError("rps y duration_s deben ser mayores que 0")
    wall_start = time.perf_counter()
    sim = Sim(seed)
    warnings = list(model.warnings)

    api_cpu, api_scale = _cores(sim, "api_cpu", model.api.cores)
    db_cpu, db_scale = _cores(sim, "db_cpu", model.db.vcpu)
    threads = Resource(sim, "api_threads", model.api.threads)
    pool_capacity = model.app_connections
    if model.db.max_connections and pool_capacity > model.db.max_connections:
        warnings.append(
            f"La app puede abrir {pool_capacity} conexiones y la DB acepta {model.db.max_connections}: "
            f"se simula con {model.db.max_connections} (las demás fallarían al conectarse)."
        )
        pool_capacity = model.db.max_connections
    pool = Resource(sim, "db_pool", pool_capacity)
    queues = {
        name: _QueueCounters(q, Resource(sim, QUEUE_PREFIX + name, q.workers)) for name, q in model.queues.items()
    }
    resources = [api_cpu, threads, pool, db_cpu, *(q.resource for q in queues.values())]
    if cache_hit_ratio is not None and not any(
        s.on_miss is not None for e in model.endpoints for s in walk_steps(e.steps)
    ):
        warnings.append("Se pidió una tasa de aciertos de caché, pero ningún endpoint tiene caché con on_miss.")
    cache = [0, 0]  # aciertos, fallos
    rec = Recorder(duration_s, model.endpoints, resources)
    in_flight: dict[int, tuple[Endpoint, float]] = {}
    api_latency_s = model.api.latency_ms / 1000
    pool_timeout_s = model.db.pool_timeout_s

    def hold(res: Resource, scale: float, ms: float) -> Generator[Any, Any, None]:
        yield res.acquire()
        yield ms * scale / 1000
        res.release()

    def run_steps(steps: tuple[Step, ...], conn: list[bool] | None) -> Generator[Any, Any, str | None]:
        """Recorre los pasos y devuelve el error, si hubo. ``conn``: [tiene conexión] de la request;
        ``None`` en un trabajo de una cola (usa su propia conexión y su propia CPU)."""
        for step in steps:
            res, ms = step.resource, step.time_ms
            for _ in range(step.repeat):
                if res == RESOURCE_DB_CONNECTION:
                    if conn is not None and not conn[0]:
                        if not (yield pool.acquire(pool_timeout_s)):
                            return ERROR_POOL_TIMEOUT
                        conn[0] = True
                    if ms > 0:
                        yield from hold(db_cpu, db_scale, ms)
                elif res == RESOURCE_API_CPU and conn is not None:
                    if ms > 0:
                        yield from hold(api_cpu, api_scale, ms)
                elif res == RESOURCE_CACHE and step.on_miss is not None:
                    if ms > 0:
                        yield ms / 1000  # GET
                    hit = step.hit_ratio if cache_hit_ratio is None else cache_hit_ratio
                    if sim.rng.random() < hit:
                        cache[0] += 1
                        continue
                    cache[1] += 1
                    error = yield from run_steps(step.on_miss, conn)
                    if error:
                        return error
                    if ms > 0:
                        yield ms / 1000  # SET
                else:  # caché sin on_miss, servicio externo, encolar, CPU del worker: espera
                    if ms > 0:
                        yield ms / 1000
                    if res == RESOURCE_BACKGROUND and step.queue is not None and not enqueue(step.queue):
                        return ERROR_QUEUE_FULL
        return None

    def enqueue(name: str) -> bool:
        q = queues[name]
        if q.config.max_length is not None and q.resource.waiting >= q.config.max_length:
            q.rejected += 1
            return False
        q.enqueued += 1
        sim.start(job(q, sim.now))
        return True

    def job(q: _QueueCounters, t0: float) -> Generator[Any, Any, None]:
        yield q.resource.acquire()
        yield from run_steps(q.config.job_steps, None)
        q.resource.release()
        q.processed += 1
        q.latencies_ms.append((sim.now - t0) * 1000)

    def request(ep: Endpoint, rid: int) -> Generator[Any, Any, None]:
        t0 = sim.now
        in_flight[rid] = (ep, t0)
        if api_latency_s:
            yield api_latency_s
        if not ep.is_async:
            yield threads.acquire()
        if ep.base_cpu_ms > 0:
            yield from hold(api_cpu, api_scale, ep.base_cpu_ms)
        conn = [False]
        error = yield from run_steps(ep.steps, conn)
        if conn[0]:
            pool.release()
        if not ep.is_async:
            threads.release()
        del in_flight[rid]
        rec.finish(ep, t0, sim.now, error, client_timeout_s)

    endpoints = model.endpoints
    cumulative = list(accumulate(e.weight for e in endpoints))

    def source() -> Generator[Any, Any, None]:
        rid = 0
        while True:
            yield sim.rng.expovariate(rate) if arrivals == "poisson" else 1.0 / rate
            if sim.now >= duration_s:
                return
            i = min(bisect_right(cumulative, sim.rng.random() * cumulative[-1]), len(endpoints) - 1)
            rid += 1
            rec.arrival(endpoints[i], sim.now)
            sim.start(request(endpoints[i], rid))

    def sampler() -> Generator[Any, Any, None]:
        for _ in range(rec.seconds):
            yield 1.0
            rec.sample()

    sim.start(source())
    sim.start(sampler())
    sim.run(until=duration_s)

    still_running = 0
    for ep, t0 in in_flight.values():
        if client_timeout_s is not None and duration_s - t0 > client_timeout_s:
            rec.timeout_in_flight(ep)
        else:
            still_running += 1

    hits, misses = cache
    cache_stats = CacheStats(hits, misses, round(hits / (hits + misses), 4) if hits + misses else None)
    queue_stats = [
        QueueStats(
            name=name,
            workers=q.config.workers,
            max_length=q.config.max_length,
            enqueued=q.enqueued,
            rejected=q.rejected,
            processed=q.processed,
            max_backlog=q.resource.max_waiting,
            final_backlog=q.resource.waiting,
            job_latency=latency_stats(q.latencies_ms),
        )
        for name, q in queues.items()
    ]
    return _build_run(
        model,
        scenario if rps is None else f"{scenario} ({rate:g} req/s)",
        rate,
        seed,
        duration_s,
        arrivals,
        rec,
        resources,
        still_running,
        warnings,
        wall_start,
        cache_stats,
        queue_stats,
    )


def _cores(sim: Sim, name: str, vcpu: float) -> tuple[Resource, float]:
    """Recurso de núcleos y factor de tiempo: 0,5 vCPU = 1 núcleo que tarda el doble."""
    if vcpu <= 0:
        raise ValueError(f"{name}: los vCPU deben ser mayores que 0")
    servers = max(1, math.floor(vcpu))
    return Resource(sim, name, servers), servers / vcpu


def _build_run(
    model: ArchitectureModel,
    scenario: str,
    rate: float,
    seed: int,
    duration_s: float,
    arrivals: str,
    rec: Recorder,
    resources: list[Resource],
    still_running: int,
    warnings: list[str],
    wall_start: float,
    cache: CacheStats,
    queues: list[QueueStats],
) -> Run:
    resource_stats = [
        ResourceStats(
            name=r.name,
            label=resource_label(r.name),
            capacity=r.capacity,
            utilization=round(r.busy_time() / (r.capacity * duration_s), 4),
            max_queue=r.max_waiting,
            final_queue=r.waiting,
            timeouts=r.timeouts,
            mean_wait_ms=round(r.wait_total / r.grants * 1000, 3) if r.grants else 0.0,
        )
        for r in resources
    ]
    ok = sum(rec.ok)
    errors = sum(rec.error_types.values())
    all_latencies = [ms for second in rec.latencies_ms for ms in second]

    for rs in resource_stats:
        if rs.utilization >= SATURATION_WARNING:
            warnings.append(
                f"{rs.label} al {rs.utilization:.0%}: cerca o sobre la capacidad el modelo es optimista "
                f'(JAJ-44). Tomar la latencia y los errores como piso ("al menos").'
            )

    return Run(
        model=model.name,
        scenario=scenario,
        rps=rate,
        seed=seed,
        duration_s=duration_s,
        arrivals=arrivals,
        requests=sum(rec.arrivals),
        ok=ok,
        errors=dict(rec.error_types),
        in_flight=still_running,
        error_rate=round(errors / (ok + errors), 4) if ok + errors else 0.0,
        throughput_rps=round(ok / duration_s, 3),
        latency=latency_stats(all_latencies),
        resources=resource_stats,
        endpoints=[
            EndpointStats(
                id=ep_id,
                requests=c.requests,
                ok=c.ok,
                errors=c.errors,
                error_rate=round(c.errors / (c.ok + c.errors), 4) if c.ok + c.errors else 0.0,
                latency=latency_stats(c.latencies_ms),
            )
            for ep_id, c in rec.by_endpoint.items()
        ],
        cache=cache,
        queues=queues,
        bottleneck=_bottleneck(resource_stats),
        warnings=warnings,
        series=[
            SecondSample(
                t=i + 1,
                arrivals=rec.arrivals[i],
                ok=rec.ok[i],
                errors=rec.errors[i],
                latency=latency_stats(rec.latencies_ms[i]),
                queue=rec.queue_samples[i] if i < len(rec.queue_samples) else {},
                utilization=rec.utilization_samples[i] if i < len(rec.utilization_samples) else {},
            )
            for i in range(rec.seconds)
        ],
        elapsed_ms=round((time.perf_counter() - wall_start) * 1000, 1),
    )


def _bottleneck(stats: list[ResourceStats]) -> Bottleneck:
    top = max(stats, key=lambda s: (s.utilization, s.final_queue))
    if top.utilization < BOTTLENECK_MIN:
        return Bottleneck(
            None,
            top.utilization,
            f"Ningún recurso pasa del {BOTTLENECK_MIN:.0%} de uso: el escenario se aguanta con holgura.",
        )
    message = f"{top.label} al {top.utilization:.0%}"
    if top.final_queue:
        message += f", con {top.final_queue} requests esperando al final (la cola crece)"
    elif top.max_queue:
        message += f", con hasta {top.max_queue} requests esperando"
    return Bottleneck(top.name, top.utilization, message + ".")
