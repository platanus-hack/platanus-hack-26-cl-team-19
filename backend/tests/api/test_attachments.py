"""IA-6 (JAJ-115): adjuntos temporales del chat, con ``InMemoryAttachmentStorage`` y en memoria o Postgres."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.auth import AuthError, User
from app.api.main import create_app
from app.api.routes.attachments import purge_expired, safe_filename
from app.api.store import InMemoryProjectStore
from app.samples import load_sample
from app.storage import InMemoryAttachmentStorage

ALICE = str(uuid.UUID(int=0xA11CE))
BOB = str(uuid.UUID(int=0xB0B))
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


class FakeAuth:
    """El token es el id del usuario: alcanza para probar dueños sin firmar JWT."""

    def verify(self, token: str) -> User:
        try:
            return User(str(uuid.UUID(token)))
        except ValueError:
            raise AuthError("token inválido") from None


@pytest.fixture(params=["memoria", "postgres"])
def store(request):
    if request.param == "memoria":
        return InMemoryProjectStore()
    import psycopg

    store = request.getfixturevalue("clean_pg_store")
    with psycopg.connect(request.getfixturevalue("database_url")) as conn:
        for uid in (ALICE, BOB):
            conn.execute(
                "insert into auth.users (id, aud, role, email) values (%s, 'authenticated', 'authenticated', %s)"
                " on conflict (id) do nothing",
                (uid, f"{uid[-4:]}@example.com"),
            )
    return store


@pytest.fixture
def storage():
    return InMemoryAttachmentStorage()


@pytest.fixture
def client(store, storage):
    app = create_app(store=store, auth=FakeAuth(), github_app=None, attachment_storage=storage)
    return TestClient(app)


def h(user=ALICE):
    return {"Authorization": f"Bearer {user}"}


@pytest.fixture
def project(store):
    return store.create("tienda", load_sample("full-stack-fastapi-template"), None, ALICE).id


def upload(client, storage, project, filename="panel.png", media_type="image/png", data=PNG, user=ALICE):
    r = client.post(
        f"/projects/{project}/attachments",
        json={"filename": filename, "media_type": media_type, "bytes": len(data)},
        headers=h(user),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    path = body["upload_url"].removeprefix("memory://chat-attachments/")
    from urllib.parse import unquote

    storage.put(unquote(path), data, body["content_type"])
    return body


def test_upload_complete_list_and_delete(client, storage, project):
    body = upload(client, storage, project)
    assert body["kind"] == "image" and body["content_type"] == "image/png"
    assert client.get(f"/projects/{project}/attachments", headers=h()).json() == []  # pending no se lista
    assert client.post(f"/projects/{project}/attachments/{body['id']}/complete", headers=h()).status_code == 204
    listed = client.get(f"/projects/{project}/attachments", headers=h()).json()
    assert [(a["id"], a["kind"], a["filename"], a["bytes"]) for a in listed] == [
        (body["id"], "image", "panel.png", len(PNG))
    ]
    assert client.delete(f"/projects/{project}/attachments/{body['id']}", headers=h()).status_code == 204
    assert client.get(f"/projects/{project}/attachments", headers=h()).json() == []
    assert storage.objects == {}


def test_object_path_has_owner_project_and_id(client, storage, project):
    body = upload(client, storage, project, filename="../../x.png")
    [path] = storage.objects
    assert path == f"{ALICE}/{project}/{body['id']}/x.png"


@pytest.mark.parametrize(
    "filename,media_type,size",
    [
        ("a.svg", "image/svg+xml", 10),
        ("a.pdf", "application/pdf", 10),
        ("a.png", "image/png", 5 * 1024 * 1024 + 1),
        ("a.log", "text/plain", 10 * 1024 * 1024 + 1),
        ("a.exe", "application/octet-stream", 10),
    ],
)
def test_rejected_type_or_size_creates_nothing(client, store, project, filename, media_type, size):
    r = client.post(
        f"/projects/{project}/attachments",
        json={"filename": filename, "media_type": media_type, "bytes": size},
        headers=h(),
    )
    assert r.status_code == 422
    assert store.list_attachments(project, ALICE, include_pending=True) == []


def test_log_without_mime_type_is_plain_text(client, storage, project):
    body = upload(client, storage, project, filename="access.log", media_type="application/octet-stream", data=b"x")
    assert body["kind"] == "log" and body["content_type"] == "text/plain"


def test_complete_with_other_size_is_422_and_deletes(client, storage, store, project):
    r = client.post(
        f"/projects/{project}/attachments",
        json={"filename": "a.png", "media_type": "image/png", "bytes": 50},
        headers=h(),
    )
    aid, url = r.json()["id"], r.json()["upload_url"]
    from urllib.parse import unquote

    storage.put(unquote(url.removeprefix("memory://chat-attachments/")), PNG, "image/png")  # 108 bytes, no 50
    r = client.post(f"/projects/{project}/attachments/{aid}/complete", headers=h())
    assert r.status_code == 422
    assert storage.objects == {} and store.get_attachment(aid, ALICE) is None


def test_complete_without_upload_is_422(client, project):
    r = client.post(
        f"/projects/{project}/attachments",
        json={"filename": "a.png", "media_type": "image/png", "bytes": 50},
        headers=h(),
    )
    assert client.post(f"/projects/{project}/attachments/{r.json()['id']}/complete", headers=h()).status_code == 422


def test_other_user_cannot_see_or_complete(client, storage, store, project):
    body = upload(client, storage, project)
    assert client.post(f"/projects/{project}/attachments/{body['id']}/complete", headers=h(BOB)).status_code == 404
    assert client.get(f"/projects/{project}/attachments", headers=h(BOB)).status_code == 404  # proyecto ajeno
    bob_project = store.create("otra", load_sample("full-stack-fastapi-template"), None, BOB).id
    r = client.post(f"/projects/{bob_project}/attachments/{body['id']}/complete", headers=h(BOB))
    assert r.status_code == 404
    assert client.delete(f"/projects/{bob_project}/attachments/{body['id']}", headers=h(BOB)).status_code == 404


def test_without_session_is_401(client, project):
    assert client.get(f"/projects/{project}/attachments").status_code == 401
    r = client.post(
        f"/projects/{project}/attachments", json={"filename": "a.png", "media_type": "image/png", "bytes": 1}
    )
    assert r.status_code == 401


def test_without_login_configured_is_401(store, storage):
    client = TestClient(create_app(store=store, auth=None, github_app=None, attachment_storage=storage))
    pid = store.create("tienda", load_sample("full-stack-fastapi-template"), None).id
    assert client.get(f"/projects/{pid}/attachments").status_code == 401


def test_without_storage_is_503(store, project):
    client = TestClient(create_app(store=store, auth=FakeAuth(), github_app=None, attachment_storage=None))
    assert client.get(f"/projects/{project}/attachments", headers=h()).status_code == 503


def test_expired_attachment_is_hidden_and_purged(client, storage, store, project, monkeypatch):
    body = upload(client, storage, project)
    client.post(f"/projects/{project}/attachments/{body['id']}/complete", headers=h())
    a = store.get_attachment(body["id"], ALICE)
    past = datetime.now(UTC) - timedelta(minutes=1)
    if isinstance(store, InMemoryProjectStore):
        store._attachments[a.id] = replace(a, expires_at=past)
    else:
        import psycopg

        with psycopg.connect(store._pool.conninfo) as conn:
            conn.execute("update chat_attachments set expires_at = %s where id = %s", (past, a.id))
    assert store.list_attachments(project, ALICE) == []
    assert storage.objects  # sigue en Storage hasta la siguiente llamada
    assert client.get(f"/projects/{project}/attachments", headers=h()).json() == []
    assert storage.objects == {} and store.get_attachment(a.id, ALICE) is None
    assert client.post(f"/projects/{project}/attachments/{a.id}/complete", headers=h()).status_code == 404


def test_twenty_first_attachment_is_422(client, project):
    for i in range(20):
        r = client.post(
            f"/projects/{project}/attachments",
            json={"filename": f"{i}.log", "media_type": "text/plain", "bytes": 10},
            headers=h(),
        )
        assert r.status_code == 201
    r = client.post(
        f"/projects/{project}/attachments",
        json={"filename": "21.log", "media_type": "text/plain", "bytes": 10},
        headers=h(),
    )
    assert r.status_code == 422 and "20" in r.json()["error"]["message"]


@pytest.mark.parametrize(
    "raw,safe",
    [
        ("../../x.png", "x.png"),
        ("a/b/c.log", "c.log"),
        ("..\\..\\evil.png", "evil.png"),
        ("mi captura (1).png", "mi_captura_1_.png"),
        ("...", "archivo"),
        ("/", "archivo"),
    ],
)
def test_safe_filename(raw, safe):
    assert safe_filename(raw) == safe
    assert "/" not in safe_filename(raw) and ".." not in safe_filename(raw)


def test_purge_expired_for_everyone(store, storage, project):
    from app.api.store import Attachment

    now = datetime.now(UTC)
    for owner in (ALICE,):
        store.create_attachment(
            Attachment(
                str(uuid.uuid4()),
                owner,
                project,
                "log",
                "a.log",
                "text/plain",
                1,
                f"{owner}/{project}/x/a.log",
                "ready",
                now - timedelta(days=2),
                now - timedelta(days=1),
            )
        )
    storage.put(f"{ALICE}/{project}/x/a.log", b"x", "text/plain")
    assert purge_expired(store, storage, None) == 1
    assert storage.objects == {}
