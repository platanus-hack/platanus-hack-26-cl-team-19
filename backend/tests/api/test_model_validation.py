"""El modelo se valida en un solo lugar, ``load_model`` (JAJ-101): ninguna entrada responde 500.

Antes, algunas formas raras (``deployment.db = []``, un escenario escalar, ``replicas = "2"``) daban
``Internal Server Error`` en texto plano, y algunos rangos imposibles (0 réplicas, tiempos negativos)
se aceptaban al crear el proyecto y fallaban después, en cada simulación. Ahora las tres rutas que
reciben un modelo responden 422 ``invalid_model`` con el campo en el mensaje, en los dos stores.
"""

from __future__ import annotations

import copy
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.routes import models as models_routes
from app.api.store import InMemoryProjectStore
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"


@pytest.fixture(params=["memoria", "postgres"])
def store(request):
    if request.param == "memoria":
        return InMemoryProjectStore()
    return request.getfixturevalue("clean_pg_store")


@pytest.fixture
def client(store):
    return TestClient(create_app(store=store, auth=None), raise_server_exceptions=False)


def changed(change: Callable[[dict], object]) -> dict:
    m = copy.deepcopy(load_sample(SAMPLE))
    change(m)
    return m


def api(m: dict) -> dict:
    return m["deployment"]["api"]


def db(m: dict) -> dict:
    return m["deployment"]["db"]


def ep(m: dict) -> dict:
    return m["endpoints"][0]


# (cambio al modelo del template, lo que debe decir el mensaje)
INVALID = {
    # BE-08: formas que respondían 500
    "db es una lista": (lambda m: m["deployment"].update(db=[]), "deployment.db debe ser un objeto"),
    "endpoint que no es objeto": (lambda m: m.update(endpoints=["x"]), "endpoints[0] debe ser un objeto"),
    "réplicas como texto": (lambda m: api(m).update(replicas="2"), "deployment.api.replicas debe ser un número"),
    "réplicas como texto con procedencia": (
        lambda m: api(m).update(replicas={"value": "2"}),
        "deployment.api.replicas debe ser un número",
    ),
    "escenario escalar": (
        lambda m: m["traffic"]["scenarios"].update(rapido=5),
        "traffic.scenarios.rapido debe ser un objeto",
    ),
    "steps que no es lista": (lambda m: ep(m).update(steps="x"), "endpoints[0].steps debe ser una lista"),
    "traffic es una lista": (lambda m: m.update(traffic=[]), "traffic debe ser un objeto"),
    "deployment null": (lambda m: m.update(deployment=None), "deployment debe ser un objeto"),
    "endpoint sin id de texto": (lambda m: ep(m).update(id=3), "endpoints[0].id debe ser un texto"),
    # BE-09: rangos que se aceptaban
    "0 réplicas": (lambda m: api(m).update(replicas={"value": 0}), "deployment.api.replicas debe ser al menos 1"),
    "0 workers": (lambda m: api(m).update(workers={"value": 0}), "deployment.api.workers debe ser al menos 1"),
    "0 vCPU en la API": (lambda m: api(m).update(vcpu={"value": 0}), "deployment.api.vcpu debe ser mayor que 0"),
    "0 vCPU en la DB": (lambda m: db(m).update(vcpu={"value": 0}), "deployment.db.vcpu debe ser mayor que 0"),
    "0 hilos": (
        lambda m: api(m).update(threads_per_worker={"value": 0}),
        "deployment.api.threads_per_worker debe ser al menos 1",
    ),
    "réplicas con decimales": (lambda m: api(m).update(replicas=1.5), "deployment.api.replicas debe ser un entero"),
    "latencia negativa": (
        lambda m: api(m).update(latency_ms={"value": -1000}),
        "deployment.api.latency_ms no puede ser negativo",
    ),
    "tiempo negativo": (
        lambda m: ep(m)["steps"][0].update(time={"value": -5}),
        "endpoints[0].steps[0].time no puede ser negativo",
    ),
    "peso negativo": (lambda m: ep(m).update(weight={"value": -0.5}), "endpoints[0].weight no puede ser negativo"),
    "0 conexiones": (
        lambda m: db(m).update(max_connections={"value": 0}),
        "deployment.db.max_connections debe ser al menos 1",
    ),
    "cola con largo 0": (
        lambda m: m["deployment"].update(queues={"q": {"workers": 5, "max_length": 0}}),
        "deployment.queues.q.max_length debe ser al menos 1",
    ),
    "req/s negativas": (
        lambda m: m["traffic"]["scenarios"]["pico_normal"].update(rps={"value": -1}),
        "traffic.scenarios.pico_normal.rps debe ser mayor que 0",
    ),
    "conversión sobre 1": (
        lambda m: m["business"].update(conversion={"value": 2}),
        "business.conversion es una fracción",
    ),
    # BE-14: Postgres rechazaba el sufijo con un 500 (check model_versions_schema)
    "schema con sufijo": (lambda m: m.update(schema="branchpoint.model/v1.1-loquesea"), "Esquema no soportado"),
}


