"""Escenarios que cambian más que la tasa (JAJ-131): mezcla de endpoints, dependencias más lentas y
datos de negocio, por corrida o guardados en el escenario del proyecto, sin crear versiones."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.run_cache import RUN_CACHE_HEADER
from app.api.store import InMemoryProjectStore
from app.models.overrides import OverrideError, apply_overrides, slowdown_targets
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"
RUN = {"scenario": "pico_normal", "seed": 1, "duration_s": 30}
LOGIN = "POST /login/access-token"  # 110 ms de hash de contraseña: casi no pesa en la mezcla del modelo


@pytest.fixture(params=["memoria", "postgres"])
def store(request):
    if request.param == "memoria":
        return InMemoryProjectStore()
    return request.getfixturevalue("clean_pg_store")


@pytest.fixture
def client(store):
    return TestClient(create_app(store=store, auth=None))


@pytest.fixture
def pid(client):
    return client.post("/projects", json={"sample": SAMPLE}).json()["id"]


def resource(run: dict, name: str) -> dict:
    return next(r for r in run["resources"] if r["name"] == name)


def with_payments() -> dict:
    """Un modelo mínimo con dos endpoints: uno llama al servicio de pagos (100 ms) y otro no."""
    step_db = {"kind": "db", "resource": "db_connection", "time": {"value": 5}, "at": "a.py:1"}
    pay = {"kind": "http", "resource": "external", "service": "Pagos", "time": {"value": 100}, "at": "pay.py:9"}
    return {
        "schema": "branchpoint.model/v1",
        "repo": {"path": "tienda"},
        "deployment": {
            "api": {"replicas": 1, "vcpu": 2, "workers": 2, "threads_per_worker": 40, "latency_ms": 0},
            "db": {"vcpu": 2, "max_connections": 100, "pool_per_worker": {"pool_size": 20, "max_overflow": 0}},
        },
        "endpoints": [
            {"id": "POST /checkout", "weight": 1, "async": True, "api_cpu_ms": 1, "steps": [step_db, pay]},
            {"id": "GET /products", "weight": 1, "async": True, "api_cpu_ms": 1, "steps": [step_db]},
        ],
        "traffic": {"scenarios": {"s": {"rps": 10}}},
    }


def post_run(client, model, **over):
    return client.post("/runs", json={"model": model, "scenario": "s", "seed": 1, "duration_s": 30, **over})


def p50(run: dict, eid: str) -> float:
    return next(e for e in run["endpoints"] if e["id"] == eid)["latency"]["p50_ms"]


# --- mezcla de endpoints ---------------------------------------------------------------------------


def test_endpoint_mix_changes_the_bottleneck_without_a_new_version(client, pid):
    base = client.post(f"/projects/{pid}/versions/1/runs", json=RUN).json()
    heavy = client.post(f"/projects/{pid}/versions/1/runs", json={**RUN, "endpoint_weights": {LOGIN: 1}}).json()
    # el login pasa de ~1 % a ~50 % del tráfico: la CPU de la API sube y el hash la domina
    assert resource(heavy, "api_cpu")["utilization"] > 5 * resource(base, "api_cpu")["utilization"]
    assert resource(heavy, "api_cpu")["by_endpoint"][0]["endpoint"] == LOGIN
    assert heavy["overrides"] and "Mezcla de endpoints del escenario" in heavy["overrides"][0]
    assert base["overrides"] == []
    assert len(client.get(f"/projects/{pid}").json()["versions"]) == 1  # no creó versión


# --- dependencias más lentas -----------------------------------------------------------------------


def test_slow_payments_slow_down_only_the_endpoints_that_use_them(client):
    m = with_payments()
    base, slow = post_run(client, m).json(), post_run(client, m, slowdowns={"external:pagos": 10}).json()
    assert p50(slow, "POST /checkout") == pytest.approx(p50(base, "POST /checkout") + 900, rel=0.02)
    assert p50(slow, "GET /products") == pytest.approx(p50(base, "GET /products"), rel=0.02)
    assert "external:pagos ×10" in slow["overrides"][0]


def test_slow_db_scales_every_query(client):
    m = with_payments()
    base, slow = post_run(client, m).json(), post_run(client, m, slowdowns={"db": 2}).json()
    assert resource(slow, "db_cpu")["utilization"] == pytest.approx(
        2 * resource(base, "db_cpu")["utilization"], rel=0.05
    )


# --- negocio ---------------------------------------------------------------------------------------


def test_business_changes_the_failure_cost_and_says_where_it_comes_from(client, pid):
    long_run = {**RUN, "scenario": "cyberday", "duration_s": 120}
    base = client.post(f"/projects/{pid}/versions/1/results", json=long_run).json()
    # el template trae conversión 0,02 y ticket US$30: con 0,04 y US$60 las ventas en juego se cuadruplican
    biz = {"conversion": 0.04, "ticket_usd": 60}
    over = client.post(f"/projects/{pid}/versions/1/results", json={**long_run, "business": biz}).json()
    lo, lo_over = (r["failure"]["lost_sales_per_hour"]["low"]["value"] for r in (base, over))
    assert lo_over == pytest.approx(4 * lo, rel=0.01)
    assert "Declarado en el escenario" in over["failure"]["lost_sales_per_hour"]["low"]["source"]
    assert "Negocio del escenario" in over["summary"]
    assert over["cost"] == base["cost"]  # el costo de infraestructura no depende del negocio


def test_business_fills_what_the_model_is_missing(client):
    model = copy.deepcopy(load_sample(SAMPLE))
    del model["business"]
    pid = client.post("/projects", json={"model": model}).json()["id"]
    body = {**RUN, "business": {"conversion": 0.03, "ticket_usd": 40}}
    r = client.post(f"/projects/{pid}/versions/1/results", json=body).json()
    assert r["failure"] is not None and r["failure_missing"] == []


# --- guardados en el escenario del proyecto --------------------------------------------------------


def test_saved_scenario_applies_to_every_version_and_to_compare(client, pid):
    saved = client.put(
        f"/projects/{pid}/scenarios/black_friday",
        json={
            "multiplier": 5,
            "description": "Black Friday: todos compran",
            "endpoint_weights": {LOGIN: 1},
            "business": {"conversion": 0.05},
        },
    )
    assert saved.status_code == 200 and saved.json()["endpoint_weights"] == {LOGIN: 1.0}
    assert client.get(f"/projects/{pid}/scenarios/black_friday").json()["business"] == {
        "conversion": 0.05,
        "ticket_usd": None,
    }
    client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 2}]})
    params = {"scenario": "black_friday", "seed": 1, "duration_s": 30}
    for n in (1, 2):
        run = client.post(f"/projects/{pid}/versions/{n}/runs", json=params).json()
        assert run["overrides"] and resource(run, "api_cpu")["by_endpoint"][0]["endpoint"] == LOGIN
    cmp = client.post(f"/projects/{pid}/compare", json={**params, "a": 1, "b": 2}).json()
    assert cmp["run_a"]["overrides"] == cmp["run_b"]["overrides"] != []
    assert "Mezcla de endpoints del escenario" in cmp["summary"]


def test_request_overrides_win_over_the_saved_ones(client, pid):
    client.put(f"/projects/{pid}/scenarios/carga", json={"rps": 20, "endpoint_weights": {LOGIN: 1}})
    run = client.post(
        f"/projects/{pid}/versions/1/runs",
        json={"scenario": "carga", "seed": 1, "duration_s": 10, "endpoint_weights": {"GET /users/": 5}},
    ).json()
    assert "GET /users/" in run["overrides"][0] and LOGIN not in run["overrides"][0]


def test_overrides_enter_the_saved_run_key(client, pid):
    """Otro reemplazo simula de nuevo; el mismo vuelve del guardado (JAJ-75)."""
    url = f"/projects/{pid}/versions/1/runs"
    assert client.post(url, json=RUN).headers[RUN_CACHE_HEADER] == "miss"
    over = {**RUN, "endpoint_weights": {LOGIN: 1}}
    assert client.post(url, json=over).headers[RUN_CACHE_HEADER] == "miss"
    assert client.post(url, json=over).headers[RUN_CACHE_HEADER] == "hit"


# --- errores ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "over, says",
    [
        ({"endpoint_weights": {"GET /no-existe": 1}}, "no tiene el endpoint GET /no-existe"),
        ({"endpoint_weights": {"POST /checkout": 0, "GET /products": 0}}, "peso 0"),
        ({"slowdowns": {"external:correo": 3}}, "no tiene el nodo external:correo"),
    ],
)
def test_overrides_that_do_not_fit_the_model(client, over, says):
    r = post_run(client, with_payments(), **over)
    assert r.status_code == 422 and says in r.json()["error"]["message"]
    assert r.json()["error"]["code"] == "invalid_parameters"


def test_unknown_node_lists_the_ones_that_exist(client):
    r = post_run(client, with_payments(), slowdowns={"redis": 2}).json()["error"]
    assert r["available"] == ["db", "external:pagos"]


@pytest.mark.parametrize(
    "over",
    [{"slowdowns": {"db": 0}}, {"slowdowns": {"db": 500}}, {"endpoint_weights": {"GET /products": -1}}],
)
def test_out_of_range_values(client, over):
    assert post_run(client, with_payments(), **over).status_code == 422


# --- apply_overrides -------------------------------------------------------------------------------


def test_apply_overrides_does_not_touch_the_original():
    m = with_payments()
    before = copy.deepcopy(m)
    out, notes = apply_overrides(m, endpoint_weights={"GET /products": 3}, slowdowns={"db": 2})
    assert m == before and out != m and len(notes) == 2
    assert apply_overrides(m) == (m, [])  # sin reemplazos, el mismo modelo


def test_slowdown_targets_follow_the_graph_ids():
    m = with_payments()
    assert slowdown_targets(m) == ["db", "external:pagos"]
    m["deployment"]["services"] = [{"name": "Pagos", "role": "service", "origin": "ai"}]  # otro repo (IA-5)
    assert slowdown_targets(m) == ["db", "service:pagos"]
    with pytest.raises(OverrideError):
        apply_overrides(m, slowdowns={"external:pagos": 2})
