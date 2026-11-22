"""``POST /projects/{id}/versions/{n}/results``: simulación, costo y costo de fallar en una llamada (JAJ-128)."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.run_cache import RUN_CACHE_HEADER
from app.api.store import InMemoryProjectStore
from app.costs import describe_failure_missing, failure_missing
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"
RUN = {"scenario": "pico_normal", "seed": 1, "duration_s": 20}


@pytest.fixture
def client():
    return TestClient(create_app(store=InMemoryProjectStore(), auth=None))


def new_project(client, model=None) -> str:
    body = {"model": model} if model is not None else {"sample": SAMPLE}
    return client.post("/projects", json=body).json()["id"]


def test_results_bring_run_cost_and_failure(client):
    pid = new_project(client)
    r = client.post(f"/projects/{pid}/versions/1/results", json={**RUN, "region": "sa-east-1"})
    body = r.json()
    assert r.status_code == 200 and body["version"]["number"] == 1
    # el run es el mismo de …/runs, y sale del guardado (JAJ-75)
    assert r.headers[RUN_CACHE_HEADER] == "miss"
    again = client.post(f"/projects/{pid}/versions/1/runs", json=RUN)
    assert again.headers[RUN_CACHE_HEADER] == "hit" and again.json() == body["run"]
    # el costo es el de …/costs, en la región pedida, con desglose y procedencia
    assert body["cost"] == client.get(f"/projects/{pid}/versions/1/costs", params={"region": "sa-east-1"}).json()
    assert body["cost"]["region"] == "sa-east-1" and body["cost"]["lines"]
    assert body["cost"]["total"]["unit"].startswith("US$") and body["cost"]["total"]["source"]
    # el costo de fallar, que antes solo traía compare (el template trae los datos de negocio)
    assert body["failure"] is not None and body["failure_missing"] == []
    assert body["summary"].startswith("v1 cuesta US$") and body["failure"]["message"] in body["summary"]


def test_failure_matches_compare(client):
    """El mismo modelo, escenario y semilla dan el mismo costo de fallar que compare."""
    pid = new_project(client)
    client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 2}]})
    params = {"scenario": "cyberday", "seed": 1, "duration_s": 60}
    results = client.post(f"/projects/{pid}/versions/2/results", json=params).json()
    compare = client.post(f"/projects/{pid}/compare", json={**params, "a": 1, "b": 2}).json()
    assert results["failure"] == compare["failure_b"] and results["run"] == compare["run_b"]
    assert results["cost"] == compare["cost_b"]


def test_without_business_data_says_what_is_missing(client):
    model = copy.deepcopy(load_sample(SAMPLE))
    del model["business"]
    pid = new_project(client, model)
    body = client.post(f"/projects/{pid}/versions/1/results", json=RUN).json()
    assert body["failure"] is None
    assert body["failure_missing"] == ["business.conversion", "business.ticket_usd"]
    assert "al modelo le falta la tasa de conversión y el ticket promedio" in body["summary"]
    compare = client.post(f"/projects/{pid}/compare", json={**RUN, "a": 1, "b": 1}).json()
    assert compare["failure_missing_a"] == compare["failure_missing_b"] == body["failure_missing"]


def test_partial_total_is_said(client):
    """Con la API y la DB en local no tienen precio (JAJ-88): el total es parcial y el resumen lo dice."""
    model = copy.deepcopy(load_sample(SAMPLE))
    model["deployment"]["api"]["provider"] = "local"
    model["deployment"]["db"]["provider"] = "local"
    pid = new_project(client, model)
    body = client.post(f"/projects/{pid}/versions/1/results", json=RUN).json()
    assert set(body["cost"]["missing"]) == {"api", "db"}
    assert "sin contar la API ni la DB, que no tienen precio" in body["summary"]


def test_saturated_version_is_said(client):
    """Una versión que no alcanza a atender el tráfico (JAJ-89): su tasa de error es un piso."""
    pid = new_project(client)
    body = client.post(f"/projects/{pid}/versions/1/results", json={**RUN, "scenario": "cyberday"}).json()
    assert body["run"]["saturation"]["saturated"]
    assert "Ojo: v1 no alcanza a atender este tráfico" in body["summary"]


def test_errors_are_the_same_as_runs(client):
    pid = new_project(client)
    unknown = client.post(f"/projects/{pid}/versions/1/results", json={**RUN, "scenario": "nope"})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_scenario"
    assert client.post(f"/projects/{pid}/versions/9/results", json=RUN).status_code == 404
    bad_region = client.post(f"/projects/{pid}/versions/1/results", json={**RUN, "region": "mars-1"})
    assert bad_region.status_code == 422


def test_failure_missing_and_its_message():
    full = load_sample(SAMPLE)
    assert failure_missing(full) == []
    assert failure_missing({}) == ["traffic.requests_per_session", "business.conversion", "business.ticket_usd"]
    assert describe_failure_missing(["business.ticket_usd"]) == (
        "El costo de fallar no se calcula: al modelo le falta el ticket promedio (business.ticket_usd)."
    )
