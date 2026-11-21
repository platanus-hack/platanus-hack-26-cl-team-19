"""Tests de quién ocupa cada recurso (JAJ-69): endpoint y línea de código detrás del cuello de botella."""

import pytest

from app.engine import simulate
from app.models import load_model
from app.models.architecture import walk_steps
from app.samples import load_sample


def endpoint(eid, steps, weight=1, is_async=True, api_cpu_ms=None):
    cpu_steps = sum(s["time"] for s in steps if s["resource"] == "api_cpu")
    return {
        "id": eid,
        "weight": weight,
        "async": is_async,
        "api_cpu_ms": cpu_steps if api_cpu_ms is None else api_cpu_ms,
        "steps": steps,
    }


def cpu(ms, at):
    return {"kind": "cpu", "resource": "api_cpu", "time": ms, "at": at}


def query(ms, at):
    return {"kind": "db", "resource": "db_connection", "time": ms, "at": at}


def model_dict(endpoints, queues=None):
    return {
        "schema": "branchpoint.model/v1",
        "repo": {"path": "sintetico"},
        "deployment": {
            "api": {"replicas": 1, "vcpu": 1, "workers": 1, "threads_per_worker": 40, "latency_ms": 0},
            "db": {
                "vcpu": 4,
                "max_connections": 100,
                "pool_per_worker": {"pool_size": 20, "max_overflow": 0, "pool_timeout_s": 30},
            },
            "queues": queues or {},
        },
        "endpoints": endpoints,
        "traffic": {"scenarios": {"base": {"rps": 50}}},
    }


def resource(run, name):
    return next(r for r in run.resources if r.name == name)


def sim(raw, rps=50, **kw):
    return simulate(load_model(raw), rps=rps, duration_s=60, arrivals="uniform", **kw)


def test_shares_follow_cpu_time_and_sum_to_one():
    """Mismo tráfico: A gasta 8 ms y B 2 ms de CPU, así que A ocupa el 80 % y B el 20 %."""
    raw = model_dict([endpoint("GET /a", [cpu(8, "a.py:1")]), endpoint("GET /b", [cpu(2, "b.py:1")])])
    usage = resource(sim(raw), "api_cpu").by_endpoint
    assert [u.endpoint for u in usage] == ["GET /a", "GET /b"]
    assert usage[0].share == pytest.approx(0.8, abs=0.03)
    assert usage[0].refs == ["a.py:1"]
    assert sum(u.share for u in usage) == pytest.approx(1, abs=1e-3)


def test_bottleneck_points_to_endpoint_and_line():
    """Sobre la capacidad (200 req/s × 5 ms = 100 %), el cuello de botella nombra a A y su línea."""
    raw = model_dict([endpoint("GET /a", [cpu(8, "a.py:1")]), endpoint("GET /b", [cpu(2, "b.py:1")])])
    b = sim(raw, rps=200).bottleneck
    assert b.resource == "api_cpu"
    assert (b.endpoint, b.refs, b.line) == ("GET /a", ["a.py:1"], "a.py:1")
    assert b.endpoint_share == pytest.approx(0.8, abs=0.03)
    assert "a.py:1" in b.message and "GET /a" in b.message


def test_shared_line_adds_up_across_endpoints():
    """El hash de contraseña lo usan dos endpoints: cada uno ocupa ~50 %, pero la línea junta ~91 %."""
    raw = model_dict(
        [
            endpoint("POST /login", [cpu(5, "security.py:10")]),
            endpoint("POST /users", [cpu(5, "security.py:10"), cpu(1, "users.py:4")]),
        ]
    )
    run = sim(raw, rps=180)
    lines = resource(run, "api_cpu").by_line
    assert lines[0].at == "security.py:10"
    assert lines[0].share == pytest.approx(10 / 11, abs=0.02)
    assert set(lines[0].endpoints) == {"POST /login", "POST /users"}
    assert run.bottleneck.line == "security.py:10"
    assert "2 endpoints" in run.bottleneck.message


def test_time_without_line_counts_but_has_no_ref():
    """La CPU propia del framework (sin paso) cuenta en el reparto, pero no aparece como línea."""
    raw = model_dict([endpoint("GET /a", [cpu(2, "a.py:1")], api_cpu_ms=4)])  # 2 ms base sin línea
    r = resource(sim(raw), "api_cpu")
    assert r.by_endpoint[0].share == pytest.approx(1)
    assert r.by_line[0].at == "a.py:1"
    assert r.by_line[0].share == pytest.approx(0.5, abs=0.02)


def test_pool_goes_to_the_query_that_took_the_connection():
    """La conexión se toma en la primera consulta y se retiene hasta el final: el pool se anota a esa línea."""
    raw = model_dict([endpoint("GET /a", [query(4, "repo.py:1"), query(6, "repo.py:2")])])
    r = resource(sim(raw), "db_pool")
    assert [line.at for line in r.by_line] == ["repo.py:1"]
    db = resource(sim(raw), "db_cpu")
    assert [line.at for line in db.by_line] == ["repo.py:2", "repo.py:1"]  # 6 ms antes que 4 ms


def test_sync_endpoints_hold_threads():
    raw = model_dict([endpoint("GET /a", [cpu(2, "a.py:1")], is_async=False)])
    r = resource(sim(raw), "api_threads")
    assert r.by_endpoint[0].endpoint == "GET /a" and r.by_line == []


def test_queue_jobs_are_named_after_their_queue():
    enqueue = {"kind": "background", "resource": "background", "time": 0.03, "at": "app.py:9"}
    queues = {"emails": {"workers": {"value": 1}, "job_steps": [query(10, "worker.py:3")]}}
    run = sim(model_dict([endpoint("POST /signup", [enqueue])], queues), rps=20)
    assert resource(run, "queue:emails").by_endpoint[0].endpoint == "cola emails"
    assert resource(run, "db_cpu").by_line[0].endpoints == ["cola emails"]


def test_idle_resource_has_no_usage():
    run = sim(model_dict([endpoint("GET /a", [cpu(1, "a.py:1")])]))
    assert resource(run, "db_pool").by_endpoint == [] and resource(run, "db_pool").by_line == []


def test_template_cyberday_points_to_password_hash():
    """En el template, más de la mitad de la CPU de la API se va en una línea de hash de contraseña.

    Hay dos: la que crea el hash (crear usuario, signup, cambiar clave...) y la que lo verifica (login).
    """
    raw = load_sample("full-stack-fastapi-template")
    model = load_model(raw)
    hash_lines = {s.at for e in model.endpoints for s in walk_steps(e.steps) if s.shape == "password_hash"}
    b = simulate(model, "cyberday", seed=1).bottleneck
    assert b.resource == "api_cpu"
    assert b.line in hash_lines
    assert b.line_share > 0.5
    assert len(b.line_endpoints) >= 2
