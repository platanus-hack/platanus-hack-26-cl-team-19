"""Sesiones de Supabase y proyectos por usuario (JAJ-78).

Los tokens se firman acá con una clave propia, publicada en un JWKS falso: así se prueba la
validación completa sin levantar Supabase Auth.
"""

from __future__ import annotations

import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.api.auth import (
    JWKS_TTL_S,
    MISS_COOLDOWN_S,
    RETRY_AFTER_FAILURE_S,
    AuthError,
    SupabaseAuth,
    auth_from_env,
)
from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.samples import load_sample

SUPABASE = "http://supabase.test"
ISSUER = f"{SUPABASE}/auth/v1"
SAMPLE = "full-stack-fastapi-template"
RUN = {"scenario": "cyberday", "seed": 1, "duration_s": 5}
ALICE = "11111111-1111-1111-1111-111111111111"
BOB = "22222222-2222-2222-2222-222222222222"

_KEY = ec.generate_private_key(ec.SECP256R1())
_JWK = {**json.loads(jwt.algorithms.ECAlgorithm.to_jwk(_KEY.public_key())), "kid": "k1", "alg": "ES256"}


def token(sub: str = ALICE, *, key=_KEY, kid: str = "k1", **claims) -> str:
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        "email": "a@b.cl",
        **claims,
    }
    return jwt.encode(payload, key, algorithm="ES256", headers={"kid": kid})


def bearer(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def jwks_calls():
    return []


@pytest.fixture
def auth(jwks_calls):
    def fetch(url):
        jwks_calls.append(url)
        return {"keys": [_JWK]}

    return SupabaseAuth(SUPABASE, fetch_jwks=fetch)


@pytest.fixture(params=["memoria", "postgres"])
def store(request):
    if request.param == "memoria":
        return InMemoryProjectStore()
    store = request.getfixturevalue("clean_pg_store")
    _ensure_users(request.getfixturevalue("database_url"), ALICE, BOB)
    return store


def _ensure_users(database_url: str, *ids: str) -> None:
    """projects.owner_id referencia auth.users: los usuarios de los tests tienen que existir ahí."""
    import psycopg

    with psycopg.connect(database_url) as conn:
        for i in ids:
            conn.execute(
                "insert into auth.users (id, aud, role, email) values (%s, 'authenticated', 'authenticated', %s)"
                " on conflict (id) do nothing",
                (i, f"{i[:4]}@test.cl"),
            )


@pytest.fixture
def client(store, auth):
    return TestClient(create_app(cors_origins=["http://localhost:3000"], store=store, auth=auth))


# --- 401 -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer no-es-un-jwt"},
    ],
)
def test_missing_or_malformed_token_is_401(client, headers):
    r = client.get("/projects", headers=headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    "bad, says",
    [
        (lambda: token(exp=int(time.time()) - 3600), "venció"),
        (lambda: token(aud="anon"), "authenticated"),
        (lambda: token(iss="http://otro.supabase/auth/v1"), "otro proyecto"),
        (lambda: token(key=ec.generate_private_key(ec.SECP256R1())), "no es válido"),
        (lambda: token(kid="otra"), "clave que el proyecto no publica"),
        (lambda: token(sub="no-es-uuid"), "uuid"),
        (lambda: jwt.encode({"sub": ALICE}, "s" * 32, algorithm="HS256"), "secreto compartido"),
    ],
)
def test_invalid_token_is_401_with_a_reason(client, bad, says):
    r = client.get("/projects", headers=bearer(bad()))
    assert r.status_code == 401, r.text
    assert says in r.json()["error"]["message"]


def test_every_project_route_needs_a_session(client):
    pid = client.post("/projects", json={"sample": SAMPLE}, headers=bearer(token())).json()["id"]
    routes = [
        ("get", f"/projects/{pid}", None),
        ("post", f"/projects/{pid}/versions", {"model": load_sample(SAMPLE)}),
        ("get", f"/projects/{pid}/versions/1", None),
        ("post", f"/projects/{pid}/versions/1/ops", {"ops": [{"op": "scale_api", "replicas": 2}]}),
        ("post", f"/projects/{pid}/versions/1/runs", RUN),
        ("post", f"/projects/{pid}/compare", {"a": 1, "b": 1, **RUN}),
        ("get", f"/projects/{pid}/versions/1/costs", None),
        ("get", f"/projects/{pid}/scenarios", None),
        ("get", f"/projects/{pid}/scenarios/cyberday", None),
        ("put", f"/projects/{pid}/scenarios/x", {"rps": 5}),
        ("post", "/projects", {"sample": SAMPLE}),
    ]
    for method, path, body in routes:
        r = client.request(method, path, json=body)
        assert r.status_code == 401, (method, path, r.status_code)


