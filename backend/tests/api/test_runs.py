"""Tests de la API (JAJ-49) con el modelo del full-stack-fastapi-template."""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.engine import simulate
from app.models import load_model

FIXTURE = Path(__file__).parents[1] / "fixtures" / "full-stack-fastapi-template.model.json"


@pytest.fixture(scope="module")
def raw():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(cors_origins=["http://localhost:3000"]))


def without_timing(d):
    d = dict(d)
    d.pop("elapsed_ms")
    return d


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "run_schema": "branchpoint.run/v1"}


def test_run_cyberday_same_as_engine(client, raw):
    """La API devuelve exactamente el Run del motor (salvo el tiempo que tardó)."""
    r = client.post("/runs", json={"model": raw, "scenario": "cyberday", "seed": 3, "duration_s": 20})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"] == "branchpoint.run/v1"
    assert body["bottleneck"]["resource"] == "api_cpu"
    assert len(body["series"]) == 20
    direct = simulate(load_model(raw), "cyberday", seed=3, duration_s=20).to_dict()
    assert without_timing(body) == without_timing(json.loads(json.dumps(direct)))


def test_defaults(client, raw):
    """Sin parámetros: CyberDay, 60 s, semilla 0."""
    body = client.post("/runs", json={"model": raw}).json()
    assert body["scenario"] == "cyberday" and body["duration_s"] == 60 and body["seed"] == 0


def test_rps_override_and_options(client, raw):
    r = client.post(
        "/runs",
        json={
            "model": raw,
            "rps": 5,
            "duration_s": 10,
            "arrivals": "uniform",
            "client_timeout_s": None,
            "cache_hit_ratio": 0.5,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rps"] == 5 and body["arrivals"] == "uniform"
    assert body["bottleneck"]["resource"] is None


def test_unknown_scenario(client, raw):
    r = client.post("/runs", json={"model": raw, "scenario": "black_friday"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "unknown_scenario"
    assert "black_friday" in err["message"]
    assert err["available"] == ["cyberday", "pico_normal"]


def test_unknown_scenario_is_fine_with_rps(client, raw):
    """Con rps, el escenario es solo un nombre para el Run."""
    r = client.post("/runs", json={"model": raw, "scenario": "prueba", "rps": 10, "duration_s": 5})
    assert r.status_code == 200
    assert r.json()["scenario"] == "prueba (10 req/s)"


def test_wrong_schema(client, raw):
    bad = copy.deepcopy(raw)
    bad["schema"] = "otra.cosa/v9"
    err = client.post("/runs", json={"model": bad}).json()["error"]
    assert err["code"] == "invalid_model"
    assert "branchpoint.model/v1" in err["message"]


def test_missing_field(client, raw):
    bad = copy.deepcopy(raw)
    del bad["deployment"]
    r = client.post("/runs", json={"model": bad})
    assert r.status_code == 422
    assert r.json()["error"] == {"code": "invalid_model", "message": "Al modelo le falta el campo 'deployment'."}


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"duration_s": 0}, "duration_s"),
        ({"rps": -1}, "rps"),
        ({"cache_hit_ratio": 1.5}, "cache_hit_ratio"),
        ({"arrivals": "burst"}, "arrivals"),
        ({"otro": 1}, "otro"),
    ],
)
def test_invalid_parameters(client, raw, payload, field):
    r = client.post("/runs", json={"model": raw, **payload})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_parameters"
    assert field in [f["field"] for f in err["fields"]]


def test_missing_model(client):
    err = client.post("/runs", json={"scenario": "cyberday"}).json()["error"]
    assert err["code"] == "invalid_parameters" and err["fields"][0]["field"] == "model"


def test_run_too_large(client, raw):
    r = client.post("/runs", json={"model": raw, "rps": 10_000, "duration_s": 3600})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "run_too_large"


def test_cors_allows_nuxt_dev(client):
    r = client.options(
        "/runs",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_other_origins(client):
    r = client.options("/runs", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers
