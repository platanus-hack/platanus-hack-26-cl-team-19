"""Tests de la caché con ``on_miss`` y de las colas con workers asíncronos (JAJ-14).

La caché se compara con lo medido en JAJ-44 (Postgres + Redis reales, k6 con tasa constante).
Las colas, con cuentas a mano: uso = tasa × duración / workers.
"""

import copy

import pytest

from app.engine import simulate
from app.models import load_model

# JAJ-44, prueba de caché (results/jaj44/cal_cache.json y real_cache.csv del spike):
# pool de 5 conexiones, consulta de 20,8 ms, 50 % de aciertos, API con 0,79 ms de CPU y 0,37 ms de red.
JAJ44_QUERY_MS = 20.78
JAJ44_REAL_P95_MS = {96: 23, 193: 22, 289: 22, 385: 28, 433: 44}  # medido con k6 (433 = 89 % del pool)


def model_dict(steps, queues=None, db_vcpu=8):
    return {
        "schema": "branchpoint.model/v1",
        "repo": {"path": "sintetico"},
        "deployment": {
            "api": {"replicas": 1, "vcpu": 1, "workers": 1, "threads_per_worker": 40, "latency_ms": 0.37},
            "db": {
                "vcpu": db_vcpu,
                "max_connections": 100,
                "pool_per_worker": {"pool_size": 5, "max_overflow": 0, "pool_timeout_s": 30},
            },
            "queues": queues or {},
        },
        "endpoints": [{"id": "GET /x", "weight": 1, "async": True, "api_cpu_ms": 0.79, "steps": steps}],
        "traffic": {"scenarios": {"base": {"rps": 100}}},
    }


def cached_query(hit_ratio=0.5):
    step = {
        "kind": "cache",
        "resource": "cache",
        "time": 0.0,
        "at": "app.py:1",
        "on_miss": [{"kind": "db", "resource": "db_connection", "time": JAJ44_QUERY_MS, "at": "app.py:2"}],
    }
    if hit_ratio is not None:
        step["hit_ratio"] = {"value": hit_ratio, "label": "OBSERVADO"}
    return step


def resource(run, name):
    return next(r for r in run.resources if r.name == name)


# --- caché ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("rate", sorted(JAJ44_REAL_P95_MS))
def test_cache_matches_jaj44(rate):
    """Con 50 % de aciertos, el p95 queda a ±15 % de lo medido en JAJ-44 (hasta el 89 % del pool)."""
    run = simulate(load_model(model_dict([cached_query(0.5)])), rps=rate, duration_s=20, arrivals="uniform")
    real = JAJ44_REAL_P95_MS[rate]
    assert sum(run.errors.values()) == 0
    assert abs(run.latency.p95_ms - real) / real < 0.15, f"{rate} req/s: p95 {run.latency.p95_ms} vs {real} ms"
    assert run.cache.hit_rate == pytest.approx(0.5, abs=0.03)


def test_cache_halves_pool_use():
    """Uso del pool = tasa × fallos × consulta / conexiones. Sin caché, 385 req/s superan el pool."""
    rate = 385
    with_cache = simulate(load_model(model_dict([cached_query(0.5)])), rps=rate, duration_s=20, arrivals="uniform")
    expected = rate * 0.5 * JAJ44_QUERY_MS / 1000 / 5
    assert resource(with_cache, "db_pool").utilization == pytest.approx(expected, rel=0.05)

    no_cache = simulate(load_model(model_dict([cached_query(0.0)])), rps=rate, duration_s=20, arrivals="uniform")
    assert no_cache.bottleneck.resource == "db_pool"
    assert resource(no_cache, "db_pool").final_queue > 0


def test_cache_always_hits_skips_db():
    run = simulate(load_model(model_dict([cached_query(1.0)])), rps=200, duration_s=10)
    assert run.cache.misses == 0 and run.cache.hits == run.requests - run.in_flight
    assert resource(run, "db_pool").utilization == 0


def test_cache_hit_ratio_override():
    model = load_model(model_dict([cached_query(0.5)]))
    run = simulate(model, rps=200, duration_s=10, cache_hit_ratio=0.9)
    assert run.cache.hit_rate == pytest.approx(0.9, abs=0.03)
    with pytest.raises(ValueError):
        simulate(model, rps=200, duration_s=10, cache_hit_ratio=1.5)