def test_public_routes_need_no_session(client):
    """El catálogo y lo que no guarda nada siguen abiertos, para arrancar el flujo sin cuenta."""
    model = load_sample(SAMPLE)
    assert client.get("/health").status_code == 200
    assert client.get("/models").status_code == 200
    assert client.get(f"/models/{SAMPLE}").status_code == 200
    assert client.post("/graph", json={"model": model}).status_code == 200
    assert client.post("/runs", json={"model": model, **RUN}).status_code == 200
    assert client.post("/costs", json={"model": model}).status_code == 200


# --- aislamiento entre usuarios --------------------------------------------------------------------


def test_bob_cannot_see_or_touch_alices_project(client):
    """Criterio 2: A crea un proyecto y B no puede listarlo, abrirlo, simularlo ni escribir versiones."""
    a, b = bearer(token(ALICE)), bearer(token(BOB))
    pid = client.post("/projects", json={"sample": SAMPLE}, headers=a).json()["id"]
    assert [p["id"] for p in client.get("/projects", headers=a).json()] == [pid]
    assert client.get("/projects", headers=b).json() == []

    attempts = [
        ("get", f"/projects/{pid}", None),
        ("post", f"/projects/{pid}/versions", {"model": load_sample(SAMPLE)}),
        ("get", f"/projects/{pid}/versions/1", None),
        ("post", f"/projects/{pid}/versions/1/ops", {"ops": [{"op": "scale_api", "replicas": 2}]}),
        ("post", f"/projects/{pid}/versions/1/runs", RUN),
        ("post", f"/projects/{pid}/compare", {"a": 1, "b": 1, **RUN}),
        ("get", f"/projects/{pid}/versions/1/costs", None),
        ("get", f"/projects/{pid}/scenarios", None),
        ("put", f"/projects/{pid}/scenarios/x", {"rps": 5}),
        ("get", f"/projects/{pid}/chat", None),
        ("put", f"/projects/{pid}/chat", {"messages": []}),
    ]
    for method, path, body in attempts:
        r = client.request(method, path, json=body, headers=b)
        # 404 y no 403: para B el proyecto no existe
        assert r.status_code == 404 and r.json()["error"]["resource"] == "project", (method, path, r.text)

    # nada de lo que intentó B quedó escrito
    project = client.get(f"/projects/{pid}", headers=a).json()
    assert [v["number"] for v in project["versions"]] == [1]
    assert "x" not in [s["name"] for s in client.get(f"/projects/{pid}/scenarios", headers=a).json()]


def test_alice_works_normally_with_her_token(client):
    a = bearer(token(ALICE))
    pid = client.post("/projects", json={"sample": SAMPLE}, headers=a).json()["id"]
    r = client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 2}]}, headers=a)
    assert r.status_code == 201, r.text
    cmp = client.post(f"/projects/{pid}/compare", json={"a": 1, "b": 2, **RUN}, headers=a)
    assert cmp.status_code == 200, cmp.text


def test_projects_without_owner_are_not_visible_with_login(store, auth):
    """Los proyectos anónimos de antes de JAJ-78 no son de nadie: con login no se ven."""
    anon = store.create("viejo", load_sample(SAMPLE), SAMPLE)
    client = TestClient(create_app(store=store, auth=auth))
    assert client.get("/projects", headers=bearer(token())).json() == []
    assert client.get(f"/projects/{anon.id}", headers=bearer(token())).status_code == 404


def test_without_login_everything_is_anonymous(store):
    """BRANCHPOINT_AUTH=off (o sin SUPABASE_URL): como antes de JAJ-78."""
    client = TestClient(create_app(store=store, auth=None))
    pid = client.post("/projects", json={"sample": SAMPLE}).json()["id"]
    assert [p["id"] for p in client.get("/projects").json()] == [pid]


