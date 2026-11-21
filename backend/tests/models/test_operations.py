"""Tests de las operaciones tipadas de propose_version (JAJ-68).

Criterios de la tarjeta: cada operación deja un modelo que carga y simula; en el template,
``scale_api(3)`` sin pooler supera las conexiones de Supabase Micro y ``add_pooler`` lo resuelve; y
ningún número nuevo queda sin ``label``, ``source`` ni ``date``.
"""

import copy

import pytest

from app.catalog import LABELS
from app.engine import simulate
from app.models import load_model
from app.models.operations import (
    AddCache,
    AddPooler,
    ChangeDbPlan,
    MoveToQueue,
    OperationError,
    ScaleApi,
    apply_operations,
    parse_operation,
)
from app.samples import load_sample

TEMPLATE = "full-stack-fastapi-template"
REALWORLD = "fastapi-realworld-example-app"


@pytest.fixture
def template():
    return load_sample(TEMPLATE)


def numbers(obj, path=""):
    """Todos los números con procedencia del modelo: (ruta, dict)."""
    if isinstance(obj, dict):
        if "value" in obj and "unit" in obj:
            yield path, obj
        for k, v in obj.items():
            yield from numbers(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from numbers(v, f"{path}[{i}]")


def assert_new_numbers_have_provenance(before, after):
    old = dict(numbers(before))
    new = [(p, n) for p, n in numbers(after) if old.get(p) != n]
    assert new, "la operación no cambió ningún número"
    for path, n in new:
        assert n.get("label") in LABELS, f"{path} sin etiqueta válida: {n}"
        assert n.get("source"), f"{path} sin fuente"
        assert n.get("date"), f"{path} sin fecha"


def run(raw, scenario="cyberday", **kw):
    return simulate(load_model(raw), scenario, duration_s=20, seed=1, **kw)


def resource(r, name):
    return next(x for x in r.resources if x.name == name)


# --- criterio de la tarjeta: pooler -------------------------------------------------------------


def test_scale_api_without_pooler_hits_supabase_micro_connections(template):
    """3 réplicas × 4 workers × 15 conexiones = 180 > 60 de Supabase Micro: el motor lo advierte."""
    scaled, _ = apply_operations(template, [ScaleApi(replicas=3)])
    r = run(scaled)
    assert resource(r, "db_pool").capacity == 60
    assert any("La app puede abrir 180 conexiones y la DB acepta 60" in w for w in r.warnings)


def test_add_pooler_lifts_the_connection_limit(template):
    pooled, changes = apply_operations(template, [ScaleApi(replicas=3), AddPooler()])
    r = run(pooled)
    assert resource(r, "db_pool").capacity == 180  # el pooler de Micro acepta 200 (catálogo, JAJ-11)
    assert not any("la DB acepta 60:" in w for w in r.warnings)
    assert any("supavisor" in w for w in r.warnings)
    assert changes[1].startswith("Pooler supavisor")
    assert pooled["deployment"]["db"]["pooler"]["max_client_connections"]["value"] == 200


# --- cada operación: carga, simula, y sus números tienen procedencia ----------------------------


@pytest.mark.parametrize(
    "op",
    [
        ScaleApi(replicas=2, vcpu=2),
        ChangeDbPlan(plan="small"),
        ChangeDbPlan(plan="db.t4g.medium", provider="rds_postgres"),
        AddPooler(),
        AddCache(endpoint="GET /items/", hit_ratio=0.8, quote="el 80 % de las lecturas se repiten"),
    ],
    ids=lambda op: op.op,
)
def test_each_operation_loads_simulates_and_labels_numbers(template, op):
    after, changes = apply_operations(template, [op])
    assert_new_numbers_have_provenance(template, after)
    assert run(after, "pico_normal").requests > 0
    assert len(changes) == 1 and changes[0]


def test_operations_are_pure(template):
    original = copy.deepcopy(template)
    apply_operations(template, [ScaleApi(replicas=4), AddPooler(), AddCache(endpoint="GET /items/", hit_ratio=0.5)])
    assert template == original


def test_history_and_stale_checks(template):
    after, _ = apply_operations(template, [ScaleApi(replicas=2, quote="vamos a tener 2 réplicas")])
    (entry,) = after["operations"]
    assert entry["op"] == "scale_api" and entry["args"] == {"replicas": 2, "quote": "vamos a tener 2 réplicas"}
    assert "stale" in after["checks"]


# --- scale_api ----------------------------------------------------------------------------------


def test_scale_api_recomputes_cost_and_uses_quote(template):
    before = template["deployment"]["api"]["usd_month"]["value"]
    after, change = apply_operations(template, [ScaleApi(replicas=3, quote="queremos 3 réplicas")])
    api = after["deployment"]["api"]
    assert api["usd_month"]["value"] == pytest.approx(before * 3, abs=0.02)
    assert api["replicas"]["source"] == "Declarado por el usuario: «queremos 3 réplicas» (réplicas de la API)"
    assert "needs_review" not in api["replicas"]
    assert change == ["API: 1 → 3 réplicas"]


def test_number_without_quote_needs_review(template):
    after, _ = apply_operations(template, [ScaleApi(replicas=2)])
    assert after["deployment"]["api"]["replicas"]["needs_review"] is True


# --- change_db_plan -----------------------------------------------------------------------------


def test_change_db_plan_supabase_small(template):
    after, change = apply_operations(template, [ChangeDbPlan(plan="small")])
    db = after["deployment"]["db"]
    assert (db["plan"], db["vcpu"]["value"], db["max_connections"]["value"]) == ("small", 0.5, 90)
    assert db["usd_month"]["value"] == 30  # 25 + max(0, 15 − 10)
    assert db["pooler_connections"]["value"] == 400
    assert "micro → supabase small" in change[0]


def test_change_db_plan_credits_come_and_go(template):
    t4g, _ = apply_operations(template, [ChangeDbPlan(plan="db.t4g.medium", provider="rds_postgres")])
    assert t4g["deployment"]["db"]["cpu_credits"]["sustained_vcpu"]["value"] == 0.4
    assert "pooler_connections" not in t4g["deployment"]["db"]
    m7g, _ = apply_operations(t4g, [ChangeDbPlan(plan="db.m7g.large")])
    db = m7g["deployment"]["db"]
    assert "cpu_credits" not in db
    assert (db["cpu_core_factor"]["value"], db["cpu_core_factor"]["processor"]) == (1.55, "graviton3")
    assert load_model(m7g).db.sustained_vcpu is None


def test_change_db_plan_updates_supabase_pooler_and_drops_it_elsewhere(template):
    pooled, _ = apply_operations(template, [AddPooler(), ChangeDbPlan(plan="medium")])
    assert pooled["deployment"]["db"]["pooler"]["max_client_connections"]["value"] == 600
    rds, change = apply_operations(pooled, [ChangeDbPlan(plan="db.m7g.large", provider="rds_postgres")])
    assert "pooler" not in rds["deployment"]["db"] and "se quitó el pooler" in change[0]


@pytest.mark.parametrize(
    "op, message",
    [
        (ChangeDbPlan(plan="gigante"), "no tiene el plan 'gigante' en supabase. Hay: micro, small"),
        (ChangeDbPlan(plan="x", provider="oracle"), "No hay planes de DB para el proveedor 'oracle'"),
    ],
)
def test_change_db_plan_errors(template, op, message):
    with pytest.raises(OperationError, match=message):
        apply_operations(template, [op])


# --- add_pooler ---------------------------------------------------------------------------------


def test_add_pooler_twice_fails(template):
    with pytest.raises(OperationError, match="Operación 2 .* ya tiene un pooler") as e:
        apply_operations(template, [AddPooler(), AddPooler()])
    assert e.value.index == 1


def test_pgbouncer_needs_a_limit():
    realworld = load_sample(REALWORLD)
    with pytest.raises(OperationError, match="max_client_connections"):
        apply_operations(realworld, [AddPooler()])
    after, _ = apply_operations(realworld, [AddPooler(max_client_connections=1000, quote="PgBouncer con 1000")])
    pooler = after["deployment"]["db"]["pooler"]
    assert pooler["kind"] == "pgbouncer" and pooler["max_client_connections"]["value"] == 1000


# --- add_cache ----------------------------------------------------------------------------------


def test_add_cache_wraps_handler_queries_not_auth(template):
    """GET /items/ tiene 2 consultas del handler y 1 de la autenticación (deps.py): solo las 2 primeras."""
    after, _ = apply_operations(template, [AddCache(endpoint="GET /items/", hit_ratio=0.9)])
    ep = next(e for e in after["endpoints"] if e["id"] == "GET /items/")
    cache = next(s for s in ep["steps"] if s["resource"] == "cache")
    assert [s["at"] for s in cache["on_miss"]] == [
        "backend/app/api/routes/items.py:23",
        "backend/app/api/routes/items.py:27",
    ]
    assert [s["resource"] for s in ep["steps"]] == ["cache", "db_connection"]  # queda la de deps.py
    assert cache["hit_ratio"]["value"] == 0.9 and cache["time"]["label"] == "CALIBRADO"


def test_add_cache_reduces_db_use(template):
    """Con 90 % de aciertos en las dos listas (GET /items/ y GET /users/), la CPU de la DB baja."""
    ops = [AddCache(endpoint="GET /items/", hit_ratio=0.9), AddCache(endpoint="GET /users/", hit_ratio=0.9)]
    after, _ = apply_operations(template, ops)
    before_db = resource(run(template, "pico_normal"), "db_cpu").utilization
    r = run(after, "pico_normal")
    assert resource(r, "db_cpu").utilization < before_db * 0.5
    assert r.cache.hit_rate == pytest.approx(0.9, abs=0.05)


def test_add_cache_errors(template):
    with pytest.raises(OperationError, match="no tiene el endpoint 'GET /nada'"):
        apply_operations(template, [AddCache(endpoint="GET /nada", hit_ratio=0.5)])
    with pytest.raises(OperationError, match="no existen o no son consultas"):
        apply_operations(template, [AddCache(endpoint="GET /items/", hit_ratio=0.5, steps=[99])])
    with pytest.raises(OperationError, match="ya tiene una caché"):
        apply_operations(
            template,
            [AddCache(endpoint="GET /items/", hit_ratio=0.5), AddCache(endpoint="GET /items/", hit_ratio=0.5)],
        )


# --- move_to_queue ------------------------------------------------------------------------------


def synthetic():
    """Un signup que manda un email de 300 ms dentro de la request (el caso típico para una cola)."""
    return {
        "schema": "branchpoint.model/v1",
        "repo": {"path": "sintetico"},
        "deployment": {
            "api": {"replicas": 1, "vcpu": 1, "workers": 1, "threads_per_worker": 40, "latency_ms": 0},
            "db": {"vcpu": 2, "max_connections": 100, "pool_per_worker": {"pool_size": 10, "max_overflow": 0}},
        },
        "endpoints": [
            {
                "id": "POST /signup",
                "weight": 1,
                "async": True,
                "api_cpu_ms": {"value": 1.0, "unit": "ms", "label": "CALIBRADO", "source": "test"},
                "steps": [
                    {"kind": "db", "resource": "db_connection", "time": 1.1, "at": "users.py:10"},
                    {"kind": "external", "resource": "external", "time": 300, "at": "emails.py:5"},
                ],
            }
        ],
        "traffic": {"scenarios": {"base": {"rps": 20}}},
    }


def test_move_to_queue_takes_the_wait_out_of_the_request():
    raw = synthetic()
    before = simulate(load_model(raw), "base", duration_s=20, arrivals="uniform")
    after_raw, change = apply_operations(raw, [MoveToQueue(endpoint="POST /signup", step=1, workers=8, queue="emails")])
    after = simulate(load_model(after_raw), "base", duration_s=20, arrivals="uniform")
    assert before.latency.p50_ms > 300 and after.latency.p50_ms < 5
    (q,) = after.queues
    assert q.name == "emails" and q.processed > 0
    assert after_raw["deployment"]["queues"]["emails"]["job_steps"][0]["at"] == "emails.py:5"
    assert change == ["Cola 'emails': el paso 1 de POST /signup pasa a 8 worker(s)"]
    assert_new_numbers_have_provenance(raw, after_raw)


def test_move_cpu_step_takes_it_out_of_api_cpu(template):
    """Mover el hash a una cola saca sus 110 ms de la CPU de la API (api_cpu_ms baja en lo mismo)."""
    ep = next(e for e in template["endpoints"] if e["id"] == "POST /users/")
    i = next(i for i, s in enumerate(ep["steps"]) if s.get("shape") == "password_hash")
    after, _ = apply_operations(template, [MoveToQueue(endpoint="POST /users/", step=i, workers=2)])
    new_ep = next(e for e in after["endpoints"] if e["id"] == "POST /users/")
    assert new_ep["api_cpu_ms"]["value"] == pytest.approx(ep["api_cpu_ms"]["value"] - 110, abs=0.01)
    old_base = next(e for e in load_model(template).endpoints if e.id == "POST /users/").base_cpu_ms
    new_base = next(e for e in load_model(after).endpoints if e.id == "POST /users/").base_cpu_ms
    assert new_base == pytest.approx(old_base, abs=0.01)  # la CPU propia del framework no cambia


def test_move_to_queue_errors():
    raw = synthetic()
    with pytest.raises(OperationError, match="no existe el 5"):
        apply_operations(raw, [MoveToQueue(endpoint="POST /signup", step=5, workers=1)])
    with pytest.raises(OperationError, match="Ya existe la cola 'default'"):
        apply_operations(
            raw,
            [
                MoveToQueue(endpoint="POST /signup", step=1, workers=1),
                MoveToQueue(endpoint="POST /signup", step=0, workers=1),
            ],
        )


# --- parseo (lo que manda el agente) ------------------------------------------------------------


def test_parse_operation_validates_names_and_args():
    assert isinstance(parse_operation({"op": "scale_api", "replicas": 3}), ScaleApi)
    with pytest.raises(ValueError):
        parse_operation({"op": "borrar_todo"})
    with pytest.raises(ValueError):
        parse_operation({"op": "scale_api", "replicas": 0})
    with pytest.raises(ValueError):
        parse_operation({"op": "add_cache", "endpoint": "GET /x", "hit_ratio": 0.5, "precio": 3})