def test_cache_without_hit_ratio_warns_and_uses_worst_case():
    model = load_model(model_dict([cached_query(None)]))
    assert any("tasa de aciertos" in w for w in model.warnings)
    run = simulate(model, rps=50, duration_s=10)
    assert run.cache.hits == 0 and run.cache.misses > 0


def test_cache_without_on_miss_is_only_a_wait():
    step = {"kind": "cache", "resource": "cache", "time": 5.0, "at": "app.py:1"}
    run = simulate(load_model(model_dict([step])), rps=10, duration_s=10, arrivals="uniform")
    assert run.cache.hits == run.cache.misses == 0
    assert run.latency.p50_ms == pytest.approx(0.37 + 0.79 + 5.0, abs=0.01)


# --- colas ---------------------------------------------------------------------------------------

ENQUEUE = {"kind": "background", "resource": "background", "time": 0.03, "at": "app.py:3"}


def queue(workers=2, job_ms=100.0, max_length=None, db_ms=0.0):
    steps = [{"kind": "cpu", "resource": "api_cpu", "time": job_ms, "at": "worker.py:1"}]
    if db_ms:
        steps.append({"kind": "db", "resource": "db_connection", "time": db_ms, "at": "worker.py:2"})
    q = {"workers": {"value": workers}, "job_steps": steps}
    if max_length is not None:
        q["max_length"] = {"value": max_length}
    return {"emails": q}


def test_queue_under_capacity():
    """10 trabajos/s de 100 ms con 2 workers: uso 50 %, sin espera, y la request no espera al trabajo."""
    run = simulate(load_model(model_dict([ENQUEUE], queue())), rps=10, duration_s=30, arrivals="uniform")
    (q,) = run.queues
    assert resource(run, "queue:emails").utilization == pytest.approx(0.5, rel=0.05)
    assert resource(run, "queue:emails").label == "workers de la cola emails"
    assert q.final_backlog == 0 and q.rejected == 0
    assert q.processed >= q.enqueued - 2
    assert q.job_latency.p95_ms == pytest.approx(100.0, abs=0.01)
    assert run.latency.p95_ms < 2  # encolar es casi instantáneo


def test_queue_over_capacity_fills_and_rejects():
    """40 trabajos/s con capacidad de 20/s: la cola llega a su largo máximo y encolar falla."""
    run = simulate(load_model(model_dict([ENQUEUE], queue(max_length=20))), rps=40, duration_s=30)
    (q,) = run.queues
    assert q.max_backlog == 20
    assert q.rejected > 0 and run.errors["queue_full"] == q.rejected
    assert run.bottleneck.resource == "queue:emails"


def test_queue_without_limit_backlog_grows():
    run = simulate(load_model(model_dict([ENQUEUE], queue())), rps=40, duration_s=30, arrivals="uniform")
    (q,) = run.queues
    assert q.rejected == 0
    assert q.final_backlog > 500  # llegan 40/s y salen 20/s
    assert run.series[-1].queue["queue:emails"] > run.series[0].queue["queue:emails"]


def test_queue_jobs_use_db_cpu():
    """Los trabajos compiten por la CPU de la DB con la API: 10/s × 50 ms = 50 % de 1 vCPU."""
    raw = model_dict([ENQUEUE], queue(job_ms=1.0, db_ms=50.0), db_vcpu=1)
    run = simulate(load_model(raw), rps=10, duration_s=30, arrivals="uniform")
    assert resource(run, "db_cpu").utilization == pytest.approx(0.5, rel=0.05)
    assert resource(run, "db_pool").utilization == 0  # el worker no usa el pool de la API


def test_background_without_queue_config_warns():
    model = load_model(model_dict([ENQUEUE]))
    assert any("no tiene cola configurada" in w for w in model.warnings)
    run = simulate(model, rps=10, duration_s=10)
    assert run.queues == [] and sum(run.errors.values()) == 0


def test_named_queue_must_exist():
    raw = model_dict([{**ENQUEUE, "queue": "otra"}], queue())
    model = load_model(raw)
    assert any("no tiene cola configurada" in w for w in model.warnings)


def test_queue_same_seed_same_result():
    raw = copy.deepcopy(model_dict([cached_query(0.5), ENQUEUE], queue(max_length=50)))
    a = simulate(load_model(raw), rps=60, duration_s=10, seed=3).to_dict()
    b = simulate(load_model(raw), rps=60, duration_s=10, seed=3).to_dict()
    a.pop("elapsed_ms"), b.pop("elapsed_ms")
    assert a == b
