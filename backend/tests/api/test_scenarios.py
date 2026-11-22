"""Escenarios del proyecto (JAJ-76), contra las dos implementaciones de ProjectStore."""

import copy

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.run_cache import RUN_CACHE_HEADER
from app.api.store import InMemoryProjectStore, ProjectScenario
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"
RUN = {"seed": 1, "duration_s": 5}
PEAK = 13.12  # traffic.peak_rps del template
# los reemplazos de JAJ-131 vienen en null cuando el escenario no los trae
NO_OVERRIDES = {"endpoint_weights": None, "slowdowns": None, "business": None, "traffic_step": None}


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


def with_peak(peak):
    model = copy.deepcopy(load_sample(SAMPLE))
    model["traffic"]["peak_rps"]["value"] = peak
    return model


def test_project_starts_with_the_model_scenarios(client, pid):
    r = client.get(f"/projects/{pid}/scenarios")
    assert r.status_code == 200
    assert r.json() == [
        {"name": "cyberday", "multiplier": 20.0, "rps": None, "description": None, **NO_OVERRIDES},
        {"name": "pico_normal", "multiplier": 1.0, "rps": None, "description": None, **NO_OVERRIDES},
    ]
    assert client.get(f"/projects/{pid}/scenarios/cyberday").json()["multiplier"] == 20.0


def test_unknown_scenario_is_404_and_422_in_spanish(client, pid):
    r = client.get(f"/projects/{pid}/scenarios/black_friday")
    assert r.status_code == 404 and r.json()["error"]["resource"] == "scenario"
    r = client.post(f"/projects/{pid}/versions/1/runs", json={**RUN, "scenario": "black_friday"})
    err = r.json()["error"]
    assert r.status_code == 422 and err["code"] == "unknown_scenario"
    assert err["available"] == ["cyberday", "pico_normal"] and "El proyecto no tiene" in err["message"]


def test_project_scenario_works_for_any_version(client, pid):
    """Criterio 1: un escenario creado en el proyecto sirve aunque no esté en traffic.scenarios."""
    r = client.put(f"/projects/{pid}/scenarios/black_friday", json={"multiplier": 10, "description": "Black Friday"})
    assert r.status_code == 200 and r.json()["multiplier"] == 10.0
    client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 2}]})
    for n in (1, 2):
        run = client.post(f"/projects/{pid}/versions/{n}/runs", json={**RUN, "scenario": "black_friday"})
        assert run.status_code == 200, run.text
        assert run.json()["scenario"] == "black_friday"
        assert run.json()["rps"] == pytest.approx(PEAK * 10)


def test_multiplier_follows_each_version_peak(client, pid):
    """Criterio 2: cyberday ×20 da un rps distinto en dos versiones con picos distintos."""
    client.post(f"/projects/{pid}/versions", json={"model": with_peak(5.0), "note": "menos tráfico"})
    cmp = client.post(f"/projects/{pid}/compare", json={"a": 1, "b": 2, "scenario": "cyberday", **RUN})
    assert cmp.status_code == 200, cmp.text
    assert cmp.json()["run_a"]["rps"] == pytest.approx(PEAK * 20)
    assert cmp.json()["run_b"]["rps"] == pytest.approx(5.0 * 20)


def test_fixed_rps_is_the_same_in_every_version(client, pid):
    client.put(f"/projects/{pid}/scenarios/carga_fija", json={"rps": 50})
    client.post(f"/projects/{pid}/versions", json={"model": with_peak(5.0)})
    cmp = client.post(f"/projects/{pid}/compare", json={"a": 1, "b": 2, "scenario": "carga_fija", **RUN}).json()
    assert cmp["run_a"]["rps"] == cmp["run_b"]["rps"] == 50


def test_elastic_scenario_saves_and_runs_an_instant_jump(client, pid):
    url = f"/projects/{pid}/scenarios/cyberday"
    step = {"at_s": 30, "multiplier": 10, "duration_s": 60}
    saved = client.put(url, json={"rps": 100, "traffic_step": step})
    assert saved.status_code == 200, saved.text
    assert client.get(url).json()["traffic_step"] == step
    # El editor todavía envía el preset de cyberday, aun si se editó el escenario.
    version = f"/projects/{pid}/versions/1"
    params = {"scenario": "cyberday", "seed": 1, "arrivals": "uniform", "traffic_profile": "pico"}
    report = client.post(f"{version}/reports", json=params)
    assert report.status_code == 201, report.text
    response = client.post(f"{version}/results", json=params)
    assert response.status_code == 200, response.text
    assert response.headers[RUN_CACHE_HEADER] == "hit"
    run = response.json()["run"]
    series = run["series"]
    assert [sample["target_rps"] for sample in series] == [100] * 30 + [1000] * 30
    assert series[29]["arrivals"] == pytest.approx(100, abs=1)
    assert series[30]["arrivals"] == pytest.approx(1000, abs=1)
    assert run["traffic_profile"] == [
        {"start_s": 0, "end_s": 30, "from_rps": 100, "to_rps": 100},
        {"start_s": 30, "end_s": 60, "from_rps": 1000, "to_rps": 1000},
    ]


