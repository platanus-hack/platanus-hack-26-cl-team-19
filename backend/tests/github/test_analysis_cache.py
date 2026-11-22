"""Reimportar un commit ya analizado reutiliza la entrega del LLM (JAJ-146)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.github import ingestion
from tests.github.test_github import APP, KEY, SHA, FakeAnalyst, FakeGitHub, connect, tarball

OTHER_SHA = "1111111111111111111111111111111111111111"


@pytest.fixture
def github():
    return FakeGitHub()


@pytest.fixture
def store():
    return InMemoryProjectStore()


@pytest.fixture
def analyst():
    """Un solo analista para todas las ingestas, para contar las vueltas del LLM entre importaciones."""
    return FakeAnalyst()


@pytest.fixture
def client(github, store, analyst, monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_FRONTEND_URL", "http://front.test")
    app = create_app(store=store, auth=None, github_app=github)
    app.state.llm_factory = lambda key, model=None: analyst
    return TestClient(app, follow_redirects=False, headers={"X-Anthropic-Api-Key": KEY})


def ingest(client) -> dict:
    job = client.post("/github/ingestions", json={"repo_full_name": "acme/tienda"}).json()
    done = client.get(f"/github/ingestions/{job['id']}").json()
    assert done["status"] == "done", done
    return done


def analysis(client, done: dict) -> dict:
    v1 = client.get(f"/projects/{done['project_id']}/versions/1").json()
    return v1["model"]["repo"]["source"]["analysis"]


def test_the_same_commit_twice_calls_the_llm_once(client, github, analyst):
    connect(client)
    first = ingest(client)
    calls = analyst.calls
    assert calls > 0 and first["cost"] is not None

    second = ingest(client)
    assert analyst.calls == calls  # la segunda no habló con el LLM
    assert second["project_id"] != first["project_id"] and second["endpoints"] == first["endpoints"]
    assert second["cost"] is None and second["llm_steps"] == 0
    cached = analysis(client, second)
    assert cached["cached"] == {"usage": analysis(client, first)["usage"], "steps": analysis(client, first)["steps"]}
    assert cached["model"] == "claude-opus-5-5" and cached["usage"] == {} and cached["steps"] == 0
    # el tarball se baja igual: la IaC y el modelo se rearman con el repo y el catálogo de hoy
    assert len(github.fetched) == 2


def test_a_new_commit_is_analyzed_again(client, github, analyst, monkeypatch):
    connect(client)
    ingest(client)
    calls = analyst.calls
    monkeypatch.setattr(type(github), "fetch", lambda self, i, name, ref: (OTHER_SHA, tarball({"src/app.js": APP})))
    ingest(client)
    assert analyst.calls > calls


def test_a_new_analyzer_does_not_reuse_old_analyses(client, analyst, monkeypatch):
    connect(client)
    ingest(client)
    calls = analyst.calls
    monkeypatch.setattr(ingestion, "ANALYZER_FINGERPRINT", "otra-huella")
    ingest(client)
    assert analyst.calls > calls


def test_a_broken_cache_does_not_break_the_ingestion(client, store: InMemoryProjectStore, analyst, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("Postgres no responde")

    monkeypatch.setattr(store, "find_analysis", boom)
    monkeypatch.setattr(store, "save_analysis", boom)
    connect(client)
    assert ingest(client)["endpoints"] == 2
    assert analyst.calls > 0


def test_an_analysis_with_dropped_evidence_is_not_cached(store: InMemoryProjectStore, monkeypatch):
    real = ingestion.analyze_repo

    def with_dropped(*args, **kwargs):
        result = real(*args, **kwargs)
        result.dropped.append("GET /items: la línea citada no existe")
        return result

    monkeypatch.setattr(ingestion, "analyze_repo", with_dropped)
    cache = ingestion.AnalysisCache(store, 7)
    ingestion.model_from_tarball(tarball({"src/app.js": APP}), "acme/tienda", FakeAnalyst(), SHA, cache=cache)
    assert store.find_analysis(7, SHA, ingestion.ANALYZER_FINGERPRINT) is None


def test_a_short_sha_is_not_cached(store: InMemoryProjectStore):
    cache = ingestion.AnalysisCache(store, 7)
    analyst = FakeAnalyst()
    for _ in range(2):
        ingestion.model_from_tarball(tarball({"src/app.js": APP}), "acme/tienda", analyst, SHA[:7], cache=cache)
    assert analyst.calls == 4  # dos vueltas por análisis, sin reutilizar
