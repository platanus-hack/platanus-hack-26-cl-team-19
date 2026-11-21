"""Tests de PostgresProjectStore (JAJ-56) contra el Postgres local de Supabase."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from app.db.postgres_store import PostgresProjectStore
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"


@pytest.fixture
def store(clean_pg_store):
    return clean_pg_store


@pytest.fixture
def model():
    return load_sample(SAMPLE)


def test_survives_a_restart(database_url, store, model):
    project = store.create("tienda", model, SAMPLE)
    store.add_version(project.id, model, "manual", 1, "API ×2")
    restarted = PostgresProjectStore.from_url(database_url)  # otro pool, como si la API reiniciara
    try:
        again = restarted.get(project.id)
        assert again is not None and again.name == "tienda" and again.sample == SAMPLE
        assert [(v.number, v.origin, v.parent) for v in again.versions] == [(1, "repo", None), (2, "manual", 1)]
        assert restarted.get_version(project.id, 2).model == model
    finally:
        restarted.close()


def test_get_lists_versions_without_models(store, model):
    project = store.create("tienda", model, None)
    assert [v.model for v in store.get(project.id).versions] == [None]
    assert store.get_version(project.id, 1).model == model


def test_unknown_or_malformed_ids_are_none(store, model):
    project = store.create("tienda", model, None)
    assert store.get("nope") is None
    assert store.get("00000000-0000-0000-0000-000000000000") is None
    assert store.get_version("nope", 1) is None
    assert store.get_version(project.id, 9) is None


def test_create_loads_the_model_scenarios(database_url, store, model):
    project = store.create("tienda", model, None)
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            "select name, multiplier, rps from scenarios where project_id = %s order by name", (project.id,)
        ).fetchall()
    assert [(name, float(mult), rps) for name, mult, rps in rows] == [
        ("cyberday", 20.0, None),
        ("pico_normal", 1.0, None),
    ]


def test_concurrent_versions_get_distinct_numbers(store, model):
    project = store.create("tienda", model, None)
    with ThreadPoolExecutor(max_workers=4) as pool:
        numbers = list(pool.map(lambda _: store.add_version(project.id, model, "agente", 1, None).number, range(8)))
    assert sorted(numbers) == list(range(2, 10))


def test_versions_are_immutable(database_url, store, model):
    project = store.create("tienda", model, None)
    with psycopg.connect(database_url) as conn, pytest.raises(psycopg.errors.RaiseException, match="no se edita"):
        conn.execute("update model_versions set note = 'x' where project_id = %s", (project.id,))


def test_add_version_rejects_missing_parent_and_project(store, model):
    project = store.create("tienda", model, None)
    with pytest.raises(psycopg.IntegrityError):
        store.add_version(project.id, model, "manual", 7, None)
    assert [v.number for v in store.get(project.id).versions] == [1]  # el contador volvió atrás
    with pytest.raises(KeyError):
        store.add_version("00000000-0000-0000-0000-000000000000", model, "manual", 1, None)


def test_saved_model_is_independent_of_the_caller(store, model):
    project = store.create("tienda", model, None)
    edited = copy.deepcopy(model)
    store.add_version(project.id, edited, "manual", 1, None)
    edited["deployment"]["api"]["replicas"]["value"] = 99
    assert store.get_version(project.id, 2).model["deployment"]["api"]["replicas"]["value"] != 99