def test_alice_reopens_v2_after_a_restart(database_url, clean_pg_store, auth):
    """Criterio 3: A guarda una v2 y la reabre después de reiniciar la API con Postgres."""
    from app.db.postgres_store import PostgresProjectStore

    _ensure_users(database_url, ALICE, BOB)
    a = bearer(token(ALICE))
    client = TestClient(create_app(store=clean_pg_store, auth=auth))
    pid = client.post("/projects", json={"sample": SAMPLE}, headers=a).json()["id"]
    client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 3}]}, headers=a)

    restarted = PostgresProjectStore.from_url(database_url)
    try:
        again = TestClient(create_app(store=restarted, auth=auth))
        v2 = again.get(f"/projects/{pid}/versions/2", headers=a)
        assert v2.status_code == 200 and v2.json()["model"]["deployment"]["api"]["replicas"]["value"] == 3
        assert again.get(f"/projects/{pid}/versions/2", headers=bearer(token(BOB))).status_code == 404
    finally:
        restarted.close()


# --- validación ------------------------------------------------------------------------------------


def test_jwks_is_fetched_once_and_refetched_for_a_new_kid(client, jwks_calls):
    for _ in range(3):
        client.get("/projects", headers=bearer(token()))
    assert jwks_calls == [f"{ISSUER}/.well-known/jwks.json"]
    client.get("/projects", headers=bearer(token(kid="nueva")))  # clave rotada: vuelve a bajar
    assert len(jwks_calls) == 2


def test_invented_kids_trigger_a_single_download(auth, jwks_calls):
    for i in range(10):
        with pytest.raises(AuthError, match="no publica"):
            auth.verify(token(kid=f"inventado-{i}"))
    assert len(jwks_calls) == 1
    assert auth.verify(token()).id == ALICE  # la clave real sigue funcionando, sin otra descarga
    assert len(jwks_calls) == 1


def test_unknown_kid_is_looked_up_again_after_the_cooldown(auth, jwks_calls, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("app.api.auth.time.monotonic", lambda: clock[0])
    with pytest.raises(AuthError):
        auth.verify(token(kid="inventado"))
    clock[0] += MISS_COOLDOWN_S + 1
    with pytest.raises(AuthError):
        auth.verify(token(kid="inventado"))
    assert len(jwks_calls) == 2


def test_cached_key_survives_a_failed_ttl_refresh(monkeypatch):
    clock, calls, up = [1000.0], [], [True]

    def fetch(url):
        calls.append(clock[0])
        if not up[0]:
            raise OSError("connection refused")
        return {"keys": [_JWK]}

    monkeypatch.setattr("app.api.auth.time.monotonic", lambda: clock[0])
    auth = SupabaseAuth(SUPABASE, fetch_jwks=fetch)
    assert auth.verify(token()).id == ALICE
    up[0] = False
    clock[0] += JWKS_TTL_S + 1  # caché vencida y Supabase Auth caído
    assert auth.verify(token()).id == ALICE
    assert auth.verify(token()).id == ALICE  # no reintenta en cada request
    assert len(calls) == 2
    clock[0] += RETRY_AFTER_FAILURE_S + 1
    up[0] = True
    assert auth.verify(token()).id == ALICE
    assert len(calls) == 3  # reintentó y volvió a tener el JWKS al día


def test_supabase_auth_down_is_503(store):
    def down(url):
        raise OSError("connection refused")

    client = TestClient(create_app(store=store, auth=SupabaseAuth(SUPABASE, fetch_jwks=down)))
    r = client.get("/projects", headers=bearer(token()))
    assert r.status_code == 503 and r.json()["error"]["code"] == "auth_unavailable"


def test_legacy_hs256_secret():
    auth = SupabaseAuth(SUPABASE, jwt_secret="s" * 32, fetch_jwks=lambda url: {"keys": []})
    t = jwt.encode(
        {"sub": ALICE, "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 60}, "s" * 32, "HS256"
    )
    assert auth.verify(t).id == ALICE


def test_cors_preflight_allows_authorization_and_put(client):
    r = client.options(
        "/projects/x/scenarios/y",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.status_code == 200
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
    assert "PUT" in r.headers["access-control-allow-methods"]


def test_auth_from_env(monkeypatch):
    assert auth_from_env() is None  # sin SUPABASE_URL
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321/")
    auth = auth_from_env()
    assert auth is not None and auth.issuer == "http://127.0.0.1:54321/auth/v1"
    monkeypatch.setenv("BRANCHPOINT_AUTH", "off")
    assert auth_from_env() is None


def test_user_ids_are_normalized():
    upper = str(uuid.UUID(ALICE)).upper()
    auth = SupabaseAuth(SUPABASE, fetch_jwks=lambda url: {"keys": [_JWK]})
    assert auth.verify(token(upper)).id == ALICE