def test_editing_a_scenario_does_not_return_the_old_run(client, pid):
    """La tasa final entra en la cache_key (JAJ-75): editar el escenario simula de nuevo."""
    first = client.post(f"/projects/{pid}/versions/1/runs", json={**RUN, "scenario": "cyberday"})
    assert first.headers[RUN_CACHE_HEADER] == "miss"
    client.put(f"/projects/{pid}/scenarios/cyberday", json={"multiplier": 10})
    second = client.post(f"/projects/{pid}/versions/1/runs", json={**RUN, "scenario": "cyberday"})
    assert second.headers[RUN_CACHE_HEADER] == "miss"
    assert second.json()["rps"] == pytest.approx(PEAK * 10) != first.json()["rps"]
    again = client.post(f"/projects/{pid}/versions/1/runs", json={**RUN, "scenario": "cyberday"})
    assert again.headers[RUN_CACHE_HEADER] == "hit"


def test_put_replaces_and_switches_rate_kind(client, pid):
    client.put(f"/projects/{pid}/scenarios/cyberday", json={"rps": 300})
    assert client.get(f"/projects/{pid}/scenarios/cyberday").json() == {
        "name": "cyberday",
        "multiplier": None,
        "rps": 300.0,
        "description": None,
        **NO_OVERRIDES,
    }
    assert len(client.get(f"/projects/{pid}/scenarios").json()) == 2


@pytest.mark.parametrize(
    "name, body",
    [
        ("x", {}),
        ("x", {"multiplier": 2, "rps": 10}),
        ("x", {"multiplier": 0}),
        ("x", {"rps": -1}),
        ("x", {"multiplier": 2, "traffic_step": {"at_s": 30}}),
        ("x", {"rps": 100, "traffic_step": {"at_s": 30, "duration_s": 30}}),
        ("x", {"rps": 100, "traffic_step": {"at_s": 30, "multiplier": 1}}),
        ("Con Espacios", {"multiplier": 2}),
        ("x", {"multiplier": 2, "otro": 1}),
    ],
)
def test_put_validates(client, pid, name, body):
    r = client.put(f"/projects/{pid}/scenarios/{name}", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_parameters"


def test_unknown_project(client):
    assert client.get("/projects/nope/scenarios").status_code == 404
    assert client.put("/projects/nope/scenarios/x", json={"rps": 1}).status_code == 404


def test_multiplier_without_peak_says_what_to_do(client):
    model = copy.deepcopy(load_sample(SAMPLE))
    del model["traffic"]["peak_rps"]
    pid = client.post("/projects", json={"model": model}).json()["id"]
    r = client.post(f"/projects/{pid}/versions/1/runs", json={**RUN, "scenario": "cyberday"})
    assert r.status_code == 422 and "traffic.peak_rps" in r.json()["error"]["message"]


def test_explicit_rps_skips_the_scenario_table(client, pid):
    r = client.post(f"/projects/{pid}/versions/1/runs", json={**RUN, "scenario": "lo_que_sea", "rps": 20})
    assert r.status_code == 200 and r.json()["rps"] == 20


def test_rate_for():
    model = load_sample(SAMPLE)
    assert ProjectScenario("x", 2.0, None).rate_for(model) == pytest.approx(PEAK * 2)
    assert ProjectScenario("x", None, 7.0).rate_for(model) == 7.0


def test_scenarios_survive_a_restart(database_url, clean_pg_store):
    """Criterio 3."""
    from app.db.postgres_store import PostgresProjectStore

    client = TestClient(create_app(store=clean_pg_store))
    pid = client.post("/projects", json={"sample": SAMPLE}).json()["id"]
    step = {"at_s": 30, "duration_s": 60, "multiplier": 10}
    response = client.put(f"/projects/{pid}/scenarios/black_friday", json={"rps": 100, "traffic_step": step})
    assert response.status_code == 200, response.text
    restarted = PostgresProjectStore.from_url(database_url)
    try:
        scenarios = restarted.list_scenarios(pid)
        assert [s.name for s in scenarios] == ["black_friday", "cyberday", "pico_normal"]
        assert scenarios[0].rps == 100 and scenarios[0].traffic_step == step
    finally:
        restarted.close()
