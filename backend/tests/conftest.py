"""Fixtures compartidas. Los tests de Postgres corren solo con ``TEST_DATABASE_URL``.

Con el stack local de Supabase arriba (``npx supabase start`` o ``npx supabase db start``):

  TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python -m pytest

Cada test parte con las tablas vacías, así que solo se acepta una base local.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@pytest.fixture(autouse=True)
def _no_login_from_env(monkeypatch):
    """Los tests no leen el login del entorno: con SUPABASE_URL en el .env de alguien, create_app()
    pediría tokens. Los tests de login (JAJ-78) pasan su propio SupabaseAuth."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("BRANCHPOINT_AUTH", raising=False)


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("sin TEST_DATABASE_URL: se saltan los tests de Postgres")
    if urlparse(url).hostname not in LOCAL_HOSTS:
        pytest.fail("TEST_DATABASE_URL tiene que ser una base local: los tests borran las tablas")
    return url


@pytest.fixture(scope="session")
def pg_store(database_url):
    from app.db.postgres_store import PostgresProjectStore

    store = PostgresProjectStore.from_url(database_url)
    yield store
    store.close()


def truncate(database_url: str) -> None:
    import psycopg

    with psycopg.connect(database_url) as conn:
        conn.execute("truncate projects, repo_connections, github_installations cascade")


@pytest.fixture
def clean_pg_store(database_url, pg_store):
    truncate(database_url)
    return pg_store
