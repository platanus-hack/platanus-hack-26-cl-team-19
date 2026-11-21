"""Tests de las rutas del editor (JAJ-52): modelos de ejemplo, grafo, proyectos, versiones y comparar."""

import copy

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.samples import load_sample, sample_ids

SAMPLE = "full-stack-fastapi-template"
RUN = {"scenario": "cyberday", "seed": 1, "duration_s": 10}


@pytest.fixture
def client():
    return TestClient(create_app(cors_origins=["http://localhost:3000"]))


@pytest.fixture
def project(client):
    r = client.post("/projects", json={"sample": SAMPLE})
    assert r.status_code == 201, r.text
    return r.json()


def scaled(model, replicas):
    m = copy.deepcopy(model)
    m["deployment"]["api"]["replicas"]["value"] = replicas
    return m


# --- modelos de ejemplo -------------------------------------------------------------------------


def test_list_models_has_both_samples(client):
    r = client.get("/models")
    assert r.status_code == 200
    by_id = {m["id"]: m for m in r.json()}
    assert set(by_id) == set(sample_ids()) >= {SAMPLE, "fastapi-realworld-example-app"}
    m = by_id[SAMPLE]
    assert m["name"] == SAMPLE
    assert m["endpoints"] == 23
    assert set(m["scenarios"]) == {"pico_normal", "cyberday"}


def test_get_model_returns_full_v1(client):
    r = client.get(f"/models/{SAMPLE}")
    assert r.status_code == 200
    assert r.json() == load_sample(SAMPLE)


def test_unknown_model_is_404_with_available(client):
    r = client.get("/models/nope")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found" and err["resource"] == "model"
    assert SAMPLE in err["available"]


# --- grafo --------------------------------------------------------------------------------------


def test_graph_of_sample(client):
    r = client.post("/graph", json={"model": load_sample(SAMPLE)})
    assert r.status_code == 200, r.text
    g = r.json()
    nodes = {n["id"]: n for n in g["nodes"]}
    assert set(nodes) == {"api", "db"}
    assert nodes["db"]["resources"] == ["db_cpu", "db_pool"]
    assert nodes["db"]["details"]["provider"] == "supabase"
    [edge] = g["edges"]
    assert (edge["source"], edge["target"]) == ("api", "db")
    assert len(edge["endpoints"]) == 22  # todos menos el que no toca la DB
    assert all(":" in ref for ref in edge["refs"])  # archivo:línea
    assert len(g["endpoints"]) == 23
    assert sum(e["weight"] for e in g["endpoints"]) == pytest.approx(1.0)


def test_graph_with_cache_queue_and_external(client):
    m = load_sample(SAMPLE)
    ep = m["endpoints"][0]
    db_step = ep["steps"][0]
    ep["steps"] = [
        {"kind": "cache", "resource": "cache", "time": {"value": 0.03}, "hit_ratio": {"value": 0.8},
         "at": "app/x.py:1", "on_miss": [db_step]},
        {"kind": "background", "resource": "background", "time": {"value": 0.03}, "at": "app/x.py:2"},
    ]
    m["deployment"]["queues"] = {"emails": {"workers": {"value": 2}, "job_steps": [
        {"kind": "external", "resource": "external", "time": {"value": 300}, "at": "app/jobs.py:9"}]}}
    g = client.post("/graph", json={"model": m}).json()
    kinds = {n["id"]: n["kind"] for n in g["nodes"]}
    assert kinds == {"api": "api", "db": "db", "cache": "cache", "queue:emails": "queue",
                     "worker:emails": "worker", "external": "external"}
    edges = {e["id"]: e for e in g["edges"]}
    assert {"api->cache", "api->db", "api->queue:emails", "queue:emails->worker:emails",
            "worker:emails->external"} <= set(edges)
    assert edges["worker:emails->external"]["endpoints"] == ["cola emails"]
    assert edges["api->cache"]["refs"] == ["app/x.py:1"]


