"""Mis proyectos: importar un repo, guardar v2 y volver a abrirla en otra sesión (JAJ-80).

Recorre el criterio vigente del MVP contra la API, con login de Supabase y GitHub falsos:
una cuenta nueva conecta la GitHub App, importa su repo como v1, simula, guarda una v2,
cierra sesión y, con un token nuevo de la misma cuenta, encuentra el proyecto y su v2.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.auth import SupabaseAuth
from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from tests.api.test_auth import _JWK, ALICE, BOB, SUPABASE, _ensure_users, bearer, token
from tests.github.test_github import KEY, FakeAnalyst, FakeGitHub, connect

RUN = {"scenario": "cyberday", "seed": 1, "duration_s": 5}


@pytest.fixture
def auth():
    return SupabaseAuth(SUPABASE, fetch_jwks=lambda url: {"keys": [_JWK]})


@pytest.fixture(params=["memoria", "postgres"])
def store(request):
    if request.param == "memoria":
        return InMemoryProjectStore()
    store = request.getfixturevalue("clean_pg_store")
    _ensure_users(request.getfixturevalue("database_url"), ALICE, BOB)
    return store


def session(store, auth, github, user: str = ALICE) -> TestClient:
    """Un navegador con una sesión nueva de ``user``: cada llamada lleva un token recién emitido."""
    app = create_app(store=store, auth=auth, github_app=github)
    app.state.llm_factory = lambda key, model=None: FakeAnalyst()
    return TestClient(app, headers=bearer(token(user)), follow_redirects=False)


def test_imported_repo_and_its_v2_reopen_after_signing_out(store, auth, monkeypatch):
    monkeypatch.setenv("BRANCHPOINT_FRONTEND_URL", "http://front.test")
    github = FakeGitHub()
    alice = session(store, auth, github)

    # Cuenta nueva: Mis proyectos vacío. Conecta la GitHub App e importa su repo.
    assert alice.get("/projects").json() == []
    connect(alice)
    started = alice.post(
        "/github/ingestions",
        json={"repo_full_name": "acme/tienda"},
        headers={"X-Anthropic-Api-Key": KEY},
    )
    assert started.status_code == 202, started.text
    done = alice.get(f"/github/ingestions/{started.json()['id']}").json()
    assert done["status"] == "done" and done["version"] == 1
    pid = done["project_id"]

    # El proyecto importado aparece en Mis proyectos con su repo y abre su v1.
    [listed] = alice.get("/projects").json()
    assert listed["id"] == pid and [v["number"] for v in listed["versions"]] == [1]
    assert listed["repositories"][0]["fullName"] == "acme/tienda"
    v1 = alice.get(f"/projects/{pid}/versions/1").json()

    # En el editor: simula la v1, cambia el modelo y guarda la v2.
    assert alice.post(f"/projects/{pid}/versions/1/runs", json=RUN).status_code == 200
    edited = v1["model"]
    edited["deployment"]["api"]["replicas"] = {"value": 3, "label": "SUPUESTO"}
    saved = alice.post(f"/projects/{pid}/versions", json={"model": edited, "parent": 1, "origin": "manual"})
    assert saved.status_code == 201, saved.text
    assert saved.json()["number"] == 2

    # Cierra sesión y vuelve con la misma cuenta (otro token, otra instancia de la API).
    alice.close()
    again = session(store, auth, github)
    [reopened] = again.get("/projects").json()
    assert reopened["id"] == pid and [v["number"] for v in reopened["versions"]] == [1, 2]
    v2 = again.get(f"/projects/{pid}/versions/2").json()
    assert v2["model"]["deployment"]["api"]["replicas"]["value"] == 3
    assert again.post(f"/projects/{pid}/versions/2/runs", json=RUN).status_code == 200

    # Otra cuenta no lo ve.
    bob = session(store, auth, github, BOB)
    assert bob.get("/projects").json() == []
    assert bob.get(f"/projects/{pid}/versions/2").status_code == 404
