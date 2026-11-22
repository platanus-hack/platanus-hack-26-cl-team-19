"""Tests de las rutas de costos (JAJ-72): POST /costs, el costo de una versión y el costo en compare."""

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.samples import load_sample


@pytest.fixture
def client():
    return TestClient(create_app(cors_origins=["http://localhost:3000"], store=InMemoryProjectStore()))


def test_post_costs(client):
    r = client.post("/costs", json={"model": load_sample("full-stack-fastapi-template")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"] == "branchpoint.cost/v1" and body["region"] == "us-east-1"
    assert [line["id"] for line in body["lines"]] == ["api", "db", "alb", "transfer"]
    assert body["total"]["unit"] == "US$/mes" and body["total"]["label"] == "SUPUESTO"


def test_post_costs_validates(client):
    assert client.post("/costs", json={"model": {"schema": "otra/v9"}}).json()["error"]["code"] == "invalid_model"
    r = client.post("/costs", json={"model": load_sample("full-stack-fastapi-template"), "region": "eu-west-1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_parameters"


def test_version_costs_and_compare(client):
    pid = client.post("/projects", json={"sample": "full-stack-fastapi-template"}).json()["id"]
    v1 = client.get(f"/projects/{pid}/versions/1/costs").json()
    assert v1["total"]["value"] > 0
    sa = client.get(f"/projects/{pid}/versions/1/costs", params={"region": "sa-east-1"}).json()
    assert sa["region"] == "sa-east-1" and sa["total"]["value"] > v1["total"]["value"]

    ops = [{"op": "scale_api", "replicas": 3}]
    assert client.post(f"/projects/{pid}/versions/1/ops", json={"ops": ops}).status_code == 201
    cmp = client.post(f"/projects/{pid}/compare", json={"a": 1, "b": 2, "duration_s": 5}).json()
    d = cmp["cost_delta"]
    assert d["by_line"]["api"] == pytest.approx(2 * (0.03238 + 2 * 0.00356) * 730, abs=0.03)
    assert d["b"] - d["a"] == pytest.approx(d["diff"], abs=0.01)
    assert cmp["cost_a"]["total"]["value"] == pytest.approx(v1["total"]["value"])


def test_compare_shows_sales_at_stake(client):
    """JAJ-74: en CyberDay (120 s), la v2 (API ×3 + pooler) cuesta más por mes y evita ventas perdidas."""
    pid = client.post("/projects", json={"sample": "full-stack-fastapi-template"}).json()["id"]
    ops = [{"op": "scale_api", "replicas": 3}, {"op": "add_pooler"}]
    client.post(f"/projects/{pid}/versions/1/ops", json={"ops": ops})
    cmp = client.post(
        f"/projects/{pid}/compare", json={"a": 1, "b": 2, "scenario": "cyberday", "duration_s": 120, "seed": 1}
    ).json()
    fa, fb = cmp["failure_a"], cmp["failure_b"]
    assert fa["lost_sales_per_hour"]["low"]["value"] > fb["lost_sales_per_hour"]["low"]["value"]
    assert cmp["summary"].startswith("v2 cuesta +US$57")
    assert "evita entre US$" in cmp["summary"] and "(al menos)" in cmp["summary"]


def test_compare_too_short_says_so(client):
    pid = client.post("/projects", json={"sample": "full-stack-fastapi-template"}).json()["id"]
    client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 3}]})
    cmp = client.post(
        f"/projects/{pid}/compare", json={"a": 1, "b": 2, "scenario": "cyberday", "duration_s": 20}
    ).json()
    assert "muy corta" in cmp["summary"]


def test_version_costs_404(client):
    assert client.get("/projects/nope/versions/1/costs").status_code == 404
