"""Simulación de un modelo de arquitectura bajo un escenario de tráfico (JAJ-14).

Recursos que se arman desde el ``deployment`` del modelo:

* ``api_cpu``: núcleos de la API, ``min(workers, vCPU) × réplicas``. Los ocupa la CPU base de cada
  request y los pasos de CPU (ej. hash de contraseña, que libera el GIL pero usa un núcleo).
* ``api_threads``: hilos del threadpool para endpoints ``def`` (síncronos). Los async no los usan.
* ``db_pool``: conexiones, ``pool por worker × workers × réplicas`` (tope: conexiones de la DB).
  Sin pooler, pasar el tope de la DB es un error al conectarse; con pooler, la request espera.
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

De laptop a nube (JAJ-48): los tiempos del modelo son de 1 núcleo del laptop de calibración
(JAJ-46). En la nube, la CPU de la API y cada consulta de la DB tardan ``cpu_core_factor`` veces
más (ej. ×1,95 en Graviton2), así que la conexión también se retiene más tiempo. Una DB con
créditos de CPU (``db.t4g.*``) se simula con sus vCPU sostenidos (``cpu_credits="sustained"``, la
base de créditos con carga sostenida) o con todos sus vCPU (``"burst"``: solo mientras duren los
créditos o pagando el exceso). Los trabajos de las colas usan sus tiempos tal cual.

Quién causa el cuello de botella (JAJ-69): cada vez que una request suelta un recurso, el motor
anota cuánto lo tuvo, a nombre de su endpoint y de la línea del paso que lo ocupó (``at``). El pool
se anota a la consulta que tomó la conexión, y los hilos a la request completa. Con eso, cada
recurso del ``Run`` dice quién lo ocupa (``by_endpoint``) y el cuello de botella apunta al endpoint
y al ``archivo:línea`` que más lo usan.

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
from app.engine.metrics import (
    ERROR_DB_REFUSED,
    ERROR_POOL_TIMEOUT,
    ERROR_QUEUE_FULL,
    Recorder,
    UsageTracker,
    latency_stats,
)
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
    CpuAdjustment,
    EndpointStats,
    ProfileSegment,
    QueueStats,
    ResourceStats,
    Run,
    Saturation,
    SecondSample,
)
from app.models.traffic import TrafficProfile

RESOURCE_LABELS = {
    "api_cpu": "CPU de la API",
    "api_threads": "hilos de la API",
    "db_pool": "pool de conexiones",
    "db_cpu": "CPU de la DB",
}
SATURATION_WARNING = 0.9  # JAJ-44: sobre esto, latencia y errores se muestran como piso
# JAJ-89: cuándo el sistema "no alcanza a atender". Los dos números son SUPUESTO, elegidos por el equipo:
# * UNANSWERED_SATURATED: fracción mínima de requests sin respuesta al terminar para avisar. Por sí sola
#   no basta: sin saturación, la fracción en curso es latencia / duración (un endpoint sano de 3 s en
#   30 s deja 10 %).
# * WAIT_GROWTH: la espera que implica la fila (Ley de Little: fila / tasa de llegada) tiene que crecer
#   entre la mitad y el final de la simulación. Sana, la espera se estabiliza en la latencia; saturada,
#   crece sin parar. WAIT_GROWTH_MIN_S evita que el ruido de esperas de milisegundos cuente como crecer.
UNANSWERED_SATURATED = 0.05
WAIT_GROWTH = 1.5
WAIT_GROWTH_MIN_S = 0.25
WAIT_WINDOW_S = 3  # segundos para estimar la tasa de llegada en un instante
MIN_SECONDS_FOR_GROWTH = 4  # con menos, no hay mitad y final que comparar: no se avisa
BOTTLENECK_MIN = 0.5  # bajo esto no se habla de cuello de botella
ARRIVALS = ("poisson", "uniform")
CPU_CREDITS = ("sustained", "burst")
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
    cpu_credits: str = "sustained",
    traffic_profile: TrafficProfile | None = None,
) -> Run:
    """Simula ``duration_s`` segundos de tráfico y devuelve el ``Run``.

    ``rps`` reemplaza la tasa del escenario. ``arrivals``: ``poisson`` (usuarios reales) o
    ``uniform`` (como k6 con tasa constante, útil para comparar con mediciones).
    ``traffic_profile`` (JAJ-71) hace que la tasa cambie en el tiempo: es la tasa base multiplicada
    por el perfil en cada instante, y la duración pasa a ser la del perfil.
    ``cache_hit_ratio`` reemplaza la tasa de aciertos de todas las cachés con ``on_miss``.
    ``cpu_credits``: en una DB con créditos de CPU, ``sustained`` (vCPU sostenidos) o ``burst``.
    """
    if arrivals not in ARRIVALS:
        raise ValueError(f"arrivals debe ser uno de {ARRIVALS}")
    if cpu_credits not in CPU_CREDITS:
        raise ValueError(f"cpu_credits debe ser uno de {CPU_CREDITS}")
    if cache_hit_ratio is not None and not 0.0 <= cache_hit_ratio <= 1.0:
        raise ValueError("cache_hit_ratio debe estar entre 0 y 1")
    rate = rps if rps is not None else model.scenario(scenario).rps
    if traffic_profile is not None:
        duration_s = traffic_profile.duration_s
    if rate <= 0 or duration_s <= 0:
        raise ValueError("rps y duration_s deben ser mayores que 0")
    wall_start = time.perf_counter()
    sim = Sim(seed)
    warnings = list(model.warnings)

    cpu = _cpu_adjustment(model, cpu_credits, warnings)
    api_cpu, api_scale = _cores(sim, "api_cpu", model.api.cores)
    db_cpu, db_scale = _cores(sim, "db_cpu", cpu.db_vcpu_effective)
    api_scale *= cpu.api_core_factor
    db_scale *= cpu.db_core_factor
    threads = Resource(sim, "api_threads", model.api.threads)
    pool_capacity, refuse_at = _connection_limits(model, warnings)
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
    usage = UsageTracker()
    in_flight: dict[int, tuple[Endpoint, float]] = {}
    api_latency_s = model.api.latency_ms / 1000
    pool_timeout_s = model.db.pool_timeout_s

    def hold(res: Resource, scale: float, ms: float, owner: str, at: str | None) -> Generator[Any, Any, None]:
        yield res.acquire()
        seconds = ms * scale / 1000
        yield seconds
        res.release()
        usage.add(res.name, owner, at, seconds)

    def run_steps(steps: tuple[Step, ...], conn: list[Any] | None, owner: str) -> Generator[Any, Any, str | None]:
        """Recorre los pasos y devuelve el error, si hubo. ``conn``: ``[tiene conexión, desde cuándo,
        línea que la tomó]`` de la request; ``None`` en un trabajo de una cola (usa su propia conexión
        y su propia CPU). ``owner``: a nombre de quién se anota el uso de cada recurso."""
        for step in steps:
            res, ms = step.resource, step.time_ms
            for _ in range(step.repeat):
                if res == RESOURCE_DB_CONNECTION:
                    if conn is not None and not conn[0]:
                        if refuse_at is not None and pool.busy + pool.waiting >= refuse_at:
                            return ERROR_DB_REFUSED
                        if not (yield pool.acquire(pool_timeout_s)):
                            return ERROR_POOL_TIMEOUT
                        conn[:] = [True, sim.now, step.at]
                    if ms > 0:
                        yield from hold(db_cpu, db_scale, ms, owner, step.at)
                elif res == RESOURCE_API_CPU and conn is not None:
                    if ms > 0:
                        yield from hold(api_cpu, api_scale, ms, owner, step.at)
                elif res == RESOURCE_CACHE and step.on_miss is not None:
                    if ms > 0:
                        yield ms / 1000  # GET
                    hit = step.hit_ratio if cache_hit_ratio is None else cache_hit_ratio
                    if sim.rng.random() < hit:
                        cache[0] += 1
                        continue
                    cache[1] += 1
                    error = yield from run_steps(step.on_miss, conn, owner)
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
        owner = f"cola {q.config.name}"
        yield q.resource.acquire()
        started = sim.now
        yield from run_steps(q.config.job_steps, None, owner)
        q.resource.release()
        usage.add(q.resource.name, owner, None, sim.now - started)
        q.processed += 1
        q.latencies_ms.append((sim.now - t0) * 1000)

    def request(ep: Endpoint, rid: int) -> Generator[Any, Any, None]:
        t0 = sim.now
        in_flight[rid] = (ep, t0)
        if api_latency_s:
            yield api_latency_s
        if not ep.is_async:
            yield threads.acquire()
            thread_since = sim.now
        if ep.base_cpu_ms > 0:
            yield from hold(api_cpu, api_scale, ep.base_cpu_ms, ep.id, None)
        conn: list[Any] = [False, 0.0, None]
        error = yield from run_steps(ep.steps, conn, ep.id)
        if conn[0]:
            pool.release()
            usage.add(pool.name, ep.id, conn[2], sim.now - conn[1])
        if not ep.is_async:
            threads.release()
            usage.add(threads.name, ep.id, None, sim.now - thread_since)
        del in_flight[rid]
        rec.finish(ep, t0, sim.now, error, client_timeout_s)

    endpoints = model.endpoints
    cumulative = list(accumulate(e.weight for e in endpoints))

    rid = 0

    def arrive() -> None:
        nonlocal rid
        i = min(bisect_right(cumulative, sim.rng.random() * cumulative[-1]), len(endpoints) - 1)
        rid += 1
        rec.arrival(endpoints[i], sim.now)
        sim.start(request(endpoints[i], rid))

    def source() -> Generator[Any, Any, None]:
        while True:
            yield sim.rng.expovariate(rate) if arrivals == "poisson" else 1.0 / rate
            if sim.now >= duration_s:
                return
            arrive()

    def profiled_source(profile: TrafficProfile) -> Generator[Any, Any, None]:
        """Llegadas con tasa ``rate × perfil(t)`` (JAJ-71).

        Poisson: se generan candidatas a la tasa del pico y se acepta cada una con probabilidad
        ``perfil(t) / pico`` (thinning, el método estándar para un Poisson con tasa variable).
        Uniforme: la siguiente llega ``1 / tasa(t)`` segundos después; si eso cruza el borde del tramo,
        se salta al borde y se vuelve a calcular con la tasa nueva.
        """
        peak = profile.peak
        while sim.now < duration_s:
            if arrivals == "poisson":
                yield sim.rng.expovariate(rate * peak)
                if sim.now >= duration_s:
                    return
                if sim.rng.random() * peak < profile.multiplier_at(sim.now):
                    arrive()
                continue
            lam = rate * profile.multiplier_at(sim.now)
            boundary = profile.next_change(sim.now)
            if lam <= 0 or sim.now + 1.0 / lam > boundary:
                yield boundary - sim.now
                continue
            yield 1.0 / lam
            if sim.now >= duration_s:
                return
            arrive()

    def sampler() -> Generator[Any, Any, None]:
        for _ in range(rec.seconds):
            yield 1.0
            rec.sample()

    sim.start(source() if traffic_profile is None else profiled_source(traffic_profile))
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
        cpu,
        usage,
        traffic_profile,
    )


def _profile_segments(profile: TrafficProfile | None, rate: float) -> list[ProfileSegment] | None:
    """El perfil en req/s, con el segundo de inicio y de fin de cada tramo, para el gráfico."""
    if profile is None:
        return None
    out, start = [], 0.0
    for seg in profile.segments:
        out.append(
            ProfileSegment(
                start_s=round(start, 3),
                end_s=round(start + seg.duration_s, 3),
                from_rps=round(rate * seg.from_multiplier, 3),
                to_rps=round(rate * seg.to_multiplier, 3),
            )
        )
        start += seg.duration_s
    return out


def _cpu_adjustment(model: ArchitectureModel, cpu_credits: str, warnings: list[str]) -> CpuAdjustment:
    """Factor laptop → nube de la API y la DB, y vCPU con que se simula la DB (JAJ-48).

    Deja en ``warnings`` qué se ajustó, para que el usuario sepa que la capacidad es la de la nube.
    """
    api, db = model.api, model.db
    adjusted = [
        f"{name} ×{factor:g}" + (f" ({processor})" if processor else "")
        for name, factor, processor in (("API", api.core_factor, api.processor), ("DB", db.core_factor, db.processor))
        if factor != 1.0
    ]
    if adjusted:
        warnings.append(
            "Capacidad de la nube: los tiempos de CPU del modelo son de 1 núcleo del laptop de calibración "
            f"y se multiplican por el factor de cada procesador: {', '.join(adjusted)} (JAJ-46)."
        )

    db_vcpu, credits = db.vcpu, None
    if db.sustained_vcpu is not None:
        credits = cpu_credits
        plan = f"La DB ({db.plan})" if db.plan else "La DB"
        if cpu_credits == "sustained":
            db_vcpu = db.sustained_vcpu
            warnings.append(
                f"{plan} tiene créditos de CPU: se simula con {db.sustained_vcpu:g} vCPU sostenidos de {db.vcpu:g} "
                f"(la base de créditos con carga sostenida). Con cpu_credits=burst se simulan los {db.vcpu:g} vCPU, "
                "que solo se mantienen mientras duren los créditos o pagando el exceso."
            )
        else:
            warnings.append(
                f"{plan} tiene créditos de CPU: se simula con sus {db.vcpu:g} vCPU completos (burst). Con carga "
                f"sostenida eso solo dura mientras haya créditos o pagando el exceso; la base es {db.sustained_vcpu:g} vCPU."
            )
    return CpuAdjustment(
        api_core_factor=api.core_factor,
        api_processor=api.processor,
        db_core_factor=db.core_factor,
        db_processor=db.processor,
        db_vcpu=db.vcpu,
        db_vcpu_effective=db_vcpu,
        cpu_credits=credits,
    )


def _connection_limits(model: ArchitectureModel, warnings: list[str]) -> tuple[int, int | None]:
    """Conexiones que se simulan y desde cuántas en uso (o esperando) se rechaza una nueva.

    * La app abre como máximo ``app_connections`` (pool por worker × workers × réplicas). Si llega a
      ese tope, la request espera en el pool de la app, con su timeout.
    * Sin pooler, la app se conecta directo a la DB: si puede abrir más de las que la DB acepta,
      nunca llega a esperar en su pool, y la conexión que pasa el límite falla (``db_refused``).
    * Con pooler (modo transacción), la app se conecta al pooler, que acepta ``pooler_connections``
      clientes y los reparte en las ``max_connections`` de la DB: los que no tienen una, esperan.
    """
    app, db_max, pooler = model.app_connections, model.db.max_connections, model.db.pooler_connections
    capacity = min(app, db_max) if db_max else app
    if pooler is None:
        if db_max and app > db_max:
            warnings.append(
                f"La app puede abrir {app} conexiones y la DB acepta {db_max}: las que pasen de {db_max} "
                f"fallan al conectarse (error db_refused). Un pooler las haría esperar en vez de fallar."
            )
            return capacity, db_max
        return capacity, None
    if app > pooler:
        warnings.append(
            f"La app puede abrir {app} conexiones y el pooler acepta {pooler} clientes: las que pasen de "
            f"{pooler} fallan al conectarse (error db_refused)."
        )
        return capacity, pooler
    return capacity, None


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
    cpu: CpuAdjustment,
    usage: UsageTracker,
    profile: TrafficProfile | None,
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
            by_endpoint=usage.by_endpoint(r.name),
            by_line=usage.by_line(r.name),
        )
        for r in resources
    ]
    ok = sum(rec.ok)
    errors = sum(rec.error_types.values())
    all_latencies = [ms for second in rec.latencies_ms for ms in second]

    requests = sum(rec.arrivals)
    saturation = _saturation(requests, errors, still_running, duration_s, resource_stats, rec)
    if saturation.message:
        warnings.insert(0, saturation.message)  # primero: es lo que cambia cómo leer el resto
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
        requests=requests,
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
        cpu=cpu,
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
                target_rps=round(rate * (profile.multiplier_at(i + 0.5) if profile else 1.0), 3),
            )
            for i in range(rec.seconds)
        ],
        traffic_profile=_profile_segments(profile, rate),
        elapsed_ms=round((time.perf_counter() - wall_start) * 1000, 1),
        saturation=saturation,
    )


def _pct(x: float) -> str:
    return f"{x * 100:.0f} %"


def _secs(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + " s"


def _implied_wait_s(rec: Recorder, second: int) -> float:
    """Espera que implica la fila al final del segundo ``second`` (Ley de Little: fila / tasa de llegada).

    La fila es lo que llegó y todavía no termina (ok o error). La tasa de llegada se estima con los
    últimos ``WAIT_WINDOW_S`` segundos, así un perfil que sube no se confunde con una fila que crece.
    Si en esa ventana no llegó nada (un perfil que baja a 0) pero queda fila, se usa la tasa promedio
    hasta ese segundo: con 0 la espera sería infinita, y devolver 0 escondería la fila.
    """
    backlog = sum(rec.arrivals[: second + 1]) - sum(rec.ok[: second + 1]) - sum(rec.errors[: second + 1])
    if backlog <= 0:
        return 0.0
    window = rec.arrivals[max(0, second + 1 - WAIT_WINDOW_S) : second + 1]
    arrival_rate = sum(window) / len(window) if window else 0.0
    if arrival_rate <= 0:
        arrival_rate = sum(rec.arrivals[: second + 1]) / (second + 1)
    return backlog / arrival_rate if arrival_rate > 0 else 0.0


def _saturation(
    requests: int, errors: int, unanswered: int, duration_s: float, stats: list[ResourceStats], rec: Recorder
) -> Saturation:
    """Si la fila crece sin parar y quedan muchas requests sin respuesta, el sistema no alcanza a atender
    (JAJ-89).

    ``error_rate`` no cuenta las requests sin respuesta (no son ok ni error todavía), así que un sistema
    colapsado puede dar "0 % de errores" con un p95 de decenas de segundos. Pero quedar en curso no basta
    para decir que está saturado: con un endpoint lento o una simulación corta, una fracción sana queda
    en curso (latencia / duración). Por eso se exigen las dos cosas: muchas sin respuesta
    (``UNANSWERED_SATURATED``) y una espera que crece entre la mitad y el final (``WAIT_GROWTH``).
    """
    rate = unanswered / requests if requests else 0.0
    worst = (errors + unanswered) / requests if requests else 0.0
    wait_mid = wait_end = 0.0
    growing = False
    if rec.seconds >= MIN_SECONDS_FOR_GROWTH:
        wait_mid = _implied_wait_s(rec, rec.seconds // 2 - 1)
        wait_end = _implied_wait_s(rec, rec.seconds - 1)
        growing = wait_end >= WAIT_GROWTH * wait_mid + WAIT_GROWTH_MIN_S
    saturated = rate >= UNANSWERED_SATURATED and growing
    message = None
    if saturated:
        queued = max(stats, key=lambda s: (s.final_queue, s.utilization), default=None)
        where = (
            f" La fila estaba en {queued.label} ({queued.final_queue} esperando)."
            if queued is not None and queued.final_queue
            else ""
        )
        message = (
            f"El sistema no alcanza a atender este tráfico: {unanswered} de {requests} requests ({_pct(rate)}) "
            f"seguían sin respuesta al terminar y no cuentan como error. La espera crece sin parar: unos "
            f"{_secs(wait_mid)} a la mitad y {_secs(wait_end)} al final.{where} Si terminaran fallando, la tasa de "
            f"error sería {_pct(worst)}. Simula más tiempo para ver los timeouts, o toma la tasa de error como piso."
        )
    return Saturation(
        saturated=saturated,
        offered_rps=round(requests / duration_s, 3) if duration_s > 0 else 0.0,
        unanswered=unanswered,
        unanswered_rate=round(rate, 4),
        error_rate_if_unanswered_fail=round(worst, 4),
        message=message,
        wait_mid_s=round(wait_mid, 3),
        wait_end_s=round(wait_end, 3),
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
    message += "."
    if not top.by_endpoint:
        return Bottleneck(top.name, top.utilization, message)
    # JAJ-69: qué código ocupa el recurso, para el banner del editor. Se nombra la línea que más lo
    # ocupa (sumando endpoints) y el endpoint que más lo ocupa.
    culprit = top.by_endpoint[0]
    line = top.by_line[0] if top.by_line else None
    if line:
        n = len(line.endpoints)
        message += f" El {line.share:.0%} se va en {line.at} ({n} endpoint{'s' if n != 1 else ''})."
    message += f" El endpoint que más lo ocupa es {culprit.endpoint} ({culprit.share:.0%})."
    return Bottleneck(
        top.name,
        top.utilization,
        message,
        line=line.at if line else None,
        line_share=line.share if line else None,
        line_endpoints=line.endpoints if line else [],
        endpoint=culprit.endpoint,
        endpoint_share=culprit.share,
        refs=culprit.refs,
    )
