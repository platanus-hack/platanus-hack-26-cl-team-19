"""Tráfico real escrito en el editor: pico de req/s y peso de cada endpoint (JAJ-170)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agent import OpError, apply_ops
from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"


@pytest.fixture
def client():
    return TestClient(create_app(store=InMemoryProjectStore(), auth=None, github_app=None))


def test_editor_sets_peak_and_weights_as_declared_and_the_run_uses_them(client):
    pid = client.post("/projects", json={"sample": SAMPLE}).json()["id"]
    model = client.get(f"/projects/{pid}/versions/1").json()["model"]
    first, second = (e["id"] for e in model["endpoints"][:2])
    ops = [{"op": "set_traffic_base", "peak_rps": 12, "endpoint_weights": {first: 3, second: 1}}]
    r = client.post(f"/projects/{pid}/versions/1/ops", json={"ops": ops, "origin": "manual"})
    assert r.status_code == 201, r.text
    saved = r.json()["model"]
    peak = saved["traffic"]["peak_rps"]
    assert (peak["value"], peak["label"], peak["source"]) == (12, "SUPUESTO", "Declarado por el usuario en el editor")
    cyber = saved["traffic"]["scenarios"]["cyberday"]
    mult = cyber["multiplier"]["value"] if isinstance(cyber["multiplier"], dict) else cyber["multiplier"]
    assert cyber["rps"]["value"] == pytest.approx(12 * mult, abs=0.01)
    weights = {e["id"]: e["weight"] for e in saved["endpoints"]}
    assert sum(w["value"] if isinstance(w, dict) else w for w in weights.values()) == pytest.approx(1, abs=0.01)
    assert weights[first]["label"] == "SUPUESTO" and weights[first]["value"] == pytest.approx(
        3 * weights[second]["value"], abs=0.001
    )
    run = client.post(
        f"/projects/{pid}/versions/{r.json()['number']}/runs",
        json={"scenario": "pico_normal", "seed": 1, "duration_s": 10},
    ).json()
    assert run["rps"] == pytest.approx(saved["traffic"]["scenarios"]["pico_normal"]["rps"]["value"], abs=0.01)


def test_the_agent_cannot_declare_traffic_for_the_user():
    with pytest.raises(OpError, match="solo para el editor"):
        apply_ops(load_sample(SAMPLE), [{"op": "set_traffic_base", "peak_rps": 50}])


def test_bad_weights_are_rejected():
    model = load_sample(SAMPLE)
    with pytest.raises(OpError, match="No existen"):
        apply_ops(model, [{"op": "set_traffic_base", "endpoint_weights": {"GET /nada": 1}}], by_user=True)
    zeros = {e["id"]: 0 for e in model["endpoints"]}
    with pytest.raises(OpError, match="mayor que 0"):
        apply_ops(model, [{"op": "set_traffic_base", "endpoint_weights": zeros}], by_user=True)
