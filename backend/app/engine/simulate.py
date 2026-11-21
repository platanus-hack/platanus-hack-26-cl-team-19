"""Simulación de un modelo de arquitectura bajo un escenario de tráfico (JAJ-14).

Recursos que se arman desde el ``deployment`` del modelo:

* ``api_cpu``: núcleos de la API, ``min(workers, vCPU) × réplicas``. Los ocupa la CPU base de cada
  request y los pasos de CPU (ej. hash de contraseña, que libera el GIL pero usa un núcleo).
* ``api_threads``: hilos del threadpool para endpoints ``def`` (síncronos). Los async no los usan.
* ``db_pool``: conexiones, ``pool por worker × workers × réplicas`` (tope: conexiones de la DB).
  Esperar más que el timeout del pool es un error.
* ``db_cpu``: vCPU de la DB. Cada consulta ocupa un núcleo durante su tiempo.

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
from app.engine.metrics import ERROR_POOL_TIMEOUT, Recorder, latency_stats
from app.models.architecture import (
    RESOURCE_API_CPU,
    RESOURCE_DB_CONNECTION,
    ArchitectureModel,
    Endpoint,
)
from app.models.run import Bottleneck, EndpointStats, ResourceStats, Run, SecondSample

RESOURCE_LABELS = {
    "api_cpu": "CPU de la API",
    "api_threads": "hilos de la API",
    "db_pool": "pool de conexiones",
    "db_cpu": "CPU de la DB",
}
SATURATION_WARNING = 0.9  # JAJ-44: sobre esto, latencia y errores se muestran como piso
BOTTLENECK_MIN = 0.5  # bajo esto no se habla de cuello de botella
ARRIVALS = ("poisson", "uniform")


def simulate(
    model: ArchitectureModel,
    scenario: str = "cyberday",
    *,
    seed: int = 0,
    duration_s: float = 60.0,
    rps: float | None = None,
    arrivals: str = "poisson",
    client_timeout_s: float | None = 30.0,
) -> Run:
    """Simula ``duration_s`` segundos de tráfico y devuelve el ``Run``.

    ``rps`` reemplaza la tasa del escenario. ``arrivals``: ``poisson`` (usuarios reales) o
    ``uniform`` (como k6 con tasa constante, útil para comparar con mediciones).
    """
    if arrivals not in ARRIVALS:
        raise ValueError(f"arrivals debe ser uno de {ARRIVALS}")
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
    resources = [api_cpu, threads, pool, db_cpu]
    rec = Recorder(duration_s, model.endpoints, resources)
    in_flight: dict[int, tuple[Endpoint, float]] = {}
    api_latency_s = model.api.latency_ms / 1000
    pool_timeout_s = model.db.pool_timeout_s

    def hold(res: Resource, scale: float, ms: float) -> Generator[Any, Any, None]:
        yield res.acquire()
        yield ms * scale / 1000
        res.release()

    def request(ep: Endpoint, rid: int) -> Generator[Any, Any, None]:
        t0 = sim.now
        in_flight[rid] = (ep, t0)
        if api_latency_s:
            yield api_latency_s
        if not ep.is_async:
            yield threads.acquire()
        if ep.base_cpu_ms > 0:
            yield from hold(api_cpu, api_scale, ep.base_cpu_ms)
        has_connection, error = False, None
        for step in ep.steps:
            for _ in range(step.repeat):
                if step.resource == RESOURCE_DB_CONNECTION:
                    if not has_connection:
                        if not (yield pool.acquire(pool_timeout_s)):
                            error = ERROR_POOL_TIMEOUT
                            break
                        has_connection = True
                    if step.time_ms > 0:
                        yield from hold(db_cpu, db_scale, step.time_ms)
                elif step.resource == RESOURCE_API_CPU:
                    if step.time_ms > 0:
                        yield from hold(api_cpu, api_scale, step.time_ms)
                elif step.time_ms > 0:  # caché, servicio externo, encolar: espera sin recurso compartido
                    yield step.time_ms / 1000
            if error:
                break
        if has_connection:
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

    return _build_run(model, scenario if rps is None else f"{scenario} ({rate:g} req/s)", rate, seed,
                      duration_s, arrivals, rec, resources, still_running, warnings, wall_start)


def _cores(sim: Sim, name: str, vcpu: float) -> tuple[Resource, float]:
    """Recurso de núcleos y factor de tiempo: 0,5 vCPU = 1 núcleo que tarda el doble."""
    if vcpu <= 0:
        raise ValueError(f"{name}: los vCPU deben ser mayores que 0")
    servers = max(1, math.floor(vcpu))
    return Resource(sim, name, servers), servers / vcpu


def _build_run(model: ArchitectureModel, scenario: str, rate: float, seed: int, duration_s: float,
               arrivals: str, rec: Recorder, resources: list[Resource], still_running: int,
               warnings: list[str], wall_start: float) -> Run:
    resource_stats = [
        ResourceStats(
            name=r.name,
            label=RESOURCE_LABELS.get(r.name, r.name),
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
                f"(JAJ-44). Tomar la latencia y los errores como piso (\"al menos\")."
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
        return Bottleneck(None, top.utilization,
                          f"Ningún recurso pasa del {BOTTLENECK_MIN:.0%} de uso: el escenario se aguanta con holgura.")
    message = f"{top.label} al {top.utilization:.0%}"
    if top.final_queue:
        message += f", con {top.final_queue} requests esperando al final (la cola crece)"
    elif top.max_queue:
        message += f", con hasta {top.max_queue} requests esperando"
    return Bottleneck(top.name, top.utilization, message + ".")
