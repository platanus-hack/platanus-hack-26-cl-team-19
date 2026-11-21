"""Tests del paso de laptop a nube (JAJ-48): factor de núcleo y créditos de CPU de la DB.

Los tiempos del modelo son de 1 núcleo del laptop de calibración (JAJ-46). En la nube, la CPU de la
API y las consultas tardan ``cpu_core_factor`` veces más, así que la capacidad baja en ese factor.
"""

import copy

import pytest

from app.engine import simulate
from app.models import load_model
from app.samples import load_sample


def model_dict(api_factor=None, db_factor=None, db_vcpu=8, sustained=None, api_cpu_ms=10.0, query_ms=0.0):
    api = {"replicas": 1, "vcpu": 1, "workers": 1, "threads_per_worker": 40, "latency_ms": 0}
    db = {
        "vcpu": db_vcpu,
        "max_connections": 100,
        "pool_per_worker": {"pool_size": 50, "max_overflow": 0, "pool_timeout_s": 30},
    }
    if api_factor is not None:
        api["cpu_core_factor"] = {"value": api_factor, "label": "ESTIMADO", "processor": "graviton3"}
    if db_factor is not None:
        db["cpu_core_factor"] = {"value": db_factor, "label": "ESTIMADO", "processor": "graviton2"}
    if sustained is not None:
        db["plan"] = "db.t4g.medium"
        db["cpu_credits"] = {"sustained_vcpu": {"value": sustained, "label": "ESTIMADO"}}
    steps = [{"kind": "db", "resource": "db_connection", "time": query_ms, "at": "app.py:1"}] if query_ms else []
    return {
        "schema": "branchpoint.model/v1",
        "repo": {"path": "sintetico"},
        "deployment": {"api": api, "db": db},
        "endpoints": [{"id": "GET /x", "weight": 1, "async": True, "api_cpu_ms": api_cpu_ms, "steps": steps}],
        "traffic": {"scenarios": {"base": {"rps": 50}}},
    }


def util(run, name):
    return next(r for r in run.resources if r.name == name).utilization


def sim(raw, **kw):
    return simulate(load_model(raw), duration_s=60, arrivals="uniform", **kw)


# --- factor de núcleo ----------------------------------------------------------------------------


def test_factor_multiplies_api_cpu_use():
    """10 ms de CPU a 50 req/s = 50 % de 1 núcleo; con factor 1,55 es 77,5 %."""
    local = sim(model_dict(), rps=50)
    cloud = sim(model_dict(api_factor=1.55), rps=50)
    assert util(local, "api_cpu") == pytest.approx(0.50, rel=0.02)
    assert util(cloud, "api_cpu") == pytest.approx(0.50 * 1.55, rel=0.02)


def test_factor_saturates_at_capacity_over_factor():
    """Capacidad local: 100 req/s. Con factor 1,55 satura a ~100/1,55 = 64,5 req/s."""
    below, above = 0.9 * 100 / 1.55, 1.1 * 100 / 1.55  # 58 y 71 req/s
    ok = sim(model_dict(api_factor=1.55), rps=below)
    assert ok.bottleneck.resource == "api_cpu" and ok.resources[0].final_queue < 5
    over = sim(model_dict(api_factor=1.55), rps=above)
    assert over.resources[0].final_queue > 100  # la cola crece: llegan 71/s y salen 64,5/s
    assert sim(model_dict(), rps=above).resources[0].final_queue < 5  # en el laptop, 71 req/s se aguantan


def test_db_factor_scales_queries_and_connection_hold():
    """Una consulta de 10 ms tarda 19,5 ms con factor 1,95: la CPU de la DB y el pool se usan ×1,95."""
    local = sim(model_dict(api_cpu_ms=0.1, query_ms=10), rps=50)
    cloud = sim(model_dict(api_cpu_ms=0.1, query_ms=10, db_factor=1.95), rps=50)
    for resource in ("db_cpu", "db_pool"):
        assert util(cloud, resource) == pytest.approx(util(local, resource) * 1.95, rel=0.03)
    assert util(cloud, "api_cpu") == pytest.approx(util(local, "api_cpu"), rel=0.01)  # la API no cambia


def test_no_factor_keeps_times_and_says_nothing():
    run = sim(model_dict(), rps=50)
    assert run.cpu.api_core_factor == 1.0 and run.cpu.db_core_factor == 1.0
    assert run.cpu.cpu_credits is None
    assert not any("Capacidad de la nube" in w for w in run.warnings)


def test_factor_is_reported():
    run = sim(model_dict(api_factor=1.55, db_factor=1.95), rps=10)
    assert (run.cpu.api_core_factor, run.cpu.api_processor) == (1.55, "graviton3")
    assert (run.cpu.db_core_factor, run.cpu.db_processor) == (1.95, "graviton2")
    (warning,) = [w for w in run.warnings if "Capacidad de la nube" in w]
    assert "API ×1.55 (graviton3)" in warning and "DB ×1.95 (graviton2)" in warning


