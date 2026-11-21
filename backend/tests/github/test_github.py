"""Conectar un repo con la GitHub App y analizarlo como v1 (JAJ-57), con GitHub falso."""

from __future__ import annotations

import io
import json
import tarfile
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from app.agent.loop import Turn
from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.github.client import GitHubApp, GitHubAppConfig, GitHubError, Repo
from app.github.ingestion import extract_tarball
from app.github.state import InvalidState, sign_state, verify_state

SECRET = "client-secret-de-prueba"
TOKEN = "ghs_token_que_nunca_debe_salir"
SHA = "06ff98cfa9b925e35b866e5abdf9e792006a36bb"

APP = b"""const express = require('express')
const app = express()
app.get('/items', async (req, res) => res.json(await db.item.findMany({ take: 20 })))
app.post('/items', async (req, res) => res.json(await db.item.create({ data: req.body })))
app.listen(3000)
"""
KEY = "sk-ant-key-de-prueba-que-nunca-debe-salir"


class FakeAnalyst:
    """Hace de Claude en la ingesta: busca rutas con grep y, según lo que encuentra, entrega la arquitectura
    o avisa que no hay endpoints. Como el analizador real, solo ve el repo por sus tools."""

    model = "claude-opus-5-5"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system, messages, tools):
        self.calls += 1
        last = messages[-1]["content"]
        if isinstance(last, str):  # primera vuelta: el árbol del repo
            return Turn([{"type": "tool_use", "id": "t1", "name": "grep", "input": {"pattern": r"app\.(get|post)"}}],
                        "tool_use", {"input": 2000, "output": 100})  # fmt: skip
        hits = json.loads(last[0]["content"])["hits"]
        if not hits:
            call = {"type": "tool_use", "id": "t2", "name": "report_no_endpoints", "input": {"reason": "sin rutas"}}
            return Turn([call], "tool_use", {"input": 2000, "output": 50})
        endpoints = []
        for hit in hits:
            file, line, code = hit.split(":", 2)
            method = "GET" if ".get(" in code else "POST"
            op, shape = ("read", "range") if method == "GET" else ("write", "commit")
            step = {"kind": "db", "op": op, "shape": shape, "entity": "Item", "detail": "db.item",
                    "file": file, "line": int(line), "why": "Prisma"}  # fmt: skip
            endpoints.append({"method": method, "path": "/items", "handler": f"items_{method.lower()}",
                              "file": file, "line": int(line), "why": "ruta de express", "is_async": True,
                              "effects": [step]})  # fmt: skip
        arch = {"framework": "express", "language": "javascript", "endpoints": endpoints}
        return Turn([{"type": "tool_use", "id": "t2", "name": "submit_architecture", "input": arch}], "tool_use",
                    {"input": 3000, "output": 400})  # fmt: skip


