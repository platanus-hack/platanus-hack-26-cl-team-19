"""IA-3 (JAJ-117): la ingesta elige la key como el chat (header, personal, Branchpoint con cuota), con Postgres."""

from __future__ import annotations

import time
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.auth import AuthError, User
from app.api.main import create_app
from tests.github.test_github import FakeAnalyst, FakeGitHub, connect

ALICE = str(uuid.UUID(int=0xA11CE))


class FakeAuth:
    def verify(self, token: str) -> User:
        try:
            return User(str(uuid.UUID(token)))
        except ValueError:
            raise AuthError("token inválido") from None


@pytest.fixture
def store(database_url, clean_pg_store):
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "insert into auth.users (id, aud, role, email) values (%s, 'authenticated', 'authenticated', 'a@x.cl')"
            " on conflict (id) do nothing",
            (ALICE,),
        )
        conn.execute("truncate team_chat_usage, llm_credentials")
    return clean_pg_store


@pytest.fixture
def keys():
    return []


@pytest.fixture
def client(store, keys, monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_FRONTEND_URL", "http://front.test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-branchpoint")
    monkeypatch.setenv("BRANCHPOINT_TEAM_EXTRACT_LIMIT", "2")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app(store=store, auth=FakeAuth(), github_app=FakeGitHub(), attachment_storage=None)
    app.state.llm_factory = lambda key, model=None: keys.append(key) or FakeAnalyst()
    client = TestClient(app, follow_redirects=False, headers={"Authorization": f"Bearer {ALICE}"})
    connect(client)
    return client


def start(client, **body):
    return client.post("/github/ingestions", json={"repo_full_name": "acme/tienda", **body})


def wait(client, job_id):
    for _ in range(50):
        job = client.get(f"/github/ingestions/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("la ingesta no terminó")


def test_branchpoint_key_charges_one_extraction_until_429(client, store, keys):
    r = start(client)
    assert r.status_code == 202
    assert wait(client, r.json()["id"])["status"] == "done"
    assert keys == ["sk-ant-branchpoint"]
    assert store.team_used(ALICE) == {"messages": 0, "extractions": 1}
    assert start(client).status_code == 202
    r = start(client)
    assert r.status_code == 429 and r.json()["error"]["code"] == "team_extract_quota"
    assert len(keys) == 2  # el tercero no se encoló
    assert store.team_used(ALICE)["extractions"] == 2


def test_selected_personal_key_is_used_and_not_charged(client, store, keys):
    store.save_credential(ALICE, "anthropic", "sk-ant-alice")
    store.select_chat_key(ALICE, "anthropic", True)
    r = start(client)
    assert r.status_code == 202 and wait(client, r.json()["id"])["status"] == "done"
    assert keys == ["sk-ant-alice"]
    assert store.team_used(ALICE)["extractions"] == 0


def test_header_key_wins_over_everything(client, store, keys):
    store.save_credential(ALICE, "anthropic", "sk-ant-alice")
    store.select_chat_key(ALICE, "anthropic", True)
    r = client.post(
        "/github/ingestions", json={"repo_full_name": "acme/tienda"}, headers={"X-Anthropic-Api-Key": "sk-header"}
    )
    assert r.status_code == 202
    assert keys == ["sk-header"]


def test_without_any_credential_is_422_with_mcp_hint(client, store, keys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    r = start(client)
    assert r.status_code == 422
    message = r.json()["error"]["message"]
    assert "Configuración" in message and "MCP" in message
    assert keys == []


def test_openai_without_keys_is_422(client, keys):
    r = start(client, provider="openai")
    assert r.status_code == 422 and "OpenAI" in r.json()["error"]["message"]
    assert keys == []
