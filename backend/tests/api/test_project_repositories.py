"""GET /projects trae el repo de cada proyecto, como lo lee "Mis proyectos" (JAJ-92)."""

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.store import InMemoryProjectStore, RepoSource
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"
SHA = "06ff98cfa9b925e35b866e5abdf9e792006a36bb"


def _client_and_store():
    store = InMemoryProjectStore()
    return TestClient(create_app(store=store, auth=None)), store


def test_imported_project_lists_its_repository():
    client, store = _client_and_store()
    imported = store.create("tienda", load_sample(SAMPLE), None, None, RepoSource("c1", "acme/tienda", "dev", SHA))

    listed = client.get("/projects").json()
    assert listed[0]["repositories"] == [{"id": imported.id, "fullName": "acme/tienda", "branch": "dev"}]
    # el id del repo es el del proyecto: el editor abre GET /projects/{id} con él
    one = client.get(f"/projects/{imported.id}").json()
    assert one["repositories"][0]["id"] == imported.id == one["id"]


def test_project_without_repository_is_null():
    """null y no []: con null el editor usa su fallback (el nombre del proyecto) en la barra lateral."""
    client, _ = _client_and_store()
    created = client.post("/projects", json={"sample": SAMPLE})
    assert created.status_code == 201 and created.json()["repositories"] is None
    assert client.get("/projects").json()[0]["repositories"] is None


def test_other_owner_does_not_see_the_repository():
    """El repo viaja con el proyecto: si el proyecto es de otro, no aparece (aislamiento de JAJ-78)."""
    client, store = _client_and_store()
    store.create("ajeno", load_sample(SAMPLE), None, "otro-usuario", RepoSource("c1", "acme/privado", "main", SHA))
    assert client.get("/projects").json() == []
