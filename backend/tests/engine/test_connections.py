"""Límite de conexiones de la DB, con y sin pooler (JAJ-68).

Sistema sintético: 4 workers × pool de 10 = 40 conexiones posibles; la DB acepta 20. Cada request
toma una conexión durante 100 ms, así que a 300 req/s se necesitan ~30 a la vez (ley de Little).
"""

from app.engine import simulate
from app.models import load_model

QUERY_MS = 100
RATE = 300


def model_dict(max_connections=20, pooler=None):
    db = {
        "vcpu": 64,  # que la CPU de la DB no sea el cuello: solo importan las conexiones
        "max_connections": max_connections,
        "pool_per_worker": {"pool_size": 10, "max_overflow": 0, "pool_timeout_s": 30},
    }
    if pooler is not None:
        db["pooler"] = {"client_connections": pooler}
    return {
        "schema": "branchpoint.model/v1",
        "repo": {"path": "sintetico"},
        "deployment": {
            "api": {"replicas": 1, "vcpu": 4, "workers": 4, "threads_per_worker": 40, "latency_ms": 0},
            "db": db,
        },
        "endpoints": [
            {
                "id": "GET /x",
                "weight": 1,
                "async": True,
                "api_cpu_ms": 0,
                "steps": [{"kind": "db", "resource": "db_connection", "time": QUERY_MS, "at": "app.py:1"}],
            }
        ],
        "traffic": {"scenarios": {"base": {"rps": RATE}}},
    }


def run(**kw):
    return simulate(load_model(model_dict(**kw)), "base", seed=0, duration_s=20)


def test_without_pooler_connections_over_db_limit_are_refused():
    r = run()
    assert r.errors["db_refused"] > 0
    assert r.errors["pool_timeout"] == 0  # nunca espera en el pool: la DB rechaza antes
    assert any("fallan al conectarse" in w for w in r.warnings)


def test_with_pooler_connections_wait_instead_of_failing():
    r = run(pooler=200)
    assert r.errors["db_refused"] == 0
    assert not any("fallan al conectarse" in w for w in r.warnings)
    pool = next(x for x in r.resources if x.name == "db_pool")
    assert pool.capacity == 20  # el pooler no agrega conexiones a Postgres: solo hace esperar


def test_pooler_smaller_than_app_still_refuses():
    r = run(pooler=25)
    assert r.errors["db_refused"] > 0
    assert any("el pooler acepta 25" in w for w in r.warnings)


def test_app_within_db_limit_unchanged():
    r = run(max_connections=100)
    assert r.errors["db_refused"] == 0
    assert not any("conectarse" in w for w in r.warnings)