def tarball(files: dict[str, bytes], root: str = f"acme-tienda-{SHA[:7]}") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(f"{root}/{name}" if root else name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeGitHub(GitHubApp):
    """Responde como GitHub según lo que se configure. Registra qué se pidió."""

    def __init__(self) -> None:
        super().__init__(GitHubAppConfig("1", "branchpoint-test", "Iv1.test", SECRET, "sin-key"))
        self.user_installations_seen = {42: "alice-gh"}  # lo que ve el usuario dueño del code "ok"
        self.repos = {42: [Repo(7, "acme/tienda", True, "main", 42)]}
        self.tarballs = {"acme/tienda": tarball({"src/app.js": APP})}
        self.fetched: list[tuple[int, str, str]] = []
        self.exchanged_with: list[str | None] = []  # redirect_uri de cada canje de code

    def installation_token(self, installation_id: int, repo_name: str | None = None) -> str:
        return TOKEN

    def user_installations(self, code: str, redirect_uri: str | None = None) -> dict[int, str]:
        self.exchanged_with.append(redirect_uri)
        if code != "ok":
            raise GitHubError(401, "GitHub rechazó la autorización (el código venció o ya se usó). Vuelve a conectar.")
        return dict(self.user_installations_seen)

    def list_repos(self, installation_id: int) -> list[Repo]:
        if installation_id not in self.repos:
            raise GitHubError(404, "La instalación de la GitHub App ya no existe.")
        return self.repos[installation_id]

    def list_branches(self, installation_id: int, full_name: str) -> list[str]:
        return ["feature-x", "main", "Dev"]

    def fetch(self, installation_id: int, full_name: str, ref: str) -> tuple[str, bytes]:
        self.fetched.append((installation_id, full_name, ref))
        return SHA, self.tarballs[full_name]


@pytest.fixture
def github():
    return FakeGitHub()


@pytest.fixture
def store():
    return InMemoryProjectStore()


@pytest.fixture
def keys():
    return []  # las keys de Anthropic que llegaron a la fábrica del LLM


@pytest.fixture
def client(github, store, keys, monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_FRONTEND_URL", "http://front.test")
    app = create_app(store=store, auth=None, github_app=github)
    app.state.llm_factory = lambda key: keys.append(key) or FakeAnalyst()
    return TestClient(app, follow_redirects=False, headers={"X-Anthropic-Api-Key": KEY})


def connect(client) -> None:
    """Hace el flujo de instalación completo: pide la URL y vuelve de GitHub con su state."""
    url = client.get("/github/install-url").json()["url"]
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
    r = client.get("/github/callback", params={"installation_id": 42, "code": "ok", "state": state})
    assert r.status_code == 302 and "github=ok" in r.headers["location"]


def redirect_params(r) -> dict[str, str]:
    loc = urllib.parse.urlparse(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == "http://front.test/onboarding"
    return {k: v[0] for k, v in urllib.parse.parse_qs(loc.query).items()}


# ---------- state ----------


def test_state_round_trip_and_rejects_tampering():
    state = sign_state(SECRET, "user-1")
    assert verify_state(SECRET, state) == "user-1"
    payload, sig = state.split(".")
    with pytest.raises(InvalidState):
        verify_state("otro-secreto", state)
    with pytest.raises(InvalidState):
        verify_state(SECRET, sign_state(SECRET, "intruso").split(".")[0] + "." + sig)


def test_state_expires():
    old = sign_state(SECRET, None, now=time.time() - 3600)
    with pytest.raises(InvalidState, match="venció"):
        verify_state(SECRET, old)


# ---------- instalar ----------


def test_install_url_points_to_the_app(client):
    url = client.get("/github/install-url").json()["url"]
    assert url.startswith("https://github.com/apps/branchpoint-test/installations/new?state=")


def test_callback_saves_the_installation_for_the_state_user(client, store):
    assert client.get("/github/installations").json() == []
    connect(client)
    assert client.get("/github/installations").json() == [{"installation_id": 42, "account_login": "alice-gh"}]


def test_callback_rejects_a_forged_state(client):
    r = client.get("/github/callback", params={"installation_id": 42, "code": "ok", "state": "x.y"})
    params = redirect_params(r)
    assert params["github"] == "error" and "no es válido" in params["message"]
    assert client.get("/github/installations").json() == []


def test_callback_rejects_an_installation_of_someone_else(client):
    state = sign_state(SECRET, None)
    r = client.get("/github/callback", params={"installation_id": 99, "code": "ok", "state": state})
    assert "no es de tu cuenta" in redirect_params(r)["message"]
    assert client.get("/github/installations").json() == []


def test_authorize_saves_every_installation_the_user_sees(client, github):
    """Ya tenía la app instalada: OAuth sin instalar vuelve sin installation_id y se guardan todas."""
    github.user_installations_seen = {42: "alice-gh", 43: "acme"}
    url = client.get("/github/authorize-url").json()["url"]
    assert url.startswith("https://github.com/login/oauth/authorize?client_id=Iv1.test&state=")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
    r = client.get("/github/callback", params={"code": "ok", "state": state})
    assert redirect_params(r)["github"] == "ok"
    assert {i["installation_id"] for i in client.get("/github/installations").json()} == {42, 43}


def test_authorize_url_sends_this_backends_callback_as_redirect_uri(client, github):
    """Con redirect_uri, producción y local usan la misma app: cada una vuelve a su backend (JAJ-84)."""
    url = client.get("/github/authorize-url").json()["url"]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["redirect_uri"] == ["http://testserver/github/callback"]
    client.get("/github/callback", params={"code": "ok", "state": query["state"][0]})
    assert github.exchanged_with == ["http://testserver/github/callback"]  # el mismo en el canje


def test_redirect_uri_comes_from_branchpoint_api_url(client, github, monkeypatch):
    """Detrás del proxy de Render el request llega por http: la URL pública sale de la variable."""
    monkeypatch.setenv("BRANCHPOINT_API_URL", "https://api.example.com/")
    url = client.get("/github/authorize-url").json()["url"]
    assert urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["redirect_uri"] == [
        "https://api.example.com/github/callback"
    ]
    client.get("/github/callback", params={"code": "ok", "state": sign_state(SECRET, None)})
    assert github.exchanged_with == ["https://api.example.com/github/callback"]


def test_install_callback_exchanges_without_redirect_uri(client, github):
    """Si la app sigue con OAuth durante la instalación, GitHub no recibió redirect_uri: el canje tampoco."""
    connect(client)
    assert github.exchanged_with == [None]


def test_authorize_without_the_app_installed(client, github):
    github.user_installations_seen = {}
    r = client.get("/github/callback", params={"code": "ok", "state": sign_state(SECRET, None)})
    assert "No encontramos la GitHub App instalada" in redirect_params(r)["message"]


def test_callback_with_an_expired_code(client):
    r = client.get("/github/callback", params={"code": "viejo", "state": sign_state(SECRET, None)})
    assert "venció o ya se usó" in redirect_params(r)["message"]


def test_callback_when_the_user_cancels(client):
    r = client.get("/github/callback", params={"state": sign_state(SECRET, None)})
    assert "se canceló" in redirect_params(r)["message"]


def test_github_routes_answer_503_without_config(store):
    client = TestClient(create_app(store=store, auth=None, github_app=None))
    r = client.get("/github/repos")
    assert r.status_code == 503 and r.json()["error"]["code"] == "github_not_configured"


# ---------- repos y ramas ----------


def test_repos_and_branches(client):
    assert client.get("/github/repos").json() == []  # sin instalaciones todavía
    connect(client)
    assert client.get("/github/repos").json() == [
        {"id": 7, "full_name": "acme/tienda", "private": True, "default_branch": "main", "installation_id": 42}
    ]
    assert client.get("/github/repos/acme/tienda/branches").json() == ["main", "Dev", "feature-x"]


def test_uninstalled_app_stops_being_listed(client, github, store):
    connect(client)
    github.repos.pop(42)  # la desinstalaron desde GitHub
    assert client.get("/github/repos").json() == []
    assert store.list_installations(None) == []


def test_branches_of_a_repo_without_access_is_404(client):
    connect(client)
    r = client.get("/github/repos/otra/cosa/branches")
    assert r.status_code == 404 and "no tiene acceso" in r.json()["error"]["message"]


# ---------- ingesta ----------


def test_ingestion_creates_the_project_with_its_v1(client, github, store):
    connect(client)
    r = client.post("/github/ingestions", json={"repo_full_name": "acme/tienda"})
    assert r.status_code == 202
    job = r.json()
    assert job["branch"] == "main"  # la rama por defecto
    # TestClient corre la tarea en segundo plano antes de devolver la respuesta
    done = client.get(f"/github/ingestions/{job['id']}").json()
    assert done["status"] == "done" and done["version"] == 1 and done["commit_sha"] == SHA
    assert done["endpoints"] == 2 and done["error_message"] is None, done
    assert github.fetched == [(42, "acme/tienda", "main")]

    project = client.get(f"/projects/{done['project_id']}").json()
    assert project["name"] == "tienda"
    v1 = client.get(f"/projects/{done['project_id']}/versions/1").json()
    assert v1["model"]["repo"]["source"]["via"] == "ingesta" and v1["model"]["repo"]["source"]["commit"] == SHA
    assert v1["model"]["endpoints"][0]["at"] == "src/app.js:3"  # archivo:línea relativo al repo
    assert v1["origin"] == "repo" and v1["note"] == "Extraída de acme/tienda@main (06ff98c)"
    model = v1["model"]
    assert model["repo"]["path"] == "acme/tienda"
    assert {(e["method"], e["path"]) for e in model["endpoints"]} == {("GET", "/items"), ("POST", "/items")}
    # sin respuestas del usuario: el tráfico es un supuesto por revisar (JAJ-59 lo pide después)
    assert model["traffic"]["mau"]["label"] == "SUPUESTO" and model["traffic"]["mau"]["needs_review"]

    source = store.sources[done["project_id"]]
    assert (source.repo_full_name, source.branch, source.commit_sha) == ("acme/tienda", "main", SHA)


def test_ingestion_of_another_branch_and_name(client, github):
    connect(client)
    job = client.post(
        "/github/ingestions", json={"repo_full_name": "acme/tienda", "branch": "feature-x", "name": "Tienda (feature)"}
    ).json()
    done = client.get(f"/github/ingestions/{job['id']}").json()
    assert github.fetched == [(42, "acme/tienda", "feature-x")]
    assert client.get(f"/projects/{done['project_id']}").json()["name"] == "Tienda (feature)"


def test_ingestion_without_endpoints_fails_in_spanish(client, github):
    connect(client)
    github.tarballs["acme/tienda"] = tarball({"README.md": b"# nada"})
    job = client.post("/github/ingestions", json={"repo_full_name": "acme/tienda"}).json()
    failed = client.get(f"/github/ingestions/{job['id']}").json()
    assert failed["status"] == "failed" and "No encontramos endpoints" in failed["error_message"]
    assert failed["project_id"] is None
    assert client.get("/projects").json() == []  # no queda un proyecto a medias


def test_ingestion_when_github_revokes_access_midway(client, github):
    connect(client)

    def revoked(*_):
        raise GitHubError(404, "La instalación de la GitHub App ya no existe: la desinstalaron o se revocó el acceso.")

    github.fetch = revoked
    job = client.post("/github/ingestions", json={"repo_full_name": "acme/tienda"}).json()
    failed = client.get(f"/github/ingestions/{job['id']}").json()
    assert failed["status"] == "failed" and "se revocó" in failed["error_message"]


def test_ingestion_of_a_repo_without_access_is_404(client):
    connect(client)
    r = client.post("/github/ingestions", json={"repo_full_name": "otra/cosa"})
    assert r.status_code == 404


def test_ingestion_rejects_a_bad_repo_name(client):
    r = client.post("/github/ingestions", json={"repo_full_name": "../etc/passwd"})
    assert r.status_code == 422


def test_unknown_ingestion_is_404(client):
    assert client.get("/github/ingestions/nope").status_code == 404


def test_the_token_never_reaches_a_response(client):
    connect(client)
    bodies = [client.get("/github/repos").text, client.get("/github/repos/acme/tienda/branches").text]
    job = client.post("/github/ingestions", json={"repo_full_name": "acme/tienda"}).json()
    bodies.append(client.get(f"/github/ingestions/{job['id']}").text)
    bodies.append(client.get(f"/projects/{job['id']}").text)
    assert all(TOKEN not in b and KEY not in b for b in bodies)


def test_ingestion_uses_the_users_key_or_the_demo(client, keys, monkeypatch):
    connect(client)
    client.post("/github/ingestions", json={"repo_full_name": "acme/tienda"})
    assert keys == [KEY]
    del client.headers["X-Anthropic-Api-Key"]
    r = client.post("/github/ingestions", json={"repo_full_name": "acme/tienda"})
    assert r.status_code == 422 and "API key de Anthropic" in r.json()["error"]["message"]
    monkeypatch.setenv("BRANCHPOINT_CHAT_DEMO", "on")
    for _ in range(5):
        assert client.post("/github/ingestions", json={"repo_full_name": "acme/tienda"}).status_code == 202
    assert client.post("/github/ingestions", json={"repo_full_name": "acme/tienda"}).status_code == 429
    assert keys[1:] == [None] * 5  # demo: la credencial del equipo


# ---------- extracción segura ----------


def test_extract_tarball_blocks_path_traversal(tmp_path):
    evil = tarball({"../../escapado.py": b"x = 1"}, root="")
    with pytest.raises(tarfile.OutsideDestinationError):
        extract_tarball(evil, tmp_path / "dest")
    assert not (tmp_path / "escapado.py").exists()


def test_onboarding_connection_reports_revocation_and_recovery(client, github):
    """JAJ-91: si desinstalan la app desde GitHub, el onboarding sabe por qué no hay repos."""
    assert client.get("/github/connection").json() == {"repos": [], "installations": [], "revoked": False}
    connect(client)
    github.repos.pop(42)

    revoked = client.get("/github/connection")
    assert revoked.status_code == 200
    assert revoked.json() == {"repos": [], "installations": [], "revoked": True}
    assert client.get("/github/connection").json()["revoked"] is True

    github.repos[42] = [Repo(7, "acme/tienda", True, "main", 42)]
    connect(client)
    restored = client.get("/github/connection").json()
    assert restored["revoked"] is False
    assert restored["repos"][0]["full_name"] == "acme/tienda"
