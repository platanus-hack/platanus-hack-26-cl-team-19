"""Tests de quién ocupa cada recurso (JAJ-69): endpoint y línea de código detrás del cuello de botella."""

import importlib

import pytest

from app.engine import simulate
from app.engine.metrics import UsageTracker
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


# --- JAJ-100: lo que sigue tomado al terminar -----------------------------------------------------


def holds_and_waits(pool_size=10):
    """``GET /lento`` toma la conexión y espera 120 s a un servicio externo con ella tomada; ``GET
    /rapido`` hace una consulta de 1 ms. En 60 s, las conexiones las tiene /lento casi todo el tiempo,
    pero ninguna de sus requests termina."""
    raw = model_dict(
        [
            endpoint("GET /rapido", [query(1, "rapido.py:1")], weight=0.9, api_cpu_ms=0.1),
            endpoint(
                "GET /lento",
                [
                    query(1, "lento.py:1"),
                    {"kind": "external", "resource": "external", "time": 120_000, "at": "lento.py:2"},
                ],
                weight=0.1,
                api_cpu_ms=0.1,
            ),
        ]
    )
    raw["deployment"]["db"]["pool_per_worker"]["pool_size"] = pool_size
    return raw


def test_resource_still_held_at_the_end_counts_for_whoever_holds_it():
    """BE-04: antes, el uso se anotaba al soltar. /lento nunca soltaba y quedaba en 0 %, y el banner
    culpaba a /rapido del 100 % del pool."""
    run = simulate(load_model(holds_and_waits()), rps=20, duration_s=60, seed=1, client_timeout_s=None)
    pool = resource(run, "db_pool")
    assert pool.utilization > 0.9
    assert pool.by_endpoint[0].endpoint == "GET /lento" and pool.by_endpoint[0].share > 0.9
    assert run.bottleneck.resource == "db_pool" and run.bottleneck.line == "lento.py:1"
    assert run.bottleneck.endpoint == "GET /lento"


@pytest.mark.parametrize("seconds", [5, 60])
def test_attributed_time_matches_utilization(monkeypatch, seconds):
    """Lo que se reparte entre endpoints es todo el tiempo ocupado: la suma de lo anotado de cada
    recurso calza con utilization × capacidad × duración, también con requests y trabajos en curso."""
    trackers = []

    class Spy(UsageTracker):
        def __init__(self):
            super().__init__()
            trackers.append(self)

    monkeypatch.setattr(importlib.import_module("app.engine.simulate"), "UsageTracker", Spy)  # el módulo, no la función
    raw = holds_and_waits()
    raw["endpoints"].append(
        endpoint("POST /sync", [cpu(30, "sync.py:1"), query(5, "sync.py:2")], weight=0.2, is_async=False)
    )
    raw["deployment"]["queues"] = {
        "q": {"workers": 2, "job_steps": [{"kind": "cpu", "resource": None, "time": 2000, "at": "job.py:1"}]}
    }
    raw["endpoints"].append(
        endpoint(
            "POST /encola", [{"kind": "background", "resource": "background", "time": 1, "queue": "q"}], weight=0.2
        )
    )
    run = simulate(load_model(raw), rps=20, duration_s=seconds, seed=1, client_timeout_s=None)
    seconds_by_resource = {
        r: sum(sum(lines.values()) for lines in owners.values()) for r, owners in trackers[0]._seconds.items()
    }
    for r in run.resources:
        expected = r.utilization * r.capacity * seconds
        assert seconds_by_resource.get(r.name, 0.0) == pytest.approx(expected, abs=5e-5 * r.capacity * seconds), (
            r.name
        )  # utilization va redondeada a 4 decimales
