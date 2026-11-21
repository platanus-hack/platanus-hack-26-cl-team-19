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


def test_cpu_credits_reaches_the_engine(client):
    """realworld usa db.t4g.medium: con burst se simula con sus 2 vCPU y no con los 0,4 sostenidos (JAJ-48)."""
    from app.samples import load_sample

    model = load_sample("fastapi-realworld-example-app")
    sustained = client.post("/runs", json={"model": model, "duration_s": 5}).json()
    burst = client.post("/runs", json={"model": model, "duration_s": 5, "cpu_credits": "burst"}).json()
    assert sustained["cpu"]["db_vcpu_effective"] == 0.4 and sustained["cpu"]["cpu_credits"] == "sustained"
    assert burst["cpu"]["db_vcpu_effective"] == 2 and burst["cpu"]["cpu_credits"] == "burst"


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
        ({"cpu_credits": "unlimited"}, "cpu_credits"),
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


# --- perfil de tráfico (JAJ-71) -----------------------------------------------------------------


def test_traffic_profile_pico(client, raw):
    r = client.post("/runs", json={"model": raw, "rps": 50, "duration_s": 40, "traffic_profile": "pico"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duration_s"] == 40 and len(body["series"]) == 40
    assert [round(s["to_rps"], 1) for s in body["traffic_profile"]] == [50, 50, 25]
    assert body["series"][0]["target_rps"] < body["series"][20]["target_rps"]


def test_traffic_profile_segments_set_the_duration(client, raw):
    profile = [
        {"duration_s": 10, "from_multiplier": 1, "to_multiplier": 1},
        {"duration_s": 5, "from_multiplier": 2, "to_multiplier": 0},
    ]
    body = client.post("/runs", json={"model": raw, "rps": 20, "traffic_profile": profile}).json()
    assert body["duration_s"] == 15
    assert body["series"][3]["target_rps"] == 20


def test_traffic_profile_errors(client, raw):
    zero = [{"duration_s": 10, "from_multiplier": 0, "to_multiplier": 0}]
    r = client.post("/runs", json={"model": raw, "traffic_profile": zero})
    assert r.status_code == 422 and "no llega nadie" in r.json()["error"]["message"]
    bad = [{"duration_s": 10, "from_multiplier": 1}]
    r = client.post("/runs", json={"model": raw, "traffic_profile": bad})
    assert r.json()["error"]["code"] == "invalid_parameters"
    # el tope de requests usa el multiplicador medio del perfil: 1.000 req/s × 600 s × 0,75 = 450.000
    big = [{"duration_s": 600, "from_multiplier": 1, "to_multiplier": 0.5}]
    r = client.post("/runs", json={"model": raw, "rps": 1000, "traffic_profile": big})
    assert r.json()["error"]["code"] == "run_too_large" and "450,000" in r.json()["error"]["message"]


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
