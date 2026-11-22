"""Una propuesta del chat solo afecta la versión nueva después de aceptarla."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.loop import Turn
from app.api.main import create_app
from app.api.store import InMemoryProjectStore


class ScenarioLLM:
    model = "claude-opus-5-5"

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.called = False

    def complete(self, system, messages, tools):
        assert "v1" in system and "'cyberday'" in system
        names = {tool["name"] for tool in tools}
        assert "propose_scenario" in names and "set_traffic" not in names
        if not self.called:
            self.called = True
            return Turn(
                [
                    {
                        "type": "tool_use",
                        "id": "scenario",
                        "name": "propose_scenario",
                        "input": {
                            "project_id": self.project_id,
                            "scenario": {"name": "cyberday", "rps": 42, "slowdowns": {"db": 2}},
                        },
                    }
                ],
                "tool_use",
            )
        return Turn([{"type": "text", "text": "Revisa la propuesta."}], "end_turn")


@pytest.fixture(params=["memoria", "postgres"])
def client(request):
    store = InMemoryProjectStore() if request.param == "memoria" else request.getfixturevalue("clean_pg_store")
    app = create_app(store=store, auth=None)
    return TestClient(app)


def test_chat_proposes_scenario_then_accepts_once(client):
    created = client.post("/projects", json={"sample": "full-stack-fastapi-template"}).json()
    pid = created["id"]
    path = f"/projects/{pid}"
    client.app.state.llm_factory = lambda key: ScenarioLLM(pid)
    response = client.post(
        f"{path}/chat",
        headers={"X-Anthropic-Api-Key": "test"},
        json={
            "version": 1,
            "scenario": "cyberday",
            "messages": [{"role": "user", "content": "Pon CyberDay a 42 req/s y demora la DB al doble."}],
        },
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert response.status_code == 200
    result = next(event["result"] for event in events if event["type"] == "tool_result")
    proposal = result["proposal"]
    assert any("42 req/s" in line for line in proposal["changes"])
    assert len(client.get(path).json()["versions"]) == 1

    url = f"{path}/chat/proposals/{proposal['id']}/accept"
    first = client.post(url, json=proposal["draft"])
    repeated = client.post(url, json=proposal["draft"])
    assert first.status_code == repeated.status_code == 201
    assert first.json()["number"] == repeated.json()["number"] == 2
    assert first.json()["parent"] == 1
    assert len(client.get(path).json()["versions"]) == 2

    params = {"scenario": "cyberday", "duration_s": 4}
    baseline = client.post(f"{path}/versions/1/results", json=params).json()
    changed = client.post(f"{path}/versions/2/results", json=params).json()
    assert baseline["run"]["rps"] != 42
    assert changed["run"]["rps"] == 42
    assert changed["run"]["overrides"]
    comparison = client.post(f"{path}/compare", json={**params, "a": 1, "b": 2}).json()
    assert comparison["run_a"]["rps"] == baseline["run"]["rps"]
    assert comparison["run_b"]["rps"] == 42
