"""Runs guardados por cache_key (JAJ-75), contra las dos implementaciones de ProjectStore."""

import json

import pytest
from fastapi.testclient import TestClient

from app.api import run_cache
from app.api.main import create_app
from app.api.run_cache import ENGINE_VERSION, RUN_CACHE_HEADER, cache_key, run_from_json, run_to_json
from app.api.schemas import RunParams
from app.api.store import InMemoryProjectStore
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"
RUN = {"scenario": "cyberday", "seed": 1, "duration_s": 5}


@pytest.fixture(params=["memoria", "postgres"])
def store(request):
    if request.param == "memoria":
        return InMemoryProjectStore()
    return request.getfixturevalue("clean_pg_store")


@pytest.fixture
def client(store):
    return TestClient(create_app(cors_origins=["http://localhost:3000"], store=store))


@pytest.fixture
def pid(client):
    return client.post("/projects", json={"sample": SAMPLE}).json()["id"]


@pytest.fixture
def count_simulations(monkeypatch):
    calls = []
    real = run_cache.run_model

    def counting(model, params):
        calls.append(params)
        return real(model, params)

    monkeypatch.setattr(run_cache, "run_model", counting)
    return calls


def test_second_identical_run_is_not_simulated(client, pid, count_simulations):
    first = client.post(f"/projects/{pid}/versions/1/runs", json=RUN)
    second = client.post(f"/projects/{pid}/versions/1/runs", json=RUN)
    assert first.status_code == second.status_code == 200
    assert first.headers[RUN_CACHE_HEADER] == "miss" and second.headers[RUN_CACHE_HEADER] == "hit"
    assert second.json() == first.json()
    assert len(count_simulations) == 1


def test_other_params_or_version_simulate_again(client, pid, count_simulations):
    client.post(f"/projects/{pid}/versions/1/runs", json=RUN)
    r = client.post(f"/projects/{pid}/versions/1/runs", json={**RUN, "seed": 2})
    assert r.headers[RUN_CACHE_HEADER] == "miss"
    client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 2}]})
    r = client.post(f"/projects/{pid}/versions/2/runs", json=RUN)
    assert r.headers[RUN_CACHE_HEADER] == "miss"
    assert len(count_simulations) == 3


def test_compare_reuses_saved_runs(client, pid, count_simulations):
    client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 2}]})
    client.post(f"/projects/{pid}/versions/1/runs", json=RUN)
    r = client.post(f"/projects/{pid}/compare", json={"a": 1, "b": 2, **RUN})
    assert r.status_code == 200, r.text
    assert r.headers[RUN_CACHE_HEADER] == "hit,miss"
    again = client.post(f"/projects/{pid}/compare", json={"a": 1, "b": 2, **RUN})
    assert again.headers[RUN_CACHE_HEADER] == "hit,hit"
    assert again.json()["summary"] == r.json()["summary"]
    assert len(count_simulations) == 2


def test_failed_simulation_is_not_saved(client, pid):
    r = client.post(f"/projects/{pid}/versions/1/runs", json={**RUN, "scenario": "nope"})
    assert r.status_code == 422
    assert RUN_CACHE_HEADER not in r.headers


def test_cors_exposes_the_cache_header(client, pid):
    r = client.post(f"/projects/{pid}/versions/1/runs", json=RUN, headers={"Origin": "http://localhost:3000"})
    assert RUN_CACHE_HEADER.lower() in r.headers["access-control-expose-headers"].lower()


def test_run_round_trips_through_json(store, pid):
    r = TestClient(create_app(store=store)).post(f"/projects/{pid}/versions/1/runs", json=RUN).json()
    run = run_from_json(r)
    data = run_to_json(run)
    assert data == r
    json.dumps(data, allow_nan=False)  # Postgres (jsonb) no acepta NaN ni infinito
    assert "api->db" in data["measured_edges"]
    assert any(sample["edge_calls"].get("api->db", 0) for sample in data["series"])

    del data["measured_edges"]
    for sample in data["series"]:
        del sample["edge_calls"]
    legacy = run_from_json(data)
    assert legacy.measured_edges is None
    assert all(sample.edge_calls is None for sample in legacy.series)


def test_cache_key_depends_on_everything():
    base = cache_key("p", 1, RunParams(**RUN))
    assert base == cache_key("p", 1, RunParams(**RUN))
    assert len({base, cache_key("q", 1, RunParams(**RUN)), cache_key("p", 2, RunParams(**RUN))}) == 3
    assert base != cache_key("p", 1, RunParams(**{**RUN, "cpu_credits": "burst"}))
    assert base != cache_key("p", 1, RunParams(**{**RUN, "traffic_profile": "pico"}))
    assert len(ENGINE_VERSION) == 16


def test_saved_run_survives_a_restart(database_url, clean_pg_store):
    from app.db.postgres_store import PostgresProjectStore

    pid = TestClient(create_app(store=clean_pg_store)).post("/projects", json={"sample": SAMPLE}).json()["id"]
    first = TestClient(create_app(store=clean_pg_store)).post(f"/projects/{pid}/versions/1/runs", json=RUN)
    restarted = PostgresProjectStore.from_url(database_url)  # otro pool, como si la API reiniciara
    try:
        again = TestClient(create_app(store=restarted)).post(f"/projects/{pid}/versions/1/runs", json=RUN)
        assert again.headers[RUN_CACHE_HEADER] == "hit" and again.json() == first.json()
    finally:
        restarted.close()


def test_postgres_row_has_metrics_and_scenario(database_url, clean_pg_store):
    import psycopg

    client = TestClient(create_app(store=clean_pg_store))
    pid = client.post("/projects", json={"sample": SAMPLE}).json()["id"]
    run = client.post(f"/projects/{pid}/versions/1/runs", json=RUN).json()
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            "select r.scenario_name, s.name, r.seed, r.engine_version, r.error_rate, r.params->>'rps'"
            " from runs r left join scenarios s on s.id = r.scenario_id where r.project_id = %s",
            (pid,),
        ).fetchone()
    assert row[:4] == ("cyberday", "cyberday", 1, ENGINE_VERSION)
    assert float(row[4]) == pytest.approx(run["error_rate"])
    assert float(row[5]) == pytest.approx(run["rps"])


def test_find_run_only_returns_runs_of_that_project_and_version(store):
    """JAJ-97: la clave sola no basta. Un run guardado en otro proyecto o versión no se devuelve,
    aunque tenga la misma clave (en Postgres, alguien que pudiera escribir en ``runs`` la plantaría)."""
    model = load_sample(SAMPLE)
    a, b = store.create("a", model, None), store.create("b", model, None)
    store.add_version(b.id, model, "manual", 1, None)
    run = run_to_json(run_cache.run_model(model, RunParams(**RUN)))
    key = cache_key(a.id, 1, RunParams(**RUN))
    store.save_run(b.id, 1, key, {}, run, ENGINE_VERSION)
    assert store.find_run(a.id, 1, key) is None
    assert store.find_run(b.id, 2, key) is None
    assert store.find_run(b.id, 1, key) == run
