"""El loop del chat (JAJ-67) con un LLM falso que devuelve tool calls fijas."""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.loop import Turn, run_agent
from app.agent.tools import AgentTools
from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.samples import load_sample

QUOTE = "recibimos 100.000 pedidos al día y en CyberDay 20×, el SLO es p95 < 300 ms"


def use(i, name, args):
    return {"type": "tool_use", "id": f"t{i}", "name": name, "input": args}


class FakeLLM:
    """Devuelve las vueltas en orden y guarda lo que recibió en cada una."""

    model = "claude-opus-5-5"

    def __init__(self, turns):
        self.turns, self.seen = list(turns), []

    def complete(self, system, messages, tools):
        self.seen.append(json.loads(json.dumps(messages)))
        content, stop = self.turns.pop(0)
        return Turn(content=content, stop_reason=stop, usage={"input": 1000, "output": 100})


@pytest.fixture
def setup():
    store = InMemoryProjectStore()
    project = store.create("tienda", load_sample("full-stack-fastapi-template"), None)
    return store, project


def demo_turns(pid):
    return [
        # 1. se equivoca: un número que el usuario no dijo
        (
            [use(1, "set_traffic", {"project_id": pid, "volume": 120000, "unit": "orders_per_day", "quote": QUOTE})],
            "tool_use",
        ),
        # 2. lee el error y corrige; además guarda la meta
        (
            [
                use(
                    2,
                    "set_traffic",
                    {"project_id": pid, "volume": 100000, "unit": "orders_per_day", "peak_factor": 20, "quote": QUOTE},
                ),
                use(3, "set_goals", {"project_id": pid, "slo_p95_ms": 300, "quote": QUOTE}),
            ],
            "tool_use",
        ),
        # 3. simula CyberDay
        ([use(4, "simulate", {"project_id": pid, "scenario": "cyberday"})], "tool_use"),
        # 4. responde
        (
            [{"type": "text", "text": "En CyberDay la CPU de la API se satura en backend/app/core/security.py:36."}],
            "end_turn",
        ),
    ]


def test_demo_conversation(setup):
    store, project = setup
    llm = FakeLLM(demo_turns(project.id))
    events = list(run_agent(AgentTools(store, None), llm, project.id, [{"role": "user", "content": QUOTE}]))
    calls = [e["name"] for e in events if e["type"] == "tool_call"]
    assert calls == ["set_traffic", "set_traffic", "set_goals", "simulate"]
    results = [e["result"] for e in events if e["type"] == "tool_result"]
    assert "no aparece en quote" in results[0]["error"]  # el error llega...
    # ...y el LLM lo ve en la vuelta siguiente, marcado como error
    tool_result = llm.seen[1][-1]["content"][0]
    assert tool_result["is_error"] is True and "no aparece en quote" in tool_result["content"]
    sim = results[3]
    assert sim["bottleneck"]["line"] == "backend/app/core/security.py:36"
    assert sim["goals"]["p95"]["ok"] is False
    done = events[-1]
    assert done["type"] == "done" and done["iterations"] == 4 and done["stop_reason"] == "end_turn"
    assert done["usage"] == {"input": 4000, "output": 400}
    assert done["cost"]["value"] > 0 and done["cost"]["source"]
    assert [v.origin for v in store.get(project.id).versions] == ["repo", "agente"]


def test_max_iterations(setup):
    store, project = setup
    loop_forever = [([use(i, "list_projects", {})], "tool_use") for i in range(10)]
    events = list(
        run_agent(
            AgentTools(store, None),
            FakeLLM(loop_forever),
            project.id,
            [{"role": "user", "content": "hola"}],
            max_iterations=3,
        )
    )
    assert sum(e["type"] == "tool_call" for e in events) == 3
    assert events[-1]["stop_reason"] == "max_iterations"


def test_llm_failure_is_an_event(setup):
    store, project = setup

    class Broken:
        model = "claude-opus-5-5"

        def complete(self, *a):
            raise RuntimeError("sin crédito")

    events = list(run_agent(AgentTools(store, None), Broken(), project.id, [{"role": "user", "content": "hola"}]))
    assert events == [{"type": "error", "message": "El LLM falló (RuntimeError): sin crédito"}]


def test_chat_endpoint_streams_ndjson(setup, monkeypatch):
    store, project = setup
    app = create_app(store=store, auth=None, github_app=None)
    keys = []

    def factory(key):
        keys.append(key)
        return FakeLLM(demo_turns(project.id))

    app.state.llm_factory = factory
    body = {"messages": [{"role": "user", "content": QUOTE}]}
    with TestClient(app) as client:
        monkeypatch.delenv("BRANCHPOINT_CHAT_DEMO", raising=False)
        r = client.post(f"/projects/{project.id}/chat", json=body)
        assert r.status_code == 422 and "X-Anthropic-Api-Key" in r.json()["error"]["message"]
        r = client.post(
            f"/projects/{project.id}/chat", json=body, headers={"X-Anthropic-Api-Key": "sk-ant-del-usuario"}
        )
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in r.text.splitlines()]
        assert [e["type"] for e in events][-1] == "done"
        assert "sk-ant-del-usuario" not in r.text  # la key no vuelve en la respuesta
        assert keys == ["sk-ant-del-usuario"]
        monkeypatch.setenv("BRANCHPOINT_CHAT_DEMO", "on")
        r = client.post(f"/projects/{project.id}/chat", json=body)
        assert r.status_code == 200 and keys[-1] is None  # demo: la credencial la resuelve el SDK
        assert client.post("/projects/nope/chat", json=body).status_code == 404
