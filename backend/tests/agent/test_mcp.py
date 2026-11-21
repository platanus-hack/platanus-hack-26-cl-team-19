"""El servidor MCP montado en la API (JAJ-67), por HTTP como lo usa la CLI del usuario.

Reemplaza a ``spikes/jaj-54-byos/check_client.py``: mismas comprobaciones, ahora en CI.
"""

import json
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.auth import SupabaseAuth
from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.samples import load_sample

H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
SUPABASE = "https://demo.supabase.co"
SECRET = "test-secret-de-al-menos-32-caracteres!!"
ALICE, BOB = str(uuid.uuid4()), str(uuid.uuid4())


def token(sub: str) -> str:
    claims = {"sub": sub, "aud": "authenticated", "iss": f"{SUPABASE}/auth/v1", "exp": int(time.time()) + 600}
    return jwt.encode(claims, SECRET, algorithm="HS256")


def rpc(client, method, params=None, headers=None):
    r = client.post(
        "/mcp",
        headers={**H, **(headers or {})},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    return r


def tool(client, name, args, headers=None):
    r = rpc(client, "tools/call", {"name": name, "arguments": args}, headers)
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    data = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    # MCP envuelve las respuestas que son listas (list_projects) en {"result": [...]}
    return data["result"] if isinstance(data, dict) and set(data) == {"result"} else data


@pytest.fixture
def open_api():
    store = InMemoryProjectStore()
    project = store.create("tienda", load_sample("full-stack-fastapi-template"), None)
    with TestClient(create_app(store=store, auth=None, github_app=None)) as client:
        yield client, project


def test_tools_list_and_instructions(open_api):
    client, _ = open_api
    init = rpc(
        client,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    )
    assert "Nunca inventes" in init.json()["result"]["instructions"]
    names = [t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]]
    assert len(names) == 13 and {"simulate", "propose_version", "set_goals", "submit_architecture"} <= set(names)
    assert "submit_architecture" in init.json()["result"]["instructions"]


def test_simulate_and_propose_by_mcp(open_api):
    client, project = open_api
    sim = tool(client, "simulate", {"project_id": project.id, "scenario": "cyberday"})
    assert sim["bottleneck"]["line"] == "backend/app/core/security.py:36"
    assert sim["provenance"]["label"] == "SUPUESTO"
    v = tool(client, "propose_version", {"project_id": project.id, "ops": [{"op": "scale_api", "replicas": 4}]})
    assert v["version"] == 2
    c = tool(client, "compare", {"project_id": project.id, "a": 1, "b": 2})
    assert c["delta"]["p95_ms"]["b"] < c["delta"]["p95_ms"]["a"]


def test_invented_numbers_and_unknown_args_are_errors(open_api):
    client, project = open_api
    assert "rps" in tool(client, "simulate", {"project_id": project.id, "rps": 5000})["error"]
    assert "Extra inputs" in tool(client, "list_projects", {"limit": 3})["error"]
    err = tool(client, "set_goals", {"project_id": project.id, "slo_p95_ms": 250, "quote": "p95 bajo 300 ms"})["error"]
    assert "no aparece en quote" in err


def test_login_isolates_users():
    store = InMemoryProjectStore()
    alice_project = store.create("de alice", load_sample("full-stack-fastapi-template"), None, owner=ALICE)
    store.create("de bob", load_sample("fastapi-realworld-example-app"), None, owner=BOB)
    app = create_app(store=store, auth=SupabaseAuth(SUPABASE, jwt_secret=SECRET), github_app=None)
    with TestClient(app) as client:
        assert rpc(client, "tools/list").status_code == 401  # sin token, antes de MCP
        assert rpc(client, "tools/list", headers={"Authorization": "Bearer roto"}).status_code == 401
        alice = {"Authorization": f"Bearer {token(ALICE)}"}
        bob = {"Authorization": f"Bearer {token(BOB)}"}
        assert [p["name"] for p in tool(client, "list_projects", {}, alice)["projects"]] == ["de alice"]
        assert [p["name"] for p in tool(client, "list_projects", {}, bob)["projects"]] == ["de bob"]
        assert "No existe el proyecto" in tool(client, "simulate", {"project_id": alice_project.id}, bob)["error"]
        assert client.get("/health").status_code == 200  # el resto de la API no pasa por la puerta de MCP


def test_submit_architecture_by_mcp(open_api):
    from tests.ingest.test_ai_graph import EXPRESS

    client, _ = open_api
    schema = next(t for t in rpc(client, "tools/list").json()["result"]["tools"] if t["name"] == "submit_architecture")
    assert "endpoints" in schema["inputSchema"]["required"]  # la CLI ve la forma de cada endpoint y paso
    out = tool(client, "submit_architecture", EXPRESS)
    assert out["version"] == 1 and out["components_from_ai"] == 3, out
    sim = tool(client, "simulate", {"project_id": out["project_id"], "scenario": "pico_normal"})
    assert "error" not in sim, sim
    bad = {**EXPRESS, "endpoints": [{**EXPRESS["endpoints"][0], "latency_ms": 40}]}
    assert "Extra inputs" in tool(client, "submit_architecture", bad)["error"]
