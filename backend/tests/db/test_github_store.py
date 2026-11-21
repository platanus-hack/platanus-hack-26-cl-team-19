"""Instalaciones, conexiones y la v1 de un repo en Postgres (JAJ-57)."""

from __future__ import annotations

import psycopg
import pytest

from app.api.store import GitHubInstallation, RepoSource
from app.samples import load_sample

SHA = "06ff98cfa9b925e35b866e5abdf9e792006a36bb"


@pytest.fixture
def store(clean_pg_store):
    return clean_pg_store


def test_installations_by_owner_and_revoked(store):
    store.save_installation(42, None, "alice-gh")
    store.save_installation(43, None, "acme")
    assert store.list_installations(None) == [GitHubInstallation(42, "alice-gh"), GitHubInstallation(43, "acme")]
    store.revoke_installation(43)
    assert store.list_installations(None) == [GitHubInstallation(42, "alice-gh")]
    store.save_installation(43, None, "acme")  # reinstalada: vuelve a listarse
    assert len(store.list_installations(None)) == 2


def test_connect_repo_reuses_the_connection(store):
    first = store.connect_repo(None, 42, 7, "acme/tienda", "main")
    again = store.connect_repo(None, 42, 7, "acme/tienda-renombrada", "main")
    assert first == again
    assert store.connect_repo(None, 42, 8, "acme/otra", "main") != first


def test_v1_from_a_repo_keeps_its_origin(database_url, store):
    model = load_sample("full-stack-fastapi-template")
    conn_id = store.connect_repo(None, 42, 7, "acme/tienda", "main")
    source = RepoSource(conn_id, "acme/tienda", "main", SHA, {"endpoints": 23})
    project = store.create("tienda", model, None, None, source)
    assert project.versions[0].note == "Extraída de acme/tienda@main (06ff98c)"

    with psycopg.connect(database_url) as conn:
        p = conn.execute(
            "select repo_connection_id::text, branch from projects where id = %s", (project.id,)
        ).fetchone()
        v = conn.execute("select commit_sha from model_versions where project_id = %s", (project.id,)).fetchone()
        ing = conn.execute(
            "select status::text, branch, commit_sha, stats, model_version_id is not null from ingestions"
            " where project_id = %s",
            (project.id,),
        ).fetchone()
    assert p == (conn_id, "main")
    assert v == (SHA,)
    assert ing == ("done", "main", SHA, {"endpoints": 23}, True)


def test_get_and_list_bring_the_repo_and_branch(store):
    """JAJ-92: GET /projects lee el repo con un join a repo_connections; un ejemplo no trae repo."""
    model = load_sample("full-stack-fastapi-template")
    conn_id = store.connect_repo(None, 42, 7, "acme/tienda", "main")
    from_repo = store.create("tienda", model, None, None, RepoSource(conn_id, "acme/tienda", "dev", SHA))
    from_sample = store.create("ejemplo", model, "full-stack-fastapi-template", None)

    assert (from_repo.repo_full_name, from_repo.branch) == ("acme/tienda", "dev")  # la rama analizada, no la default
    got = store.get(from_repo.id)
    assert (got.repo_full_name, got.branch) == ("acme/tienda", "dev")
    listed = {p.id: (p.repo_full_name, p.branch) for p in store.list(None)}
    assert listed == {from_repo.id: ("acme/tienda", "dev"), from_sample.id: (None, None)}
