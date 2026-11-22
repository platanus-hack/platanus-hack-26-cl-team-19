"""Effort y fast mode del LLM que lee el repo, según el entorno (JAJ-146)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.loop import AnthropicLLM, cost_usd, extract_options
from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from tests.github.test_github import KEY, FakeAnalyst, FakeGitHub, connect

EFFORT = "BRANCHPOINT_ANTHROPIC_EXTRACT_EFFORT"
SPEED = "BRANCHPOINT_ANTHROPIC_EXTRACT_SPEED"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (EFFORT, SPEED, "BRANCHPOINT_ANTHROPIC_EXTRACT_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_without_variables_the_model_defaults_apply():
    assert extract_options("claude-opus-5-5") == {}


def test_production_opus_with_fast_mode(monkeypatch):
    monkeypatch.setenv(SPEED, "fast")
    assert extract_options("claude-opus-5-5") == {"speed": "fast"}


def test_development_sonnet_with_medium_effort(monkeypatch):
    monkeypatch.setenv(EFFORT, " Medium ")
    assert extract_options("claude-sonnet-5-5") == {"effort": "medium"}


def test_fast_mode_is_ignored_on_a_model_without_it(monkeypatch, caplog):
    monkeypatch.setenv(SPEED, "fast")
    monkeypatch.setenv(EFFORT, "medium")
    assert extract_options("claude-sonnet-5-5") == {"effort": "medium"}
    assert "no tiene fast mode" in caplog.text


def test_invalid_values_are_ignored(monkeypatch):
    monkeypatch.setenv(EFFORT, "altísimo")
    monkeypatch.setenv(SPEED, "turbo")
    assert extract_options("claude-opus-5-5") == {}


class FakeStream:
    """Lo que devuelve ``messages.stream``: registra los parámetros y entrega un mensaje sin tools."""

    def __init__(self, calls: list[dict], **kwargs) -> None:
        calls.append(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def get_final_message(self):
        usage = SimpleNamespace(
            input_tokens=1, output_tokens=2, cache_read_input_tokens=0, cache_creation_input_tokens=0
        )
        return SimpleNamespace(content=[], stop_reason="end_turn", usage=usage)


def sent(llm: AnthropicLLM) -> dict:
    calls: list[dict] = []
    llm._client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: FakeStream(calls, **kw)))
    llm.complete("sistema", [{"role": "user", "content": "hola"}], [])
    return calls[0]


def test_the_request_carries_effort_and_speed_only_when_set():
    plain = sent(AnthropicLLM("k", "claude-opus-5-5"))
    assert "output_config" not in plain and "speed" not in plain
    tuned = sent(AnthropicLLM("k", "claude-opus-5-5", effort="low", speed="fast"))
    assert tuned["output_config"] == {"effort": "low"} and tuned["speed"] == "fast"


def test_fast_mode_costs_double():
    usage = {"input": 1_000_000, "output": 1_000_000, "cache_read": 0, "cache_write": 0}
    assert cost_usd("claude-opus-5-5", usage)["value"] == 24.0
    assert cost_usd("claude-opus-5-5", usage, "fast")["value"] == 48.0
    assert cost_usd("claude-sonnet-5-5", usage, "fast") is None  # sin fast mode en la tabla: sin costo inventado


class RecordingLLM(AnthropicLLM):
    """Un ``AnthropicLLM`` de verdad (para que la ruta le aplique las opciones) que responde como el analista
    falso y anota con qué effort y velocidad le tocó trabajar."""

    seen: list[tuple[str | None, str | None]] = []

    def __init__(self, api_key, model=None) -> None:
        super().__init__(api_key, model)
        self._analyst = FakeAnalyst()

    def complete(self, system, messages, tools):
        RecordingLLM.seen.append((self.effort, self.speed))
        return self._analyst.complete(system, messages, tools)


def test_the_ingestion_applies_the_environment_to_the_extractor(monkeypatch):
    monkeypatch.setenv(SPEED, "fast")
    monkeypatch.setenv("BRANCHPOINT_FRONTEND_URL", "http://front.test")
    RecordingLLM.seen = []
    app = create_app(store=InMemoryProjectStore(), auth=None, github_app=FakeGitHub())
    app.state.llm_factory = RecordingLLM
    client = TestClient(app, follow_redirects=False, headers={"X-Anthropic-Api-Key": KEY})
    connect(client)

    job = client.post("/github/ingestions", json={"repo_full_name": "acme/tienda"}).json()
    done = client.get(f"/github/ingestions/{job['id']}").json()
    assert done["status"] == "done", done
    assert RecordingLLM.seen and set(RecordingLLM.seen) == {(None, "fast")}
    analysis = client.get(f"/projects/{done['project_id']}/versions/1").json()["model"]["repo"]["source"]["analysis"]
    assert analysis["speed"] == "fast" and analysis["model"] == "claude-opus-5-5"
    assert done["cost"]["value"] == cost_usd("claude-opus-5-5", analysis["usage"], "fast")["value"]