@pytest.mark.parametrize("factor", [0, -1])
def test_invalid_factor(factor):
    with pytest.raises(ValueError, match="cpu_core_factor"):
        load_model(model_dict(api_factor=factor))


# --- créditos de CPU (db.t4g.*) ------------------------------------------------------------------


def test_sustained_uses_baseline_vcpu():
    """2 vCPU con base de 0,4: 50 req/s × 4 ms = 0,2 vCPU → 50 % sostenido y 10 % en burst."""
    raw = model_dict(api_cpu_ms=0.1, query_ms=4, db_vcpu=2, sustained=0.4)
    sustained = sim(raw, rps=50)
    burst = sim(raw, rps=50, cpu_credits="burst")
    assert sustained.cpu.db_vcpu_effective == 0.4 and sustained.cpu.cpu_credits == "sustained"
    assert burst.cpu.db_vcpu_effective == 2 and burst.cpu.cpu_credits == "burst"
    assert util(sustained, "db_cpu") == pytest.approx(0.5, rel=0.03)
    assert util(burst, "db_cpu") == pytest.approx(0.1, rel=0.03)
    assert any("0.4 vCPU sostenidos de 2" in w for w in sustained.warnings)
    assert any("burst" in w for w in burst.warnings)


def test_burst_without_credits_changes_nothing():
    raw = model_dict(api_cpu_ms=0.1, query_ms=4)
    a, b = sim(raw, rps=50), sim(raw, rps=50, cpu_credits="burst")
    assert util(a, "db_cpu") == util(b, "db_cpu") and b.cpu.cpu_credits is None


def test_invalid_credits():
    with pytest.raises(ValueError, match="cpu_credits"):
        sim(model_dict(), rps=10, cpu_credits="unlimited")
    with pytest.raises(ValueError, match="sustained_vcpu"):
        load_model(model_dict(db_vcpu=2, sustained=3))


# --- modelos de ejemplo (JAJ-47) -----------------------------------------------------------------


@pytest.mark.parametrize("sample", ["full-stack-fastapi-template", "fastapi-realworld-example-app"])
def test_samples_match_checks(sample):
    """Bajo saturación, el uso del motor coincide con los checks de build_model (±10 %), y en CyberDay
    el cuello de botella es el mismo. Los checks ya aplican el factor y la base de créditos."""
    raw = load_sample(sample)
    model = load_model(raw)
    for name, check in raw["checks"]["scenarios"].items():
        run = simulate(model, name, duration_s=120, seed=1)
        assert run.cpu.api_core_factor == 1.95 and run.cpu.db_core_factor == 1.95
        assert any("Capacidad de la nube" in w for w in run.warnings)
        for resource in ("api_cpu", "db_cpu"):
            expected = check["utilization"][resource]
            if expected < 0.9:
                assert util(run, resource) == pytest.approx(expected, rel=0.1), f"{name} {resource}"
        if name == "cyberday":
            assert run.bottleneck.resource == check["bottleneck"]


def test_realworld_t4g_burst_relieves_db():
    """El db.t4g.medium de realworld: 0,4 vCPU sostenidos. En burst, la CPU de la DB baja 5 veces."""
    model = load_model(copy.deepcopy(load_sample("fastapi-realworld-example-app")))
    sustained = simulate(model, "pico_normal", duration_s=60)
    burst = simulate(model, "pico_normal", duration_s=60, cpu_credits="burst")
    assert sustained.cpu.db_vcpu_effective == 0.4 and burst.cpu.db_vcpu_effective == 2
    assert util(burst, "db_cpu") == pytest.approx(util(sustained, "db_cpu") / 5, rel=0.1)


def test_queue_jobs_scale_their_queries_but_not_the_worker_cpu():
    """JAJ-110: en un trabajo de una cola, la consulta corre en la DB y usa su factor; la CPU del worker
    va sin ajustar, porque el modelo no dice en qué procesador corren los workers."""
    raw = model_dict(db_factor=2.0, api_cpu_ms=1.0)
    raw["deployment"]["queues"] = {
        "consulta": {
            "workers": 1,
            "job_steps": [{"kind": "db", "resource": "db_connection", "time": 100, "at": "j.py:1"}],
        },
        "cpu": {"workers": 1, "job_steps": [{"kind": "cpu", "resource": None, "time": 100, "at": "j.py:2"}]},
    }
    raw["endpoints"][0]["steps"] = [
        {"kind": "background", "resource": "background", "time": 0, "queue": "consulta"},
        {"kind": "background", "resource": "background", "time": 0, "queue": "cpu"},
    ]
    run = sim(raw, rps=1)
    p50 = {q.name: q.job_latency.p50_ms for q in run.queues}
    assert p50["consulta"] == pytest.approx(200.0) and p50["cpu"] == pytest.approx(100.0)