@pytest.mark.parametrize("change, says", INVALID.values(), ids=INVALID.keys())
def test_invalid_models_are_422_on_every_route(client, change, says):
    m = changed(change)
    pid = client.post("/projects", json={"sample": SAMPLE}).json()["id"]
    responses = {
        "POST /projects": client.post("/projects", json={"model": m}),
        "POST /runs": client.post("/runs", json={"model": m, "scenario": "pico_normal", "duration_s": 5}),
        "POST /projects/{id}/versions": client.post(f"/projects/{pid}/versions", json={"model": m}),
    }
    for route, r in responses.items():
        assert r.status_code == 422, f"{route}: {r.status_code} {r.text[:200]}"
        assert r.json()["error"]["code"] == "invalid_model", route
        assert says in r.json()["error"]["message"], f"{route}: {r.json()['error']['message']}"
    assert len(client.get(f"/projects/{pid}").json()["versions"]) == 1  # no guardó la versión


SCALARS = {
    "req/s escalar": lambda m: m["traffic"]["scenarios"]["pico_normal"].update(rps=8),
    "multiplicador escalar": lambda m: m["traffic"]["scenarios"]["cyberday"].update(multiplier=20),
    "pico escalar": lambda m: m["traffic"].update(peak_rps=8),
    "réplicas escalares": lambda m: api(m).update(replicas=2),
}


@pytest.mark.parametrize("change", SCALARS.values(), ids=SCALARS.keys())
def test_scalar_numbers_work_everywhere(client, change):
    """Un número sin procedencia vale en todo el modelo, no solo en el motor: antes, un ``rps`` escalar
    pasaba ``load_model`` pero el proyecto respondía 500 al leer sus escenarios."""
    m = changed(change)
    r = client.post("/projects", json={"model": m})
    assert r.status_code == 201, r.text[:300]
    pid = r.json()["id"]
    run = client.post(f"/projects/{pid}/versions/1/runs", json={"scenario": "cyberday", "seed": 1, "duration_s": 5})
    assert run.status_code == 200, run.text[:300]
    assert client.post("/costs", json={"model": m}).status_code == 200


def test_add_cache_on_an_endpoint_without_steps(client):
    """``steps`` es opcional; antes, ``add_cache`` en un endpoint sin pasos respondía 500."""
    m = copy.deepcopy(load_sample(SAMPLE))
    eid = next(e["id"] for e in m["endpoints"] if e["id"].startswith("GET"))
    next(e for e in m["endpoints"] if e["id"] == eid).pop("steps")
    pid = client.post("/projects", json={"model": m}).json()["id"]
    r = client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "add_cache", "endpoint": eid}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_operations"
    assert f"'{eid}' no tiene lecturas de la DB que cachear" in r.json()["error"]["message"]


def test_unexpected_errors_are_500_with_the_error_format(client, monkeypatch, caplog):
    """Lo que nadie atrapa responde 500 con ``internal_error``, sin el detalle, y el traceback va al log."""

    def boom():
        raise RuntimeError("detalle interno")

    monkeypatch.setattr(models_routes, "sample_ids", boom)
    r = client.get("/models")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "detalle interno" not in r.text
    assert "detalle interno" in caplog.text and "GET /models" in caplog.text
