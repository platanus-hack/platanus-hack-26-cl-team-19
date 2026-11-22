"""Reportes de simulación (JAJ-127): cada corrida guarda su reporte y dos reportes se comparan sin simular."""

import pytest
from fastapi.testclient import TestClient

from app.agent.tools import AgentTools
from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.reports import REPORT_SCHEMA

RUN = {"scenario": "pico_normal", "duration_s": 5}


@pytest.fixture(params=["memoria", "postgres"])
def store(request):
    if request.param == "memoria":
        return InMemoryProjectStore()
    return request.getfixturevalue("clean_pg_store")


@pytest.fixture
def client(store):
    return TestClient(create_app(store=store, auth=None, github_app=None))


@pytest.fixture
def project(client):
    r = client.post("/projects", json={"sample": "full-stack-fastapi-template", "name": "tienda"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def report(client, project, version=1, **params):
    r = client.post(f"/projects/{project}/versions/{version}/reports", json={**RUN, **params})
    assert r.status_code == 201, r.text
    return r.json()


def test_each_run_is_a_new_simulation_with_its_own_report(client, project):
    a, b = report(client, project), report(client, project)
    assert a["schema"] == REPORT_SCHEMA and a["kind"] == "run" and a["id"] != b["id"]
    assert a["scenario"]["seed"] != b["scenario"]["seed"]  # semilla nueva en cada corrida
    assert a["project"]["name"] == "tienda" and a["version"]["number"] == 1
    assert a["results"]["latency"]["p95_ms"] > 0 and a["results"]["provenance"]["label"] == "ESTIMADO"
    assert a["costs"]["total"]["value"] > 0 and a["assumptions"]["total"] > 0
    assert a["conclusion"].startswith("En pico_normal")
    listed = client.get(f"/projects/{project}/reports").json()
    assert [r["id"] for r in listed] == [b["id"], a["id"]]  # el más nuevo primero


def test_saved_report_never_needs_a_new_simulation(client, project):
    a = report(client, project, seed=7)
    assert client.get(f"/projects/{project}/reports/{a['id']}").json() == a
    md = client.get(f"/projects/{project}/reports/{a['id']}/markdown")
    assert md.headers["content-type"].startswith("text/markdown")
    assert "# Reporte de simulación · tienda v1" in md.text and "semilla 7" in md.text


def test_components_have_diagnosis_and_margin(client, project):
    calm = report(client, project)
    comps = {c["id"]: c for c in calm["components"]}
    assert set(comps) >= {"api", "db"}
    for c in comps.values():
        assert c["status"] in ("ok", "idle", "overloaded") and c["why"]
        assert c["saturates_at_rps"]["label"] == "ESTIMADO" and c["headroom_x"] > 1
    assert calm["thresholds"]["overloaded"]["label"] == "SUPUESTO"
    flood = report(client, project, rps=400)
    assert flood["scenario"]["custom"] and flood["scenario"]["label"] == "personalizado (400 req/s)"
    assert any(c["status"] == "overloaded" for c in flood["components"])
    assert flood["bottleneck"]["resource"] and flood["bottleneck"]["label"]


def test_compare_two_saved_reports_without_simulating(client, project):
    model = client.get(f"/projects/{project}/versions/1").json()["model"]
    model["deployment"]["api"]["replicas"]["value"] = 4
    r = client.post(f"/projects/{project}/versions", json={"model": model, "parent": 1, "origin": "manual"})
    assert r.status_code == 201, r.text
    a, b = report(client, project, version=1, rps=200), report(client, project, version=2, rps=200)
    c = client.post(f"/projects/{project}/reports/compare", json={"a": a["id"], "b": b["id"]})
    assert c.status_code == 201, c.text
    cmp = c.json()
    assert cmp["kind"] == "comparison" and cmp["same_scenario"] and not cmp["warnings"]
    assert any(ch["path"] == "deployment.api.replicas" for ch in cmp["changes"])
    assert cmp["delta"]["usd_month"]["diff"] > 0  # 4 réplicas cuestan más
    assert cmp["delta"]["p95_ms"]["b"] < cmp["delta"]["p95_ms"]["a"]
    other = report(client, project, version=1, rps=20)
    mixed = client.post(f"/projects/{project}/reports/compare", json={"a": a["id"], "b": other["id"]}).json()
    assert not mixed["same_scenario"] and "escenarios son distintos" in mixed["warnings"][0]
    assert "Qué cambió" not in client.get(f"/projects/{project}/reports/{mixed['id']}/markdown").text
    assert "Qué cambió en el modelo" in client.get(f"/projects/{project}/reports/{cmp['id']}/markdown").text


def test_compare_rejects_bad_pairs(client, project):
    a = report(client, project)
    assert client.post(f"/projects/{project}/reports/compare", json={"a": a["id"], "b": a["id"]}).status_code == 422
    nope = client.post(
        f"/projects/{project}/reports/compare", json={"a": a["id"], "b": "00000000-0000-0000-0000-000000000000"}
    )
    assert nope.status_code == 404


def test_delete_and_isolation_between_projects(client, project):
    a = report(client, project)
    other = client.post("/projects", json={"sample": "full-stack-fastapi-template"}).json()["id"]
    assert client.get(f"/projects/{other}/reports/{a['id']}").status_code == 404  # no se ve desde otro proyecto
    assert client.delete(f"/projects/{other}/reports/{a['id']}").status_code == 404
    assert client.delete(f"/projects/{project}/reports/{a['id']}").status_code == 204
    assert client.get(f"/projects/{project}/reports").json() == []


def test_chat_simulate_also_saves_a_report(store):
    project = store.create("tienda", __import__("app.samples", fromlist=["load_sample"]).load_sample(
        "full-stack-fastapi-template"
    ), None)  # fmt: skip
    out = AgentTools(store, None).call("simulate", {"project_id": project.id, "scenario": "pico_normal"})
    assert "error" not in out, out
    saved = store.get_report(project.id, out["report_id"])
    assert saved["kind"] == "run" and saved["scenario"]["name"] == "pico_normal"


def test_same_run_does_not_repeat_the_report(store):
    """JAJ-165: el agente simulando la misma versión, escenario y semilla reutiliza el reporte."""
    project = store.create("tienda", __import__("app.samples", fromlist=["load_sample"]).load_sample(
        "full-stack-fastapi-template"
    ), None)  # fmt: skip
    tools = AgentTools(store, None)
    first = tools.call("simulate", {"project_id": project.id, "scenario": "pico_normal"})
    again = tools.call("simulate", {"project_id": project.id, "scenario": "pico_normal"})
    other = tools.call("simulate", {"project_id": project.id, "scenario": "pico_normal", "seed": 3})
    assert first["report_id"] == again["report_id"] != other["report_id"]
    assert len(store.list_reports(project.id)) == 2


def test_report_keeps_the_scenario_adjustments(client, project):
    weights = {"POST /login/access-token": 5}
    r = report(client, project, endpoint_weights=weights, slowdowns={"db": 2})
    assert r["scenario"]["adjustments"]  # las frases de los ajustes (JAJ-131)
    assert r["params"]["slowdowns"] == {"db": 2}
    plain = report(client, project)
    cmp = client.post(f"/projects/{project}/reports/compare", json={"a": plain["id"], "b": r["id"]}).json()
    assert not cmp["same_scenario"]  # mismos req/s pero otros ajustes: no son comparables 1:1
    md = client.get(f"/projects/{project}/reports/{r['id']}/markdown").text
    assert "Ajustes del escenario" in md
