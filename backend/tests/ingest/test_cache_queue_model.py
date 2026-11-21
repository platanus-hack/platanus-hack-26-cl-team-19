from textwrap import dedent

import pytest

from app.engine import simulate
from app.ingest.build_model import build
from app.models import load_model


def test_ingestion_models_cache_aside_and_celery_worker(tmp_path):
    (tmp_path / "main.py").write_text(
        dedent(
            """\
            from celery import Celery
            from fastapi import BackgroundTasks, FastAPI

            app = FastAPI()
            celery = Celery()

            def load_item(item_id):
                return db.get(Item, item_id)

            @app.get("/items/{item_id}")
            def item(item_id):
                db.get(User, 1)
                key = f"item:{item_id}"
                cached = redis.get(key)
                if cached is not None:
                    return cached
                result = load_item(item_id)
                redis.setex(key, 60, result)
                return result

            @celery.task(queue="refresh")
            def refresh_item(item_id):
                db.get(Item, item_id)

            @app.post("/refresh")
            def refresh(item_id, background_tasks: BackgroundTasks):
                refresh_item.delay(item_id)
                background_tasks.add_task(write_audit, item_id)
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "compose.yml").write_text(
        "services:\n  refresh-worker:\n    command: celery -A main.celery worker -Q refresh --concurrency=3\n",
        encoding="utf-8",
    )

    raw = build(tmp_path, {})
    cached_endpoint = next(ep for ep in raw["endpoints"] if ep["method"] == "GET")
    user_query, lookup = cached_endpoint["steps"]
    assert user_query["detail"] == "db.get(User)"
    assert [step["detail"] for step in lookup["on_miss"]] == ["db.get(Item)"]
    assert lookup["hit_ratio"]["value"] is None
    assert lookup["hit_ratio"]["needs_review"]
    queue = raw["deployment"]["queues"]["refresh"]
    assert queue["workers"]["value"] == 3 and queue["workers"]["label"] == "OBSERVADO"
    assert queue["job_steps"][0]["detail"] == "db.get(Item)"
    assert {m["field"] for m in raw["deployment"]["iac"]["missing"]} >= {
        f"overrides.cache_hit_ratio.{lookup['at']}",
        "deployment.queues.refresh.max_length",
    }
    model = load_model(raw)
    post_steps = next(ep for ep in model.endpoints if ep.id == "POST /refresh").steps
    assert [step.queue for step in post_steps] == ["refresh", None]

    default_run = simulate(model, rps=100, duration_s=5, seed=1)
    assert default_run.cache.hits == 0
    assert default_run.cache.misses > 0
    assert default_run.queues[0].processed > 0
    assert any("tasa de aciertos" in warning for warning in default_run.warnings)

    configured = build(
        tmp_path,
        {
            "overrides": {"cache_hit_ratio": {lookup["at"]: 0.5}},
            "deployment": {"queues": {"refresh": {"max_length": 8}}},
        },
    )
    assert configured["deployment"]["queues"]["refresh"]["max_length"]["value"] == 8
    run = simulate(load_model(configured), rps=100, duration_s=5, seed=1)
    assert run.cache.hits > 0 and run.cache.misses > 0
    assert run.queues[0].processed > 0


@pytest.mark.parametrize("key, guarded", [("x", True), ("another_key", False)])
def test_cache_miss_requires_a_matching_key(tmp_path, key, guarded):
    (tmp_path / "main.py").write_text(
        dedent(
            f'''\
            from fastapi import FastAPI

            app = FastAPI()

            @app.get("/x")
            def endpoint():
                cached = redis.get("x")
                if cached is None:
                    cached = db.get(Item, 1)
                    redis.set("{key}", cached)
                return cached
            '''
        ),
        encoding="utf-8",
    )

    steps = build(tmp_path, {})["endpoints"][0]["steps"]
    if guarded:
        assert [step["resource"] for step in steps] == ["cache"]
        assert [step["resource"] for step in steps[0]["on_miss"]] == ["db_connection"]
    else:
        assert [step["resource"] for step in steps] == ["cache", "db_connection", "cache"]
        assert all("on_miss" not in step for step in steps)


def test_shared_queue_does_not_assign_one_task_profile_to_every_job(tmp_path):
    (tmp_path / "main.py").write_text(
        dedent(
            """\
            from celery import shared_task
            from fastapi import FastAPI

            app = FastAPI()

            @shared_task(queue="refresh")
            def refresh_item(item_id):
                db.get(Item, item_id)

            @shared_task
            def refresh_user(user_id):
                db.get(User, user_id)

            @app.post("/refresh")
            def refresh():
                refresh_item.delay(1)
                refresh_user.apply_async(args=[2], queue="refresh")
            """
        ),
        encoding="utf-8",
    )

    raw = build(tmp_path, {})
    assert not load_model(raw).queues
    assert [s["resource"] for s in raw["endpoints"][0]["steps"]] == ["background", "background"]
