"""Tráfico real escrito en el editor: el pico de req/s global (JAJ-170)."""

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


def test_editor_sets_the_peak_as_declared_and_the_run_uses_it(client):
    pid = client.post("/projects", json={"sample": SAMPLE}).json()["id"]
    ops = [{"op": "set_traffic_base", "peak_rps": 12}]
    r = client.post(f"/projects/{pid}/versions/1/ops", json={"ops": ops, "origin": "manual"})
    assert r.status_code == 201, r.text
    saved = r.json()["model"]
    peak = saved["traffic"]["peak_rps"]
    assert (peak["value"], peak["label"], peak["source"]) == (12, "SUPUESTO", "Declarado por el usuario en el editor")
    for sc in saved["traffic"]["scenarios"].values():
        mult = sc["multiplier"]["value"] if isinstance(sc["multiplier"], dict) else sc["multiplier"]
        assert sc["rps"]["value"] == pytest.approx(12 * mult, abs=0.01)
    run = client.post(
        f"/projects/{pid}/versions/{r.json()['number']}/runs",
        json={"scenario": "pico_normal", "seed": 1, "duration_s": 10},
    ).json()
    assert run["rps"] == pytest.approx(saved["traffic"]["scenarios"]["pico_normal"]["rps"]["value"], abs=0.01)


def test_the_agent_cannot_declare_traffic_for_the_user():
    with pytest.raises(OpError, match="solo para el editor"):
        apply_ops(load_sample(SAMPLE), [{"op": "set_traffic_base", "peak_rps": 50}])


def test_the_peak_must_be_positive():
    with pytest.raises(OpError, match="peak_rps"):
        apply_ops(load_sample(SAMPLE), [{"op": "set_traffic_base", "peak_rps": 0}], by_user=True)
