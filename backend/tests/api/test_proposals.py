"""Tests de POST /projects/{id}/proposals y GET /operations (JAJ-68)."""

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app(cors_origins=["http://localhost:3000"]))


@pytest.fixture
def project(client):
    r = client.post("/projects", json={"sample": "full-stack-fastapi-template"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_list_operations(client):
    ops = client.get("/operations").json()
    assert [o["op"] for o in ops] == ["scale_api", "change_db_plan", "add_pooler", "add_cache", "move_to_queue"]
    scale = ops[0]
    assert "replicas" in scale["arguments"]["properties"] and scale["description"]


def test_proposal_creates_agent_version_and_compares(client, project):
    r = client.post(
        f"/projects/{project}/proposals",
        json={"ops": [{"op": "scale_api", "replicas": 3}, {"op": "add_pooler"}], "note": "Escalar la API con pooler"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    v = body["version"]
    assert (v["number"], v["origin"], v["parent"], v["note"]) == (2, "agente", 1, "Escalar la API con pooler")
    assert body["changes"][0] == "API: 1 → 3 réplicas"
    assert v["model"]["deployment"]["db"]["pooler"]["kind"] == "supavisor"

    cmp = client.post(f"/projects/{project}/compare", json={"a": 1, "b": 2, "duration_s": 10}).json()
    paths = [c["path"] for c in cmp["delta"]["model_changes"]]
    assert "deployment.api.replicas" in paths


def test_proposal_without_note_uses_the_changes(client, project):
    v = client.post(f"/projects/{project}/proposals", json={"ops": [{"op": "scale_api", "replicas": 2}]}).json()
    assert v["version"]["note"] == "API: 1 → 2 réplicas"


def test_invalid_operation_is_422_with_index(client, project):
    r = client.post(
        f"/projects/{project}/proposals",
        json={"ops": [{"op": "add_pooler"}, {"op": "change_db_plan", "plan": "gigante"}]},
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_operation" and err["index"] == 1
    assert "gigante" in err["message"]
    # no se guardó nada
    assert len(client.get(f"/projects/{project}").json()["versions"]) == 1


@pytest.mark.parametrize(
    "ops",
    [
        [],
        [{"op": "borrar_todo"}],
        [{"op": "scale_api", "replicas": 0}],
        [{"op": "scale_api", "replicas": 2, "precio": 3}],
    ],
)
def test_malformed_operations_are_invalid_parameters(client, project, ops):
    r = client.post(f"/projects/{project}/proposals", json={"ops": ops})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_parameters"


def test_proposal_on_missing_project_or_version(client, project):
    assert client.post("/projects/nope/proposals", json={"ops": [{"op": "add_pooler"}]}).status_code == 404
    r = client.post(f"/projects/{project}/proposals", json={"ops": [{"op": "add_pooler"}], "parent": 7})
    assert r.status_code == 404 and r.json()["error"]["resource"] == "version"
