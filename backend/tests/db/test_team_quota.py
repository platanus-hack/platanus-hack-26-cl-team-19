"""IA-2 (JAJ-114): cuota de la key de Branchpoint por propósito y elección de la key (``llm_key``)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import psycopg
import pytest
from fastapi import Response

from app.api.auth import User
from app.api.errors import ApiError
from app.api.routes.credentials import LlmKey, chat_settings, llm_key, select_chat_key

ALICE = str(uuid.UUID(int=0xA11CE))
BOB = str(uuid.UUID(int=0xB0B))


@pytest.fixture
def store(database_url, clean_pg_store):
    with psycopg.connect(database_url) as conn:
        for uid in (ALICE, BOB):
            conn.execute(
                "insert into auth.users (id, aud, role, email) values (%s, 'authenticated', 'authenticated', %s)"
                " on conflict (id) do nothing",
                (uid, f"{uid[-4:]}@example.com"),
            )
        conn.execute("truncate team_chat_usage, llm_credentials")
    return clean_pg_store


@pytest.fixture(autouse=True)
def _team_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-branchpoint")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BRANCHPOINT_TEAM_CHAT_LIMIT", raising=False)
    monkeypatch.delenv("BRANCHPOINT_TEAM_EXTRACT_LIMIT", raising=False)


def req(store):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(store=store)))


def key(store, user=ALICE, provider="anthropic", purpose="chat", **kw) -> LlmKey:
    return llm_key(req(store), User(user), provider, kw.pop("header", None), None, purpose=purpose, **kw)


def test_third_extraction_over_the_limit_is_429(store, monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_TEAM_EXTRACT_LIMIT", "2")
    assert key(store, purpose="extract") == LlmKey("sk-ant-branchpoint", "team")
    assert key(store, purpose="extract").source == "team"
    with pytest.raises(ApiError) as e:
        key(store, purpose="extract")
    assert e.value.status == 429 and e.value.code == "team_extract_quota"
    assert "propia API key" in e.value.message
    assert store.team_used(ALICE) == {"messages": 0, "extractions": 2}


def test_chat_and_extract_quotas_are_independent(store, monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_TEAM_CHAT_LIMIT", "1")
    monkeypatch.setenv("BRANCHPOINT_TEAM_EXTRACT_LIMIT", "1")
    key(store, purpose="chat")
    with pytest.raises(ApiError) as e:
        key(store, purpose="chat")
    assert e.value.code == "team_chat_quota"
    assert key(store, purpose="extract").source == "team"  # la de chat se acabó, la de extracción no
    assert store.team_used(ALICE) == {"messages": 1, "extractions": 1}
    assert store.team_used(BOB) == {"messages": 0, "extractions": 0}


def test_selected_personal_key_is_not_charged(store):
    store.save_credential(ALICE, "anthropic", "sk-ant-alice")
    assert key(store).source == "team"  # guardada, pero sin elegir: sigue la de Branchpoint
    store.select_chat_key(ALICE, "anthropic", True)
    assert key(store, purpose="extract") == LlmKey("sk-ant-alice", "personal")
    assert key(store) == LlmKey("sk-ant-alice", "personal")
    assert store.team_used(ALICE) == {"messages": 1, "extractions": 0}


def test_header_key_wins_and_is_not_charged(store):
    assert key(store, header=" sk-header ", purpose="extract") == LlmKey("sk-header", "header")
    assert store.team_used(ALICE)["extractions"] == 0


def test_charge_team_takes_all_units_or_none(store):
    assert store.charge_team(ALICE, "extract", 5, n=2)
    assert store.team_used(ALICE)["extractions"] == 2
    assert not store.charge_team(ALICE, "extract", 5, n=4)  # 2 + 4 > 5: no descuenta nada
    assert store.team_used(ALICE)["extractions"] == 2
    assert store.charge_team(ALICE, "extract", 5, n=3)
    assert not store.charge_team(BOB, "extract", 1, n=2)  # sin fila previa tampoco pasa el límite
    assert store.team_used(BOB) == {"messages": 0, "extractions": 0}


def test_llm_key_charges_several_units(store, monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_TEAM_EXTRACT_LIMIT", "1")
    with pytest.raises(ApiError) as e:
        key(store, purpose="extract", units=2)
    assert e.value.code == "team_extract_quota"
    assert store.team_used(ALICE)["extractions"] == 0


def test_openai_without_branchpoint_key_is_422(store):
    with pytest.raises(ApiError) as e:
        key(store, provider="openai")
    assert e.value.status == 422
    with pytest.raises(ApiError) as e:
        select_chat_key("openai", SimpleNamespace(source="team"), req(store), User(ALICE))
    assert e.value.status == 422 and "OpenAI" in e.value.message


def test_openai_personal_key_is_used_when_branchpoint_has_none(store):
    store.save_credential(ALICE, "openai", "sk-openai-alice")
    assert key(store, provider="openai") == LlmKey("sk-openai-alice", "personal")


def test_openai_branchpoint_key_with_quota(store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-branchpoint")
    assert key(store, provider="openai", purpose="extract") == LlmKey("sk-openai-branchpoint", "team")
    store.save_credential(ALICE, "openai", "sk-openai-alice")  # guardarla la deja elegida
    assert key(store, provider="openai").source == "personal"
    select_chat_key("openai", SimpleNamespace(source="team"), req(store), User(ALICE))
    assert key(store, provider="openai").source == "team"


def test_chat_settings_reports_extract_quota(store, monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_TEAM_EXTRACT_LIMIT", "3")
    key(store, purpose="extract")
    key(store)
    settings = chat_settings(req(store), Response(), User(ALICE))
    assert settings["extract"] == {"remaining": 2, "limit": 3}
    assert settings["remaining"] == 29 and settings["limit"] == 30
    assert settings["team"] == ["anthropic"]


def test_llm_key_repr_hides_the_key():
    assert "sk-" not in repr(LlmKey("sk-secret", "team"))
