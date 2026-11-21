"""IA-7 (JAJ-118): chat con adjuntos, análisis determinista de logs y evidencia que falta."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agent.logs import analyze_log
from app.agent.loop import Turn
from app.agent.tools import ATTACHMENT_TOOLS, AgentTools, pending_evidence
from app.api.auth import AuthError, User
from app.api.main import create_app
from app.api.store import Attachment, InMemoryProjectStore
from app.samples import load_sample
from app.storage import InMemoryAttachmentStorage

ALICE = str(uuid.UUID(int=0xA11CE))
BOB = str(uuid.UUID(int=0xB0B))
PNG = b"\x89PNG\r\n\x1a\n" + b"1" * 64
ENDPOINTS = [e["id"] for e in load_sample("full-stack-fastapi-template")["endpoints"]]


def nginx_log() -> bytes:
    """200 líneas: 120 en el minuto 0, 60 en el 1 y 20 en el 2 (/metrics, que no está en el modelo)."""
    rows = []

    def add(minute, second, method, path, status=200):
        t = f"21/Nov/2026:10:{minute:02d}:{second:02d} +0000"
        rows.append(f'10.0.0.1 - - [{t}] "{method} {path} HTTP/1.1" {status} 512 "-" "k6/0.50"')

    for i in range(60):
        add(0, i % 60, "GET", "/items/?skip=0&limit=20")
    for i in range(40):
        add(0, i % 60, "GET", f"/items/{i + 1}", 500 if i < 6 else 200)
    for i in range(20):
        add(0, i % 60, "POST", "/login/access-token")
    for i in range(30):
        add(1, i, "GET", "/items/")
    for i in range(30):
        add(1, 30 + i, "GET", "/users/me")
    for i in range(20):
        add(2, i, "GET", "/metrics")
    return ("\n".join(rows) + "\n").encode()


# ---------- analyze_log ----------


def test_nginx_log_numbers_are_exact():
    out = analyze_log(nginx_log(), "access.log", ENDPOINTS)
    assert out["format"] == "combined" and out["lines"] == 200 and out["parsed"] == 200
    assert out["peak_rps"]["value"] == 2.0 and out["peak_rps"]["label"] == "OBSERVADO"
    assert "access.log, líneas 1–200" in out["peak_rps"]["source"]
    assert out["error_rate"]["value"] == 0.03
    weights = {e["id"]: e["weight"] for e in out["endpoints"]}
    assert weights == {
        "GET /items/": 0.5,
        "GET /items/{id}": 0.2222,
        "GET /users/me": 0.1667,
        "POST /login/access-token": 0.1111,
    }
    assert out["unmatched_paths"] == [{"path": "GET /metrics", "requests": 20}]
    assert "latency_p95_ms" not in out  # el combined no trae duración: no se estima


def test_json_lines_with_duration_have_p95():
    rows = [
        json.dumps(
            {
                "timestamp": f"2026-11-21T10:00:{i:02d}Z",
                "method": "GET",
                "path": "/items/",
                "status": 200,
                "duration_ms": float(i + 1),
            }
        )  # fmt: skip
        for i in range(20)
    ]
    out = analyze_log("\n".join(rows).encode(), "app.ndjson", ENDPOINTS)
    assert out["format"] == "json"
    assert out["latency_p95_ms"]["value"] == 19.0
    assert out["endpoints"][0]["p95_ms"] == 19.0
    no_duration = [
        json.dumps({"time": 1795284000 + i, "method": "GET", "url": "/items/", "status_code": 200}) for i in range(5)
    ]
    out = analyze_log("\n".join(no_duration).encode(), "app.ndjson", ENDPOINTS)
    assert "latency_p95_ms" not in out and out["peak_rps"]["value"] == pytest.approx(5 / 60, abs=0.01)


def test_uvicorn_lines_with_timestamp():
    rows = [f'2026-11-21 10:00:{i:02d},000 INFO: 127.0.0.1:5 - "GET /users/me HTTP/1.1" 200 OK' for i in range(10)]
    out = analyze_log("\n".join(rows).encode(), "uvicorn.log", ENDPOINTS)
    assert out["format"] == "uvicorn" and out["endpoints"][0]["id"] == "GET /users/me"


def test_free_text_is_an_error_with_a_sample():
    out = analyze_log(b"arranco el servidor\nconexion lista\nhola\nchao\n", "notas.txt", ENDPOINTS)
    assert "No reconocí el formato" in out["error"]
    assert out["sample"] == ["arranco el servidor", "conexion lista", "hola"]


# ---------- tools y chat ----------


class FakeAuth:
    def verify(self, token: str) -> User:
        try:
            return User(str(uuid.UUID(token)))
        except ValueError:
            raise AuthError("token inválido") from None


class FakeLLM:
    model = "claude-opus-5-5"

    def __init__(self, turns):
        self.turns, self.seen = list(turns), []

    def complete(self, system, messages, tools):
        self.seen.append({"messages": json.loads(json.dumps(messages)), "tools": [t["name"] for t in tools]})
        content, stop = self.turns.pop(0)
        return Turn(content, stop, {"input": 10, "output": 5})


@pytest.fixture
def store():
    return InMemoryProjectStore()


@pytest.fixture
def storage():
    return InMemoryAttachmentStorage()


@pytest.fixture
def project(store):
    return store.create("tienda", load_sample("full-stack-fastapi-template"), None, ALICE)


def attach(store, storage, project_id, kind, data, filename, media_type, owner=ALICE, status="ready", ttl=1):
    aid = str(uuid.uuid4())
    path = f"{owner}/{project_id}/{aid}/{filename}"
    now = datetime.now(UTC)
    store.create_attachment(
        Attachment(
            aid, owner, project_id, kind, filename, media_type, len(data), path, status, now, now + timedelta(hours=ttl)
        )  # fmt: skip
    )
    storage.put(path, data, media_type)
    return aid


def chat_app(store, storage, llm):
    app = create_app(store=store, auth=FakeAuth(), github_app=None, attachment_storage=storage)
    app.state.llm_factory = lambda key, model=None: llm
    return TestClient(app, headers={"Authorization": f"Bearer {ALICE}", "X-Anthropic-Api-Key": "sk-test"})


def events(r):
    assert r.status_code == 200, r.text
    return [json.loads(line) for line in r.text.splitlines()]


def test_image_goes_as_image_block_then_is_not_resent(store, storage, project):
    img = attach(store, storage, project.id, "image", PNG, "grafana.png", "image/png")
    llm = FakeLLM([([{"type": "text", "text": "Veo 40 req/s, ¿lo confirmas?"}], "end_turn")] * 2)
    client = chat_app(store, storage, llm)
    msg = {"role": "user", "content": "Mira el panel", "attachments": [img]}
    events(client.post(f"/projects/{project.id}/chat", json={"messages": [msg]}))
    last = llm.seen[0]["messages"][-1]["content"]
    assert last[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(PNG).decode()},
    }
    assert last[1]["type"] == "text" and "Mira el panel" in last[1]["text"]
    history = [msg, {"role": "assistant", "content": "Veo 40 req/s, ¿lo confirmas?"}, {"role": "user", "content": "sí"}]
    events(client.post(f"/projects/{project.id}/chat", json={"messages": history}))
    first = llm.seen[1]["messages"][0]["content"]
    assert isinstance(first, str) and "[Imagen adjunta antes: grafana.png]" in first


def test_log_is_announced_by_id_not_sent(store, storage, project):
    log = attach(store, storage, project.id, "log", nginx_log(), "access.log", "text/plain")
    llm = FakeLLM([([{"type": "text", "text": "ok"}], "end_turn")])
    client = chat_app(store, storage, llm)
    events(
        client.post(
            f"/projects/{project.id}/chat",
            json={"messages": [{"role": "user", "content": "mi log", "attachments": [log]}]},
        )
    )
    text = llm.seen[0]["messages"][-1]["content"]
    assert f"[Adjunto de log: access.log, id {log}" in text and "k6/0.50" not in text
    assert set(ATTACHMENT_TOOLS) <= set(llm.seen[0]["tools"])


@pytest.mark.parametrize("case", ["other_user", "expired", "pending", "unknown"])
def test_bad_attachment_in_last_message_is_422(store, storage, project, case):
    if case == "other_user":
        bob_project = store.create("otra", load_sample("full-stack-fastapi-template"), None, BOB)
        aid = attach(store, storage, bob_project.id, "image", PNG, "x.png", "image/png", owner=BOB)
    elif case == "expired":
        aid = attach(store, storage, project.id, "image", PNG, "x.png", "image/png", ttl=-1)
    elif case == "pending":
        aid = attach(store, storage, project.id, "image", PNG, "x.png", "image/png", status="pending")
    else:
        aid = str(uuid.uuid4())
    client = chat_app(store, storage, FakeLLM([]))
    msg = {"role": "user", "content": "mira", "attachments": [aid]}
    r = client.post(f"/projects/{project.id}/chat", json={"messages": [msg]})
    assert r.status_code == 422


def test_attachments_without_session_are_401(store, storage):
    project = store.create("tienda", load_sample("full-stack-fastapi-template"), None)
    app = create_app(store=store, auth=None, github_app=None, attachment_storage=storage)
    client = TestClient(app, headers={"X-Anthropic-Api-Key": "sk-test"})
    msg = {"role": "user", "content": "mira", "attachments": [str(uuid.uuid4())]}
    assert client.post(f"/projects/{project.id}/chat", json={"messages": [msg]}).status_code == 401


def test_assistant_messages_cannot_carry_attachments(store, storage, project):
    client = chat_app(store, storage, FakeLLM([]))
    msgs = [{"role": "assistant", "content": "x", "attachments": ["a"]}, {"role": "user", "content": "y"}]
    assert client.post(f"/projects/{project.id}/chat", json={"messages": msgs}).status_code == 422


def test_apply_log_traffic_makes_an_observed_version(store, storage, project):
    log = attach(store, storage, project.id, "log", nginx_log(), "access.log", "text/plain")
    tools = AgentTools(store, ALICE, attachments=storage)
    r = tools.call("apply_log_traffic", {"project_id": project.id, "attachment_id": log})
    assert "error" not in r, r
    m = store.get_version(project.id, r["version"]).model
    assert m["traffic"]["peak_rps"]["value"] == 2.0 and m["traffic"]["peak_rps"]["label"] == "OBSERVADO"
    weights = {e["id"]: e["weight"] for e in m["endpoints"]}
    assert weights["GET /items/"]["label"] == "OBSERVADO"
    assert sum(w["value"] for w in weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert store.get(project.id, ALICE).versions[-1].note == "Tráfico observado en access.log"
    assert "GET /users/" in r["endpoints_not_in_log"]


def test_log_tools_read_and_grep(store, storage, project):
    log = attach(store, storage, project.id, "log", nginx_log(), "access.log", "text/plain")
    tools = AgentTools(store, ALICE, attachments=storage)
    read = tools.call("read_log", {"project_id": project.id, "attachment_id": log, "start": 199, "lines": 5})
    assert read["total_lines"] == 200 and [line.split(":")[0] for line in read["lines"]] == ["199", "200"]
    grep = tools.call("grep_log", {"project_id": project.id, "attachment_id": log, "pattern": r'" 500 '})
    assert len(grep["matches"]) == 6
    assert "error" in tools.call("grep_log", {"project_id": project.id, "attachment_id": log, "pattern": "("})
    listed = tools.call("list_attachments", {"project_id": project.id})
    assert listed["attachments"][0]["kind"] == "log"
    img = attach(store, storage, project.id, "image", PNG, "x.png", "image/png")
    assert "imagen" in tools.call("read_log", {"project_id": project.id, "attachment_id": img})["error"]


def test_analyze_log_tool_returns_the_summary(store, storage, project):
    log = attach(store, storage, project.id, "log", nginx_log(), "access.log", "text/plain")
    out = AgentTools(store, ALICE, attachments=storage).call(
        "analyze_log", {"project_id": project.id, "attachment_id": log}
    )
    assert out["peak_rps"]["value"] == 2.0


def test_done_evidence_asks_for_traffic_until_the_log_is_applied(store, storage, project):
    log = attach(store, storage, project.id, "log", nginx_log(), "access.log", "text/plain")
    call = {"type": "tool_use", "id": "t1", "name": "apply_log_traffic",
            "input": {"project_id": project.id, "attachment_id": log}}  # fmt: skip
    llm = FakeLLM(
        [
            ([{"type": "text", "text": "Necesito tu log."}], "end_turn"),
            ([call], "tool_use"),
            ([{"type": "text", "text": "Listo."}], "end_turn"),
        ]
    )
    client = chat_app(store, storage, llm)
    done = events(
        client.post(f"/projects/{project.id}/chat", json={"messages": [{"role": "user", "content": "hola"}]})
    )[-1]
    fields = [p["field"] for p in done["evidence"]["pending"]]
    assert "traffic.peak_rps" in fields and done["evidence"]["total_assumptions"] > 0
    msg = {"role": "user", "content": "acá está", "attachments": [log]}
    done = events(client.post(f"/projects/{project.id}/chat", json={"messages": [msg]}))[-1]
    assert "traffic.peak_rps" not in [p["field"] for p in done["evidence"]["pending"]]


def test_pending_evidence_is_at_most_four_asks():
    model = load_sample("full-stack-fastapi-template")
    out = pending_evidence(model)
    assert 1 <= len(out["pending"]) <= 4
    assert all({"field", "ask", "accepts"} <= set(p) for p in out["pending"])


def test_without_storage_the_tools_are_the_same(store):
    names = [t["name"] for t in AgentTools(store, ALICE).schemas()]
    assert not set(ATTACHMENT_TOOLS) & set(names)
    with_storage = [t["name"] for t in AgentTools(store, ALICE, attachments=InMemoryAttachmentStorage()).schemas()]
    assert with_storage == names + list(ATTACHMENT_TOOLS)


def test_expired_log_is_not_readable(store, storage, project):
    log = attach(store, storage, project.id, "log", nginx_log(), "access.log", "text/plain")
    a = store.get_attachment(log, ALICE)
    store._attachments[log] = replace(a, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    out = AgentTools(store, ALICE, attachments=storage).call(
        "analyze_log", {"project_id": project.id, "attachment_id": log}
    )
    assert "venció" in out["error"]
