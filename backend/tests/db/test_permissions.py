"""Solo el backend escribe en las tablas (JAJ-97).

El frontend usa Supabase solo para el login. Un usuario con la key pública y su token no puede
escribir por PostgREST: ``anon`` no tiene permisos y ``authenticated`` solo lee lo suyo. Estos tests
entran a Postgres con esos roles, como lo haría PostgREST.
"""

from __future__ import annotations

import json
import uuid

import psycopg
import pytest

from app.api.run_cache import cache_key
from app.api.schemas import RunParams
from app.samples import load_sample

ALICE = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
BOB = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
WRITE = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")


@pytest.fixture
def store(clean_pg_store):
    return clean_pg_store


@pytest.fixture
def users(database_url):
    with psycopg.connect(database_url) as conn:
        for i in (ALICE, BOB):
            conn.execute(
                "insert into auth.users (id, aud, role, email) values (%s, 'authenticated', 'authenticated', %s)"
                " on conflict (id) do nothing",
                (i, f"{i[:4]}@test.cl"),
            )


def as_user(conn: psycopg.Connection, user: str | None) -> None:
    """Lo que hace PostgREST: cambia al rol de la request y deja los claims del token."""
    role = "authenticated" if user else "anon"
    conn.execute(f"set local role {role}")
    claims = {"sub": user, "role": role} if user else {"role": role}
    conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))


def test_no_table_lets_the_browser_write(database_url):
    """La guardia para las tablas nuevas: Supabase les da todos los permisos a anon y authenticated,
    así que cada migración que cree una tabla tiene que hacer el revoke (ver la migración de JAJ-97)."""
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            "select table_name, grantee, privilege_type from information_schema.role_table_grants"
            " where table_schema = 'public' and grantee in ('anon', 'authenticated')"
            " and (privilege_type = any(%s) or grantee = 'anon')"
            " order by 1, 2, 3",
            (list(WRITE),),
        ).fetchall()
    assert rows == []


def test_user_cannot_register_someone_elses_installation(database_url, users):
    """BE-02: antes, la política ``own ... for all`` dejaba insertar cualquier installation_id."""
    with psycopg.connect(database_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_user(conn, BOB)
        conn.execute(
            "insert into github_installations (installation_id, owner_id, account_login) values (42, %s, 'acme')",
            (BOB,),
        )


@pytest.mark.parametrize(
    "sql",
    [
        "insert into projects (name, owner_id) values ('x', '{u}')",
        "update projects set name = 'x'",
        "delete from projects",
        "insert into repo_connections (owner_id, kind, archive_sha256) values ('{u}', 'zip', 'x')",
        "delete from scenarios",
    ],
)
def test_user_cannot_write_any_table(database_url, users, sql):
    with psycopg.connect(database_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_user(conn, ALICE)
        conn.execute(sql.format(u=ALICE))


def test_user_cannot_plant_a_run(database_url, store, users):
    """BE-15: antes, ``insert_own`` dejaba insertar un resultado falso con el cache_key que quisiera."""
    project = store.create("tienda", load_sample("full-stack-fastapi-template"), None, ALICE)
    with psycopg.connect(database_url) as conn:
        version = conn.execute("select id from model_versions where project_id = %s", (project.id,)).fetchone()[0]
    with psycopg.connect(database_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_user(conn, ALICE)
        conn.execute(
            "insert into runs (project_id, model_version_id, scenario_name, seed, params, engine_version,"
            " cache_key, result, error_rate, throughput_rps)"
            " values (%s, %s, 's', 0, '{}', 'x', 'clave', '{\"schema\": \"branchpoint.run/v1\"}', 0, 0)",
            (project.id, version),
        )


def test_anon_reads_nothing(database_url, store, users):
    store.create("tienda", load_sample("full-stack-fastapi-template"), None, ALICE)
    with psycopg.connect(database_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_user(conn, None)
        conn.execute("select * from projects")


def test_user_still_reads_only_their_own_rows(database_url, store, users):
    """Las políticas de lectura siguen: la segunda barrera si el frontend lee con supabase-js."""
    mine = store.create("mío", load_sample("full-stack-fastapi-template"), None, ALICE)
    store.create("ajeno", load_sample("full-stack-fastapi-template"), None, BOB)
    with psycopg.connect(database_url) as conn:
        as_user(conn, ALICE)
        projects = conn.execute("select id::text from projects").fetchall()
        versions = conn.execute("select distinct project_id::text from model_versions").fetchall()
        credentials = conn.execute("select has_table_privilege('llm_credentials', 'select')").fetchone()
    assert projects == [(mine.id,)] and versions == [(mine.id,)]
    assert credentials == (False,)  # el id del secreto en Vault solo lo lee el backend


def test_find_run_ignores_a_run_saved_under_another_project(store, users):
    """BE-15: aunque una fila tuviera la clave del proyecto A, si es de B no se devuelve al simular A."""
    model = load_sample("full-stack-fastapi-template")
    a = store.create("a", model, None, ALICE)
    b = store.create("b", model, None, BOB)
    key = cache_key(a.id, 1, RunParams(scenario="pico_normal"))
    store.save_run(b.id, 1, key, {}, {"schema": "branchpoint.run/v1", "planted": True} | _run_stub(), "x")
    assert store.find_run(a.id, 1, key) is None
    assert store.find_run(b.id, 1, key)["planted"]  # la fila existe, pero es de B
    assert store.find_run(b.id, 2, key) is None  # y de la v1, no de otra versión
    assert store.find_run("no-es-uuid", 1, key) is None
    assert store.find_run(str(uuid.uuid4()), 1, key) is None


def _run_stub() -> dict:
    """Lo mínimo que ``save_run`` lee de un Run para sus columnas."""
    return {
        "scenario": "pico_normal",
        "seed": 0,
        "latency": {"p95_ms": 1.0},
        "error_rate": 0.0,
        "throughput_rps": 1.0,
        "bottleneck": {"resource": None},
        "elapsed_ms": 1.0,
    }
