"""``GET /catalog/deployment`` y elegir el plan desde el editor (JAJ-148)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.store import InMemoryProjectStore

LABELS = {"OBSERVADO", "CALIBRADO", "ESTIMADO", "SUPUESTO"}
RUN = {"scenario": "custom", "rps": 40, "seed": 1, "duration_s": 20}


@pytest.fixture
def client():
    return TestClient(create_app(store=InMemoryProjectStore(), auth=None, github_app=None))


def test_options_cover_each_component_with_provenance(client):
    body = client.get("/catalog/deployment").json()
    providers = {kind: {p["id"]: p for p in options} for kind, options in body.items()}
    assert {"supabase", "neon", "rds_postgres", "local"} <= providers["db"].keys()
    assert {"fargate", "fly", "render", "local"} <= providers["api"].keys()
    assert {"vercel", "cloudfront", "local"} <= providers["frontend"].keys()
    neon = {p["id"]: p["specs"] for p in providers["db"]["neon"]["plans"]}
    assert neon["4cu"]["max_connections"]["value"] == 1802
    for kind in body.values():
        for provider in kind:
            for plan in provider["plans"]:
                for name, spec in plan["specs"].items():
                    if spec is not None:
                        assert spec["label"] in LABELS and spec["source"], (provider["id"], plan["id"], name)
    assert providers["api"]["fargate"]["sized_by_vcpu"] and not providers["api"]["fargate"]["plans"]
    # el editor calcula el costo de Fargate con los vCPU elegidos: necesita los precios unitarios
    example = providers["api"]["fargate"]["example"]
    assert example["usd_vcpu_hour"]["value"] > 0 and example["usd_gb_hour"]["value"] > 0


def test_choosing_a_plan_in_the_editor_creates_a_manual_version_that_simulates_with_it(client):
    pid = client.post("/projects", json={"sample": "full-stack-fastapi-template"}).json()["id"]
    ops = [{"op": "change_db_plan", "provider": "neon", "plan": "0.25cu"}, {"op": "add_pooler"}]
    small = client.post(f"/projects/{pid}/versions/1/ops", json={"ops": ops, "origin": "manual"})
    assert small.status_code == 201 and small.json()["origin"] == "manual"
    big = client.post(
        f"/projects/{pid}/versions/2/ops",
        json={"ops": [{"op": "change_db_plan", "plan": "4cu"}], "origin": "manual"},
    ).json()
    assert big["model"]["deployment"]["db"]["vcpu"]["value"] == 4
    runs = {
        n: client.post(f"/projects/{pid}/versions/{n}/runs", json=RUN).json()
        for n in (small.json()["number"], big["number"])
    }
    small_run, big_run = runs.values()
    db_cpu = {n: next(r for r in run["resources"] if r["name"] == "db_cpu")["utilization"] for n, run in runs.items()}
    assert db_cpu[big["number"]] < db_cpu[small.json()["number"]] / 5
    assert big_run["latency"]["p95_ms"] < small_run["latency"]["p95_ms"]


def test_ops_from_the_agent_stay_agent_by_default(client):
    pid = client.post("/projects", json={"sample": "full-stack-fastapi-template"}).json()["id"]
    r = client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 2}]})
    assert r.json()["origin"] == "agente"
