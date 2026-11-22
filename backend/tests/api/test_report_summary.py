"""El reporte lista todo componente con costo y su conclusión se lee bien, en formato es-CL (JAJ-164).

El caso del QA: una versión con caché mostraba en Componentes solo la API y la DB, y la conclusión decía
"v3 atiende 21.93 req/s con p95 de 15 ms y 0.0% de errores" con un escenario de 26,2 req/s, "Holgado para
este tráfico: API." y "sin contar db (sin precio)".
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.reports import es
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"
# un número en formato inglés: 21.93 req/s, 0.0%, US$148.67, 21,931 ms. En es-CL, "21.931 ms" son miles.
ENGLISH_NUMBER = re.compile(r"\d\.\d{1,2} ?(?:%|req/s|ms|×)|US\$\d[\d,]*\.\d{2}\b|\d,\d{3} ?(?:ms|req/s)")


@pytest.fixture
def client():
    return TestClient(create_app(store=InMemoryProjectStore(), auth=None, github_app=None))


@pytest.fixture
def pid(client):
    pid = client.post("/projects", json={"sample": SAMPLE}).json()["id"]
    client.put(f"/projects/{pid}/scenarios/cyberday", json={"multiplier": 20})
    return pid


def report(client, pid, version=1, **params) -> dict:
    r = client.post(f"/projects/{pid}/versions/{version}/reports", json={"seed": 1, "duration_s": 30, **params})
    assert r.status_code == 201, r.text
    return r.json()


def with_cache(client, pid) -> int:
    r = client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "add_cache", "endpoint": "GET /items/"}]})
    assert r.status_code == 201, r.text
    return r.json()["number"]


def test_every_component_with_a_cost_is_in_the_table(client, pid):
    rep = report(client, pid, with_cache(client, pid), scenario="actual")
    priced_nodes = {line["node"] for line in rep["costs"]["lines"] if line["node"]}
    rows = {c["id"]: c for c in rep["components"]}
    assert priced_nodes <= set(rows)  # la caché incluida
    cache = rows["cache"]
    # el motor no simula su ocupación: sin uso ni margen, con su costo y sus aciertos
    assert cache["label"] == "Caché" and cache["utilization"] is None and cache["headroom_x"] is None
    assert cache["usd_month"] > 0 and cache["priced"] is True and cache["status"] == "ok"
    assert re.match(r"Acertó \d+(,\d)? % de [\d.]+ consultas\. El motor no simula su uso", cache["why"])


def test_cache_row_works_in_markdown_and_comparison(client, pid):
    plain, cached = (
        report(client, pid, scenario="actual"),
        report(client, pid, with_cache(client, pid), scenario="actual"),
    )
    md = client.get(f"/projects/{pid}/reports/{cached['id']}/markdown").text
    assert "| Caché | 🟢 OK | — / — |" in md
    cmp = client.post(f"/projects/{pid}/reports/compare", json={"a": plain["id"], "b": cached["id"]}).json()
    assert cmp["delta"]["components"]["cache"] == {
        "a": None,
        "b": {"label": "Caché", "status": "ok", "utilization": None},
    }


def test_the_summary_does_not_contradict_zero_errors(client, pid):
    """Con tráfico de hoy no hay errores ni requests en fila: lo dice así, sin '0.0% de errores'."""
    rep = report(client, pid, scenario="actual")
    assert rep["results"]["error_rate"] == 0 and not rep["results"]["saturation"]["saturated"]
    assert re.match(
        r"En actual, v1 atiende (en promedio )?[\d.]+(,\d)? req/s.*, con p95 de [\d.]+ ms y sin errores\.",
        rep["conclusion"],
    )


def test_lower_throughput_than_the_scenario_is_explained(client, pid):
    """Con subida, meseta y bajada, el promedio queda bajo la tasa del escenario: la frase dice las dos."""
    rep = report(client, pid, scenario="actual", traffic_profile="pico", duration_s=60)
    thr, rps = rep["results"]["throughput_rps"], rep["scenario"]["rps"]
    assert thr < rps * 0.95
    assert f"atiende en promedio {es.num(thr)} req/s (el escenario llega a {es.num(rps)} req/s)" in rep["conclusion"]


def test_saturated_run_says_errors_are_only_of_the_finished_and_does_not_repeat(client, pid):
    rep = report(client, pid, scenario="cyberday")
    text = rep["conclusion"]
    assert rep["results"]["saturation"]["saturated"]
    assert "sin errores" not in text and "de errores entre las que terminaron" in text
    assert text.count("El sistema no alcanza a atender este tráfico") == 1
    assert "La API está sobrecargada." in text


def test_natural_sentences_and_es_cl_numbers(client, pid):
    """Ni 'Sobrecargado: API.' ni 'sin contar db (sin precio)', y ningún número en formato inglés."""
    model = load_sample(SAMPLE)
    model["deployment"]["db"]["provider"] = "local"  # la DB sin precio
    local = client.post("/projects", json={"model": model}).json()["id"]
    reps = [
        report(client, pid, scenario="actual"),
        report(client, pid, scenario="cyberday"),
        report(client, local, rps=12.5),
    ]
    for rep in reps:
        text = rep["conclusion"]
        assert not ENGLISH_NUMBER.search(text), text
        assert "Sobrecargado:" not in text and "Holgado para" not in text and "(sin precio)" not in text
        for c in rep["components"]:
            assert not ENGLISH_NUMBER.search(c["why"]), c["why"]
    assert reps[2]["conclusion"].endswith("sin contar la base de datos, que no tiene precio.")
    assert reps[2]["scenario"]["label"] == "personalizado (12,5 req/s)"
    md = client.get(f"/projects/{pid}/reports/{reps[1]['id']}/markdown").text
    assert "0.0%" not in md and "US$" in md


@pytest.mark.parametrize(
    ("call", "out"),
    [
        (lambda: es.num(21.93), "21,9"),
        (lambda: es.num(26.0), "26"),
        (lambda: es.num(20731, 0), "20.731"),
        (lambda: es.usd(148.67), "US$148,67"),
        (lambda: es.usd(1234.5), "US$1.234,50"),
        (lambda: es.pct(0.125), "12,5 %"),
        (lambda: es.pct(0, 0), "0 %"),
    ],
)
def test_es_format(call, out):
    assert call() == out
