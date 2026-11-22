"""Borrar un proyecto (JAJ-144): ``DELETE /projects/{id}`` se lleva todo lo suyo, solo para su dueño."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.samples import load_sample
from app.storage import InMemoryAttachmentStorage
from app.storage.attachments import StorageError
from tests.api.test_attachments import ALICE, BOB, FakeAuth, h, upload

SAMPLE = "full-stack-fastapi-template"
RUN = {"scenario": "pico_normal", "seed": 1, "duration_s": 10}
# las tablas que cuelgan del proyecto, todas con on delete cascade
PROJECT_TABLES = (
    "model_versions",
    "scenarios",
    "runs",
    "reports",
    "chat_sessions",
    "chat_attachments",
    "project_repositories",
    "ingestions",
    "usage_profiles",
)


@pytest.fixture(params=["memoria", "postgres"])
def store(request):
    """Memoria o Postgres; en Postgres, con ALICE y BOB en ``auth.users`` (como en ``test_attachments``)."""
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
    return TestClient(create_app(store=store, auth=FakeAuth(), github_app=None, attachment_storage=storage))


def full_project(client, storage, user=ALICE) -> str:
    """Un proyecto con de todo: dos versiones, un escenario guardado, runs con su reporte, chat y adjuntos
    (uno listo y uno a medio subir)."""
    pid = client.post("/projects", json={"sample": SAMPLE}, headers=h(user)).json()["id"]
    ops = {"ops": [{"op": "scale_api", "replicas": 2}]}
    assert client.post(f"/projects/{pid}/versions/1/ops", json=ops, headers=h(user)).status_code == 201
    client.put(f"/projects/{pid}/scenarios/carga", json={"rps": 20}, headers=h(user))
    assert client.post(f"/projects/{pid}/versions/1/runs", json=RUN, headers=h(user)).status_code == 200
    assert client.post(f"/projects/{pid}/versions/2/reports", json=RUN, headers=h(user)).status_code == 201
    ready = upload(client, storage, pid, user=user)
    client.post(f"/projects/{pid}/attachments/{ready['id']}/complete", headers=h(user))
    upload(client, storage, pid, filename="a-medias.png", user=user)  # pending: también se borra
    client.app.state.store.save_chat(pid, [{"role": "user", "content": "hola"}])
    return pid


def rows_left(database_url: str, pid: str) -> dict[str, int]:
    import psycopg

    with psycopg.connect(database_url) as conn:
        counts = {
            t: conn.execute(f"select count(*) from {t} where project_id = %s", (pid,)).fetchone()[0]
            for t in PROJECT_TABLES
        }
        counts["projects"] = conn.execute("select count(*) from projects where id = %s", (pid,)).fetchone()[0]
    return {t: n for t, n in counts.items() if n}


def test_deleting_a_project_takes_everything_with_it(client, storage, store, request):
    pid = full_project(client, storage)
    other = full_project(client, storage)  # otro proyecto del mismo usuario: no se toca
    other_files = {p for p in storage.objects if f"/{other}/" in p}
    assert len(storage.objects) == 4 and len(other_files) == 2
    assert store.list_reports(pid) and store.get_chat(pid)  # en los dos stores, había de todo
    in_pg = "postgres" in request.node.callspec.id
    if in_pg:  # antes de borrar hay filas en cada tabla que el test dice limpiar
        before = rows_left(request.getfixturevalue("database_url"), pid)
        assert {"projects", "model_versions", "scenarios", "runs", "reports", "chat_sessions"} <= set(before)
        assert before["chat_attachments"] == 2 and before["model_versions"] == 2

    assert client.delete(f"/projects/{pid}", headers=h()).status_code == 204

    assert client.get(f"/projects/{pid}", headers=h()).status_code == 404
    assert [p["id"] for p in client.get("/projects", headers=h()).json()] == [other]
    assert set(storage.objects) == other_files  # los archivos del borrado se fueron; los del otro, no
    assert store.get_chat(pid) == [] and store.list_reports(pid) == []
    assert client.get(f"/projects/{other}/attachments", headers=h()).json() != []
    if in_pg:
        assert rows_left(request.getfixturevalue("database_url"), pid) == {}


def test_only_the_owner_can_delete(client, storage):
    pid = full_project(client, storage)
    r = client.delete(f"/projects/{pid}", headers=h(BOB))
    assert r.status_code == 404 and r.json()["error"]["resource"] == "project"  # como si no existiera
    assert client.get(f"/projects/{pid}", headers=h()).status_code == 200
    assert len(storage.objects) == 2


@pytest.mark.parametrize("pid", ["no-existe", "00000000-0000-0000-0000-000000000000"])
def test_unknown_project_is_404(client, pid):
    assert client.delete(f"/projects/{pid}", headers=h()).status_code == 404


def test_deleting_twice_is_404(client, storage):
    pid = full_project(client, storage)
    assert client.delete(f"/projects/{pid}", headers=h()).status_code == 204
    assert client.delete(f"/projects/{pid}", headers=h()).status_code == 404


def test_without_session_is_401(client, storage):
    pid = full_project(client, storage)
    assert client.delete(f"/projects/{pid}").status_code == 401
    assert client.get(f"/projects/{pid}", headers=h()).status_code == 200


def test_if_storage_fails_nothing_is_deleted(client, storage, monkeypatch):
    """Si no se pueden borrar los archivos, el proyecto se queda: si no, nadie los encontraría después."""
    pid = full_project(client, storage)

    def broken(paths):
        raise StorageError("caído")

    monkeypatch.setattr(storage, "delete", broken)
    r = client.delete(f"/projects/{pid}", headers=h())
    assert r.status_code == 502 and "no se borró" in r.json()["error"]["message"]
    assert client.get(f"/projects/{pid}", headers=h()).status_code == 200


def test_without_login_or_storage(store):
    """Sin login (``owner`` None) y sin Storage también se puede borrar: no hay adjuntos que limpiar."""
    client = TestClient(create_app(store=store, auth=None, github_app=None, attachment_storage=None))
    pid = client.post("/projects", json={"model": load_sample(SAMPLE)}).json()["id"]
    assert client.delete(f"/projects/{pid}").status_code == 204
    assert client.get("/projects").json() == []
