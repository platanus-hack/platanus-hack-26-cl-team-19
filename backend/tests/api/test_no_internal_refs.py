"""Ningún texto que ve el usuario cita IDs de Linear ni «el guion de la demo» (JAJ-152).

Las fuentes de cada número, los avisos de la simulación, el costo, el reporte y lo que lee el agente
(que puede repetirlo en el chat) explican de dónde sale el número con palabras del usuario. Los IDs de
las tarjetas quedan en los comentarios y docstrings del código, que no se muestran.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.loop import system_prompt
from app.agent.tools import TOOL_DESCRIPTIONS
from app.api.main import create_app
from app.api.store import InMemoryProjectStore

APP = Path(__file__).resolve().parents[2] / "app"
DATA_FILES = [APP / "catalog" / "catalog.json", *sorted((APP / "samples").glob("*.model.json"))]
SAMPLES = [p.name.removesuffix(".model.json") for p in DATA_FILES[1:]]
# IDs de tarjetas (JAJ-8) o del proyecto (P-JAJ-1), carpetas de spikes y la frase del guion
INTERNAL = re.compile(r"\bJAJ-\d+|P-JAJ|spikes/|guion de la demo", re.IGNORECASE)
RUN = {"seed": 1, "duration_s": 5}


def strings(x, path=""):
    """Cada string de un JSON, con su ruta: ``(".db_shapes.pk.source", "Lectura por PK…")``."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield from strings(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from strings(v, f"{path}[{i}]")
    elif isinstance(x, str):
        yield path, x


def leaks(x) -> list[str]:
    return [f"{p}: {s}" for p, s in strings(x) if INTERNAL.search(s)]


@pytest.mark.parametrize("path", DATA_FILES, ids=lambda p: p.name)
def test_catalog_and_samples_have_no_internal_ids(path):
    """Todo string cuenta, también ``_doc`` y ``_source``: algunos terminan dentro de una ``source``."""
    assert leaks(json.loads(path.read_text(encoding="utf-8"))) == []


def test_what_the_agent_reads_has_no_internal_ids():
    """El agente repite lo que lee: las descripciones de sus tools y su prompt tampoco llevan IDs."""
    assert leaks(TOOL_DESCRIPTIONS) == []
    assert leaks(system_prompt("p")) == []


@pytest.fixture
def client():
    return TestClient(create_app(store=InMemoryProjectStore(), auth=None, github_app=None))


def report(client, pid, version=1, **params):
    r = client.post(f"/projects/{pid}/versions/{version}/reports", json={**RUN, **params})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("sample", SAMPLES)
def test_results_costs_and_reports_have_no_internal_ids(client, sample):
    """Lo que devuelve la API en el camino de la demo: resultados, costos, comparación y reportes."""
    pid = client.post("/projects", json={"sample": sample}).json()["id"]
    assert client.put(f"/projects/{pid}/scenarios/cyberday", json={"multiplier": 20}).status_code == 200
    ops = {"ops": [{"op": "scale_api", "replicas": 2}]}
    assert client.post(f"/projects/{pid}/versions/1/ops", json=ops).status_code == 201

    seen = {
        "versión": client.get(f"/projects/{pid}/versions/1").json(),
        "resultados": client.post(f"/projects/{pid}/versions/1/results", json={**RUN, "scenario": "cyberday"}).json(),
        "costo": client.get(f"/projects/{pid}/versions/2/costs").json(),
        "comparación": client.post(
            f"/projects/{pid}/compare", json={**RUN, "scenario": "cyberday", "a": 1, "b": 2}
        ).json(),
    }
    a = report(client, pid, scenario="actual")
    b = report(client, pid, version=2, scenario="cyberday")
    c = report(client, pid, rps=500)
    pair = client.post(f"/projects/{pid}/reports/compare", json={"a": a["id"], "b": b["id"]}).json()
    seen.update(reportes=[a, b, c, pair], markdown=client.get(f"/projects/{pid}/reports/{b['id']}/markdown").text)
    assert leaks(seen) == []


def test_the_report_cites_the_project_scenario_not_the_catalog(client):
    """El escenario de la corrida es el de la tabla del proyecto: el que creó el usuario dice «Definido por
    el usuario», y los escenarios que trae el modelo del catálogo no se listan como supuestos."""
    pid = client.post("/projects", json={"sample": SAMPLES[0]}).json()["id"]
    client.put(f"/projects/{pid}/scenarios/cyberday", json={"multiplier": 20})

    cyber = report(client, pid, scenario="cyberday")["assumptions"]
    first = cyber["by_source"][0]["source"]
    assert first.startswith("Escenario «cyberday» del proyecto: 20 veces el pico del modelo (")
    assert first.endswith("req/s). Definido por el usuario")
    assert not [g for g in cyber["by_source"] if g["example_path"].startswith("traffic.scenarios.")]

    actual = report(client, pid, scenario="actual")["assumptions"]["by_source"][0]["source"]
    assert actual.startswith("Escenario «actual» del proyecto:") and actual.endswith(
        "Nace con el proyecto, con el tráfico de hoy del modelo"
    )
    custom = report(client, pid, rps=12.5)["assumptions"]["by_source"][0]["source"]
    assert custom == "Tasa elegida para esta corrida: 12,5 req/s"
