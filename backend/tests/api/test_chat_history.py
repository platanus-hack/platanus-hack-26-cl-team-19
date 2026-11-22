"""La conversación del chat se guarda por proyecto: al volver al editor, sigue ahí."""

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.store import InMemoryProjectStore

SAMPLE = "full-stack-fastapi-template"
MESSAGES = [
    {"id": "u1", "role": "user", "text": "Cambia CyberDay a 42 req/s"},
    {"id": "t1:a", "role": "tool", "name": "simulate", "input": "{}", "status": "done", "output": "p95 7 ms"},
    {
        "id": "p1",
        "role": "chat-proposal",
        "proposal": {"id": "p1", "changes": ["x"]},
        "state": "applied",
        "version": "v2",
    },
    {"id": "a1", "role": "agent", "text": "Listo."},
]


def _client():
    client = TestClient(create_app(store=InMemoryProjectStore(), auth=None))
    return client, client.post("/projects", json={"sample": SAMPLE}).json()["id"]


def test_new_project_has_an_empty_chat():
    client, pid = _client()
    assert client.get(f"/projects/{pid}/chat").json() == {"messages": []}


def test_saved_chat_comes_back_in_order_and_whole():
    client, pid = _client()
    assert client.put(f"/projects/{pid}/chat", json={"messages": MESSAGES}).status_code == 204
    assert client.get(f"/projects/{pid}/chat").json()["messages"] == MESSAGES


def test_saving_replaces_and_empty_clears():
    client, pid = _client()
    client.put(f"/projects/{pid}/chat", json={"messages": MESSAGES})
    client.put(f"/projects/{pid}/chat", json={"messages": MESSAGES[:1]})
    assert client.get(f"/projects/{pid}/chat").json()["messages"] == MESSAGES[:1]
    client.put(f"/projects/{pid}/chat", json={"messages": []})
    assert client.get(f"/projects/{pid}/chat").json()["messages"] == []


def test_unknown_project_or_bad_role_is_rejected():
    client, pid = _client()
    assert client.get("/projects/no-existe/chat").status_code == 404
    assert client.put("/projects/no-existe/chat", json={"messages": []}).status_code == 404
    bad = {"messages": [{"id": "x", "role": "system", "text": "hola"}]}
    assert client.put(f"/projects/{pid}/chat", json=bad).status_code == 422


def test_too_long_conversation_is_422():
    client, pid = _client()
    huge = [{"id": str(i), "role": "agent", "text": "x" * 20_000} for i in range(120)]
    r = client.put(f"/projects/{pid}/chat", json={"messages": huge})
    assert r.status_code == 422 and "demasiado larga" in r.json()["error"]["message"]
