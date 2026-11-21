"""Tests de las operaciones que proponen versiones del modelo (JAJ-68).

Cada operación se prueba sobre el modelo de ejemplo del template de FastAPI: el resultado tiene que
cargar con ``load_model()``, simular y no dejar números sin etiqueta ni fuente.
"""

import json
from pathlib import Path

import pytest

from app.agent import OpError, apply_ops, ops_json_schema
from app.catalog import CATALOG_PATH, load_catalog
from app.engine import simulate
from app.models import load_model
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"
LABELS = {"OBSERVADO", "CALIBRADO", "ESTIMADO", "SUPUESTO"}
SPIKE_CATALOG = Path(__file__).parents[3] / "spikes" / "jaj-45-numeros" / "catalog.json"


@pytest.fixture
def model():
    return load_sample(SAMPLE)


def numbers(node, path=""):
    """Todos los números con procedencia del modelo: dicts con ``value``."""
    if isinstance(node, dict):
        if "value" in node and "unit" in node:
            yield path, node
        for k, v in node.items():
            yield from numbers(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from numbers(v, f"{path}[{i}]")


def assert_provenance(m):
    for path, n in numbers({k: v for k, v in m.items() if k != "assumptions"}):  # assumptions es un resumen
        assert n.get("label") in LABELS, f"{path} sin etiqueta: {n}"
        assert n.get("source"), f"{path} sin fuente: {n}"


def simulates(m, scenario="cyberday"):
    return simulate(load_model(m), scenario, seed=1, duration_s=10)


def endpoint(m, eid):
    return next(e for e in m["endpoints"] if e["id"] == eid)


# --- general --------------------------------------------------------------------------------------


def test_catalog_is_a_copy_of_the_spike():
    if not SPIKE_CATALOG.exists():
        pytest.skip("sin el spike de JAJ-45")
    assert json.loads(CATALOG_PATH.read_text()) == json.loads(SPIKE_CATALOG.read_text())


def test_does_not_modify_the_input(model):
    before = json.dumps(model, sort_keys=True)
    apply_ops(model, [{"op": "scale_api", "replicas": 3}])
    assert json.dumps(model, sort_keys=True) == before


def test_drops_stale_checks_and_recomputes_assumptions(model):
    r = apply_ops(model, [{"op": "scale_api", "replicas": 3}])
    assert "checks" not in r.model
    replicas = [a for a in r.model["assumptions"]["items"] if a["path"] == "deployment.api.replicas"]
    assert replicas and replicas[0]["value"] == 3 and replicas[0]["needs_review"]


def test_invalid_op_is_an_op_error(model):
    with pytest.raises(OpError, match="replicas"):
        apply_ops(model, [{"op": "scale_api", "replicas": 0}])
    with pytest.raises(OpError):
        apply_ops(model, [{"op": "delete_db"}])
    with pytest.raises(OpError, match="No hay operaciones"):
        apply_ops(model, [])


def test_error_says_which_op_failed(model):
    with pytest.raises(OpError, match=r"Operación 2 \(add_cache\)"):
        apply_ops(model, [{"op": "scale_api", "replicas": 2}, {"op": "add_cache", "endpoint": "GET /nope"}])


def test_json_schema_lists_every_op():
    schema = json.dumps(ops_json_schema())
    for name in ("scale_api", "change_db_plan", "add_pooler", "add_cache", "move_to_queue"):
        assert name in schema


# --- scale_api ------------------------------------------------------------------------------------


def test_scale_api_recomputes_cost(model):
    r = apply_ops(model, [{"op": "scale_api", "replicas": 3}])
    api = r.model["deployment"]["api"]
    assert api["replicas"]["value"] == 3
    assert api["replicas"]["label"] == "SUPUESTO" and api["replicas"]["needs_review"]
    assert api["usd_month"]["value"] == pytest.approx(3 * model["deployment"]["api"]["usd_month"]["value"], abs=0.02)
    assert_provenance(r.model)
    simulates(r.model)


def test_scale_api_with_quote_cites_the_user(model):
    r = apply_ops(model, [{"op": "scale_api", "replicas": 2, "vcpu": 2, "quote": "podemos pagar 2 máquinas de 2 vCPU"}])
    api = r.model["deployment"]["api"]
    assert "podemos pagar" in api["vcpu"]["source"] and not api["vcpu"].get("needs_review")


# --- el caso de la demo: más réplicas sin pooler superan las conexiones de Supabase Micro ----------


def test_scaling_without_pooler_exceeds_supabase_micro(model):
    r = apply_ops(model, [{"op": "scale_api", "replicas": 3}])
    run = simulates(r.model)
    assert any("180 conexiones" in w and "acepta 60" in w for w in run.warnings)


def test_pooler_fixes_the_connection_limit(model):
    r = apply_ops(model, [{"op": "scale_api", "replicas": 3}, {"op": "add_pooler"}])
    db = r.model["deployment"]["db"]
    assert db["pooler"]["client_connections"]["value"] == 200
    run = simulates(r.model)
    assert not any("conectarse" in w for w in run.warnings)
    assert run.errors["db_refused"] == 0
    assert_provenance(r.model)


def test_pooler_twice_is_an_error(model):
    with pytest.raises(OpError, match="ya tiene pooler"):
        apply_ops(model, [{"op": "add_pooler"}, {"op": "add_pooler"}])


def test_pooler_needs_a_plan_with_pooler(model):
    with pytest.raises(OpError, match="no tiene pooler"):
        apply_ops(
            model, [{"op": "change_db_plan", "provider": "rds_postgres", "plan": "db.m7g.large"}, {"op": "add_pooler"}]
        )


# --- change_db_plan -------------------------------------------------------------------------------


def test_change_db_plan_takes_numbers_from_catalog(model):
    r = apply_ops(model, [{"op": "change_db_plan", "plan": "large"}])
    db = r.model["deployment"]["db"]
    plan = load_catalog()["db_plans"]["supabase"]["large"]
    assert (db["plan"], db["vcpu"]["value"], db["max_connections"]["value"]) == ("large", 2, 160)
    assert db["usd_month"]["value"] == 25 + plan["compute_usd_month"] - 10
    assert db["pooler_connections"]["value"] == plan["pooler_connections"]
    assert_provenance(r.model)
    simulates(r.model)


def test_change_to_rds_drops_pooler_and_warns_about_credits(model):
    r = apply_ops(
        model,
        [{"op": "add_pooler"}, {"op": "change_db_plan", "provider": "rds_postgres", "plan": "db.t4g.medium"}],
    )
    db = r.model["deployment"]["db"]
    assert "pooler" not in db and "pooler_connections" not in db
    assert db["usd_month"]["value"] == pytest.approx(0.065 * 730, abs=0.01)
    assert db["cpu_credits"]["sustained_vcpu"]["value"] == pytest.approx(0.4)
    assert any("sin pooler" in w for w in r.warnings) and any("créditos" in w for w in r.warnings)
    simulates(r.model)


def test_unknown_plan_lists_the_available_ones(model):
    with pytest.raises(OpError, match="micro, small"):
        apply_ops(model, [{"op": "change_db_plan", "plan": "huge"}])


# --- add_cache ------------------------------------------------------------------------------------


def test_add_cache_moves_reads_to_on_miss(model):
    r = apply_ops(
        model, [{"op": "add_cache", "endpoint": "GET /items/", "hit_ratio": 0.8, "quote": "el 80 % se repite"}]
    )
    steps = endpoint(r.model, "GET /items/")["steps"]
    assert [s["kind"] for s in steps] == ["cache"]
    assert len(steps[0]["on_miss"]) == 3 and steps[0]["hit_ratio"]["value"] == 0.8
    run = simulates(r.model)
    assert run.cache.hits > 0
    assert_provenance(r.model)


def test_add_cache_only_some_reads(model):
    at = "backend/app/api/routes/items.py:23"  # el COUNT(*) de toda la tabla
    r = apply_ops(model, [{"op": "add_cache", "endpoint": "GET /items/", "at": [at]}])
    steps = endpoint(r.model, "GET /items/")["steps"]
    assert [s["kind"] for s in steps] == ["cache", "db", "db"]
    assert [s["at"] for s in steps[0]["on_miss"]] == [at]
    assert any("0 %" in w for w in r.warnings)  # sin tasa de aciertos: el peor caso


def test_add_cache_hit_ratio_needs_a_quote(model):
    with pytest.raises(OpError, match="quote"):
        apply_ops(model, [{"op": "add_cache", "endpoint": "GET /items/", "hit_ratio": 0.95}])


def test_add_cache_rejects_writes(model):
    with pytest.raises(OpError, match="no es GET"):
        apply_ops(model, [{"op": "add_cache", "endpoint": "POST /items/"}])


def test_add_cache_unknown_read(model):
    with pytest.raises(OpError, match="no tiene lecturas en x.py:1"):
        apply_ops(model, [{"op": "add_cache", "endpoint": "GET /items/", "at": ["x.py:1"]}])


# --- move_to_queue --------------------------------------------------------------------------------


def test_move_to_queue_takes_the_hash_out_of_the_request(model):
    eid, at = "POST /login/access-token", "backend/app/core/security.py:32"
    r = apply_ops(model, [{"op": "move_to_queue", "endpoint": eid, "at": at, "queue": "hashes", "workers": 2}])
    ep = endpoint(r.model, eid)
    assert [s["kind"] for s in ep["steps"]][-1] == "background"
    assert ep["api_cpu_ms"]["value"] == pytest.approx(endpoint(model, eid)["api_cpu_ms"]["value"] - 110)
    queue = r.model["deployment"]["queues"]["hashes"]
    assert queue["workers"]["value"] == 2 and queue["job_steps"][0]["at"] == at
    loaded = next(e for e in load_model(r.model).endpoints if e.id == eid)
    assert loaded.base_cpu_ms == pytest.approx(next(e for e in load_model(model).endpoints if e.id == eid).base_cpu_ms)
    run = simulates(r.model)
    assert next(q for q in run.queues if q.name == "hashes").enqueued > 0
    assert_provenance(r.model)


def test_move_to_queue_errors(model):
    eid = "POST /login/access-token"
    with pytest.raises(OpError, match="no tiene un paso en x.py:1"):
        apply_ops(model, [{"op": "move_to_queue", "endpoint": eid, "at": "x.py:1", "queue": "q", "workers": 1}])
    op = {"op": "move_to_queue", "endpoint": eid, "at": "backend/app/crud.py:58", "queue": "q", "workers": 1}
    with pytest.raises(OpError, match="Ya existe la cola"):
        apply_ops(model, [op, {**op, "at": "backend/app/crud.py:59"}])


# --- inversas (IA-8) ------------------------------------------------------------------------------


def total_cost(m):
    from app.costs import estimate_cost

    return estimate_cost(m).total["value"]


def strip(m):
    """El modelo sin lo que apply_ops recalcula siempre (supuestos y cotas)."""
    return {k: v for k, v in m.items() if k not in ("assumptions", "checks")}


@pytest.mark.parametrize(
    "op",
    [
        {"op": "add_cache", "endpoint": "GET /items/", "hit_ratio": 0.8, "quote": "el 80 % se repite"},
        {"op": "add_cache", "endpoint": "GET /items/", "at": ["backend/app/api/routes/items.py:23"]},
    ],
)
def test_add_cache_then_remove_cache_is_the_original(model, op):
    base = apply_ops(model, [{"op": "scale_api", "replicas": 1}]).model  # misma forma que tras apply_ops
    added = apply_ops(base, [op]).model
    removed = apply_ops(added, [{"op": "remove_cache", "endpoint": "GET /items/"}])
    assert endpoint(removed.model, "GET /items/")["steps"] == endpoint(base, "GET /items/")["steps"]
    assert total_cost(removed.model) == total_cost(base)
    assert strip(removed.model) == strip(base)
    simulates(removed.model)


def test_add_pooler_then_remove_pooler_is_the_original(model):
    base = apply_ops(model, [{"op": "change_db_plan", "provider": "supabase", "plan": "small"}]).model
    added = apply_ops(base, [{"op": "add_pooler"}]).model
    assert "pooler" in added["deployment"]["db"]
    removed = apply_ops(added, [{"op": "remove_pooler"}])
    assert removed.model["deployment"]["db"] == base["deployment"]["db"]
    assert total_cost(removed.model) == total_cost(base)
    assert "conexiones directo" in removed.changes[0]
    simulates(removed.model)


def test_move_to_queue_then_move_to_sync_is_the_original(model):
    eid, at = "POST /login/access-token", "backend/app/core/security.py:32"
    base = apply_ops(model, [{"op": "scale_api", "replicas": 1}]).model
    queued = apply_ops(base, [{"op": "move_to_queue", "endpoint": eid, "at": at, "queue": "hashes", "workers": 2}])
    back = apply_ops(queued.model, [{"op": "move_to_sync", "endpoint": eid, "step": at}])
    assert endpoint(back.model, eid) == endpoint(base, eid)  # pasos y api_cpu_ms
    assert "queues" not in back.model["deployment"] or "hashes" not in back.model["deployment"]["queues"]
    assert strip(back.model) == strip(base)
    assert total_cost(back.model) == total_cost(base)
    assert "se quitan" in back.changes[0]
    simulates(back.model)


def repo_cache_and_queue(model):
    """Una caché y una cola como las arma la ingesta (sin restore_*), para probar las inversas sobre el repo."""
    m = json.loads(json.dumps(model))
    ep = endpoint(m, "GET /items/")
    reads = ep["steps"][:]
    ep["steps"] = [
        {
            "kind": "cache",
            "resource": "cache",
            "detail": "redis.get(items)",
            "at": "backend/app/api/routes/items.py:20",
            "time": {"value": 0.5, "unit": "ms", "label": "ESTIMADO", "source": "catálogo"},
            "on_miss": reads,
        }
    ]
    login = endpoint(m, "POST /login/access-token")
    hash_step = next(s for s in login["steps"] if s.get("at") == "backend/app/core/security.py:32")
    m["deployment"]["queues"] = {
        "mails": {
            "workers": {"value": 1, "unit": "workers", "label": "SUPUESTO", "source": "repo", "needs_review": True},
            "job_steps": [hash_step],
        }
    }
    login["steps"] = [
        s
        if s is not hash_step
        else {
            "kind": "background",
            "resource": "background",
            "detail": "send_email.delay",
            "at": "backend/app/api/routes/login.py:40",
            "time": {"value": 1, "unit": "ms", "label": "ESTIMADO", "source": "catálogo"},
            "queue": "mails",
        }
        for s in login["steps"]
    ]
    return m, reads


def test_remove_cache_from_the_repo_puts_reads_where_the_cache_was(model):
    m, reads = repo_cache_and_queue(model)
    r = apply_ops(m, [{"op": "remove_cache", "endpoint": "GET /items/"}])
    assert endpoint(r.model, "GET /items/")["steps"] == reads
    simulates(r.model)


def test_move_to_sync_from_the_repo_brings_back_cpu(model):
    m, _ = repo_cache_and_queue(model)
    eid = "POST /login/access-token"
    before = endpoint(m, eid)["api_cpu_ms"]["value"]
    r = apply_ops(m, [{"op": "move_to_sync", "endpoint": eid, "step": "backend/app/api/routes/login.py:40"}])
    ep = endpoint(r.model, eid)
    assert any(s.get("at") == "backend/app/core/security.py:32" for s in ep["steps"])
    assert ep["api_cpu_ms"]["value"] == pytest.approx(before + 110)
    assert "queues" not in r.model["deployment"]
    simulates(r.model)


def test_remove_cache_errors(model):
    with pytest.raises(OpError, match="no tiene caché. Tienen caché: ninguno"):
        apply_ops(model, [{"op": "remove_cache", "endpoint": "GET /items/"}])
    m = json.loads(json.dumps(model))
    endpoint(m, "GET /items/")["steps"].insert(
        0, {"kind": "cache", "resource": "cache", "at": "x.py:1", "time": {"value": 1, "unit": "ms"}}
    )
    with pytest.raises(OpError, match="no guarda qué se hace cuando falla"):
        apply_ops(m, [{"op": "remove_cache", "endpoint": "GET /items/"}])


def test_remove_pooler_without_pooler(model):
    with pytest.raises(OpError, match="El proyecto no tiene pooler"):
        apply_ops(model, [{"op": "remove_pooler"}])


def test_move_to_sync_errors(model):
    eid = "POST /login/access-token"
    with pytest.raises(OpError, match="no encola nada en x.py:1"):
        apply_ops(model, [{"op": "move_to_sync", "endpoint": eid, "step": "x.py:1"}])
    m, _ = repo_cache_and_queue(model)
    m["deployment"]["queues"]["mails"]["job_steps"] = []
    with pytest.raises(OpError, match="no guarda los pasos de su trabajo"):
        apply_ops(m, [{"op": "move_to_sync", "endpoint": eid, "step": "backend/app/api/routes/login.py:40"}])


def test_scale_workers(model):
    m, _ = repo_cache_and_queue(model)
    r = apply_ops(m, [{"op": "scale_workers", "queue": "mails", "workers": 4, "quote": "queremos 4 workers"}])
    w = r.model["deployment"]["queues"]["mails"]["workers"]
    assert w["value"] == 4 and "queremos 4 workers" in w["source"] and not w.get("needs_review")
    r = apply_ops(m, [{"op": "scale_workers", "queue": "mails", "workers": 3}])
    w = r.model["deployment"]["queues"]["mails"]["workers"]
    assert w["label"] == "SUPUESTO" and w["source"].startswith("Propuesta del agente") and w["needs_review"]
    assert "1 → 3" in r.changes[0]
    simulates(r.model)
    assert_provenance(r.model)


def test_scale_workers_unknown_queue(model):
    with pytest.raises(OpError, match="No existe la cola 'x'. Hay: ninguna"):
        apply_ops(model, [{"op": "scale_workers", "queue": "x", "workers": 2}])


def test_ops_schema_has_the_inverse_ops():
    text = json.dumps(ops_json_schema())
    for name in ("remove_cache", "remove_pooler", "move_to_sync", "scale_workers"):
        assert f'"{name}"' in text
