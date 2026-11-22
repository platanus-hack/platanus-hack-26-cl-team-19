"""La frase de costo de ``POST /projects/{id}/compare`` cuando un componente tiene precio en una sola versión (JAJ-156).

El caso del QA: v1 con la API en local y v2 con la API en Render starter (US$7/mes). Antes decía
"v2 cuesta +US$0.00/mes … ni la API (con precio solo en v2) y evita entre US$0 y US$0 por hora", y el
editor mostraba "US$0,00 → US$0,00 = Igual" con totales distintos.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.routes.projects import _usd
from app.api.store import InMemoryProjectStore

RUN = {"scenario": "actual", "seed": 1, "duration_s": 10}


@pytest.fixture
def client():
    return TestClient(create_app(store=InMemoryProjectStore(), auth=None, github_app=None))


def new_version(client, pid, version, **op) -> int:
    r = client.post(f"/projects/{pid}/versions/{version}/ops", json={"ops": [{"op": "change_api_host", **op}]})
    assert r.status_code == 201, r.text
    return r.json()["number"]


@pytest.fixture
def local_vs_render(client):
    """v2: la API en local; v3: la API en Render starter. Lo demás (DB, transferencia) igual."""
    pid = client.post("/projects", json={"sample": "full-stack-fastapi-template"}).json()["id"]
    local = new_version(client, pid, 1, provider="local")
    render = new_version(client, pid, local, provider="render", plan="starter")
    return pid, local, render


def compare(client, pid, a, b) -> dict:
    r = client.post(f"/projects/{pid}/compare", json={**RUN, "a": a, "b": b})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_component_priced_in_one_version_is_said_apart_with_its_amount(client, local_vs_render):
    pid, local, render = local_vs_render
    body = compare(client, pid, local, render)
    delta = body["cost_delta"]
    # la API tiene precio solo en v3: el editor sabe que la fila "comparable" no es una comparación
    assert delta["comparable"] is False and delta["priced_in_one"] == {"api": 7.0}
    assert body["cost_b"]["total"]["value"] - body["cost_a"]["total"]["value"] == pytest.approx(7.0, abs=0.01)
    assert body["summary"].startswith(f"v{render} suma US$7,00/mes en la API (v{local} no tiene precio); ")
    assert "el resto cuesta lo mismo" in body["summary"]
    # con tráfico de hoy ninguna versión falla: no hay ventas en juego que contar
    assert "entre US$0 y US$0" not in body["summary"] and "ventas en juego" not in body["summary"]


def test_the_other_way_round_names_the_base(client, local_vs_render):
    pid, local, render = local_vs_render
    summary = compare(client, pid, render, local)["summary"]
    assert summary.startswith(f"v{render} suma US$7,00/mes en la API (v{local} no tiene precio)")


def test_both_priced_is_comparable_as_before(client, local_vs_render):
    pid, local, render = local_vs_render
    body = compare(client, pid, 1, render)  # Fargate contra Render: las dos con precio
    assert body["cost_delta"]["comparable"] is True and body["cost_delta"]["priced_in_one"] == {}
    diff = body["cost_delta"]["diff"]
    assert body["summary"].startswith(f"v{render} cuesta {'+' if diff >= 0 else '−'}{_usd(diff)}/mes respecto de v1")


def test_same_version_costs_the_same(client, local_vs_render):
    pid, _, render = local_vs_render
    assert compare(client, pid, render, render)["summary"].startswith(f"v{render} cuesta lo mismo que v{render}")


def test_lost_sales_are_kept_when_there_is_a_difference(client):
    """Con una versión que falla, la cláusula de ventas sigue: solo se omite cuando da US$0 en las dos cotas."""
    pid = client.post("/projects", json={"sample": "full-stack-fastapi-template"}).json()["id"]
    client.put(f"/projects/{pid}/scenarios/cyberday", json={"multiplier": 20})
    bigger = client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 3}]})
    r = client.post(
        f"/projects/{pid}/compare",
        json={**RUN, "scenario": "cyberday", "duration_s": 60, "a": 1, "b": bigger.json()["number"]},
    )
    assert "ventas en juego" in r.json()["summary"]


@pytest.mark.parametrize(
    ("x", "decimals", "out"),
    [
        (7, 2, "US$7,00"),
        (57.66, 2, "US$57,66"),
        (1234.5, 2, "US$1.234,50"),
        (-3.2, 2, "US$3,20"),
        (12345.6, 0, "US$12.346"),
    ],
)
def test_usd_uses_the_editor_format(x, decimals, out):
    assert _usd(x, decimals) == out