def test_graph_invalid_model_is_422(client):
    r = client.post("/graph", json={"model": {"schema": "otro"}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_model"


# --- proyectos y versiones ----------------------------------------------------------------------


def test_create_project_from_sample_has_v1(client, project):
    assert project["name"] == SAMPLE and project["sample"] == SAMPLE
    [v1] = project["versions"]
    assert v1 == {**v1, "number": 1, "label": "v1", "origin": "repo", "parent": None}
    r = client.get(f"/projects/{project['id']}/versions/1")
    assert r.json()["model"] == load_sample(SAMPLE)


def test_create_project_from_own_model(client):
    r = client.post("/projects", json={"model": load_sample(SAMPLE), "name": "Mi tienda"})
    assert r.status_code == 201
    assert r.json()["name"] == "Mi tienda" and r.json()["sample"] is None


@pytest.mark.parametrize("body", [{}, {"sample": SAMPLE, "model": {}}])
def test_create_project_needs_exactly_one_source(client, body):
    r = client.post("/projects", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_parameters"


def test_create_project_unknown_sample_is_404(client):
    assert client.post("/projects", json={"sample": "nope"}).status_code == 404


def test_versions_chain_like_commits(client, project):
    pid = project["id"]
    m = load_sample(SAMPLE)
    r = client.post(f"/projects/{pid}/versions", json={"model": scaled(m, 2), "note": "API ×2"})
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert (v2["number"], v2["label"], v2["origin"], v2["parent"]) == (2, "v2", "manual", 1)
    r = client.post(f"/projects/{pid}/versions", json={"model": m, "origin": "agente", "parent": 1})
    assert (r.json()["number"], r.json()["parent"]) == (3, 1)
    history = client.get(f"/projects/{pid}").json()["versions"]
    assert [(v["label"], v["origin"], v["parent"]) for v in history] == [
        ("v1", "repo", None), ("v2", "manual", 1), ("v3", "agente", 1)]
    assert [p["id"] for p in client.get("/projects").json()] == [pid]


def test_saved_version_is_a_copy(client, project):
    m = load_sample(SAMPLE)
    client.post(f"/projects/{project['id']}/versions", json={"model": m})
    m["deployment"]["api"]["replicas"]["value"] = 99  # el cliente sigue editando su copia
    saved = client.get(f"/projects/{project['id']}/versions/2").json()["model"]
    assert saved["deployment"]["api"]["replicas"]["value"] != 99


def test_version_errors(client, project):
    pid = project["id"]
    assert client.get("/projects/nope").json()["error"]["resource"] == "project"
    r = client.get(f"/projects/{pid}/versions/5")
    assert r.status_code == 404 and r.json()["error"]["resource"] == "version"
    r = client.post(f"/projects/{pid}/versions", json={"model": load_sample(SAMPLE), "parent": 7})
    assert r.status_code == 404
    r = client.post(f"/projects/{pid}/versions", json={"model": {"schema": "otro"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_model"
    assert len(client.get(f"/projects/{pid}").json()["versions"]) == 1  # no guardó nada


# --- simular y comparar -------------------------------------------------------------------------


def test_run_version_same_as_post_runs(client, project):
    r = client.post(f"/projects/{project['id']}/versions/1/runs", json=RUN)
    assert r.status_code == 200, r.text
    direct = client.post("/runs", json={**RUN, "model": load_sample(SAMPLE)}).json()
    a, b = r.json(), direct
    a.pop("elapsed_ms"), b.pop("elapsed_ms")
    assert a == b


def test_run_version_unknown_scenario(client, project):
    r = client.post(f"/projects/{project['id']}/versions/1/runs", json={"scenario": "nope"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_scenario"


def test_compare_same_version_is_zero_delta(client, project):
    r = client.post(f"/projects/{project['id']}/compare", json={**RUN, "a": 1, "b": 1})
    assert r.status_code == 200, r.text
    d = r.json()["delta"]
    for k in ("p50_ms", "p95_ms", "p99_ms", "error_rate", "throughput_rps"):
        assert d[k]["diff"] == 0, k
    assert d["bottleneck_changed"] is False
    assert d["model_changes"] == []


def test_compare_scaled_api(client, project):
    pid = project["id"]
    client.post(f"/projects/{pid}/versions", json={"model": scaled(load_sample(SAMPLE), 4)})
    r = client.post(f"/projects/{pid}/compare", json={**RUN, "a": 1, "b": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["a"]["label"], body["b"]["label"]) == ("v1", "v2")
    assert body["run_a"]["seed"] == body["run_b"]["seed"] == 1
    d = body["delta"]
    assert d["model_changes"] == [{"path": "deployment.api.replicas", "a": 1, "b": 4}]
    assert d["p95_ms"]["diff"] < 0  # CyberDay satura la CPU de la API en v1: ×4 réplicas baja el p95


def test_compare_lists_added_endpoint(client, project):
    m = load_sample(SAMPLE)
    m["endpoints"].append({**copy.deepcopy(m["endpoints"][0]), "id": "GET /nuevo"})
    client.post(f"/projects/{project['id']}/versions", json={"model": m})
    d = client.post(f"/projects/{project['id']}/compare", json={**RUN, "a": 1, "b": 2}).json()["delta"]
    assert {"path": "endpoints[GET /nuevo]", "a": None, "b": "presente"} in d["model_changes"]


def test_openapi_lists_editor_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/models", "/models/{sample_id}", "/graph", "/projects", "/projects/{project_id}",
            "/projects/{project_id}/versions", "/projects/{project_id}/versions/{number}",
            "/projects/{project_id}/versions/{number}/runs", "/projects/{project_id}/compare"} <= set(paths)
