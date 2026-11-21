"""Caché (cache-aside) y colas con workers, desde la arquitectura que propone la IA más la IaC."""

import pytest

from app.engine import simulate
from app.ingest.ai_graph import ArchitectureSubmission, build_from_ai
from app.ingest.iac import scan_deployment
from app.models import load_model

EV = {"why": "visto en el código"}


def db_read(entity, line, shape="pk"):
    return {"kind": "db", "op": "read", "shape": shape, "entity": entity, "detail": "orm.get", "file": "app.js",
            "line": line, **EV}  # fmt: skip


def submission(**extra):
    return ArchitectureSubmission.model_validate(
        {
            "repo": "acme/tienda",
            "framework": "express",
            "language": "javascript",
            "endpoints": [
                {
                    "method": "GET",
                    "path": "/items/:id",
                    "handler": "getItem",
                    "file": "app.js",
                    "line": 10,
                    **EV,
                    "effects": [
                        db_read("User", 11),
                        {
                            "kind": "cache",
                            "detail": "redis.get(item:id)",
                            "file": "app.js",
                            "line": 13,
                            **EV,
                            "on_miss": [db_read("Item", 16)],
                        },
                    ],
                },
                {
                    "method": "POST",
                    "path": "/refresh",
                    "handler": "refresh",
                    "file": "app.js",
                    "line": 30,
                    **EV,
                    "effects": [
                        {
                            "kind": "background",
                            "task": "refreshItem",
                            "queue": "refresh",
                            "detail": "queue.add",
                            "file": "app.js",
                            "line": 31,
                            **EV,
                        },  # fmt: skip
                    ],
                },
            ],
            "jobs": [
                {
                    "task": "refreshItem",
                    "queue": "refresh",
                    "file": "worker.js",
                    "line": 3,
                    **EV,
                    "effects": [db_read("Item", 4)],
                },  # fmt: skip
            ],
            **extra,
        }
    )


@pytest.mark.parametrize(
    ("concurrency", "replicas", "expected_workers", "label"),
    [(3, None, 3, "OBSERVADO"), (3, 2, 6, "OBSERVADO"), (None, None, 1, "SUPUESTO")],
    ids=["concurrencia", "concurrencia-por-replica", "concurrencia-desconocida"],
)
def test_cache_aside_and_queue_worker_from_ai_and_iac(tmp_path, concurrency, replicas, expected_workers, label):
    command = "celery -A main.celery worker -Q refresh"
    if concurrency is not None:
        command += f" --concurrency={concurrency}"
    manifest = f"services:\n  refresh-worker:\n    command: {command}\n"
    if replicas is not None:
        manifest += f"    deploy:\n      replicas: {replicas}\n"
    (tmp_path / "compose.yml").write_text(manifest, encoding="utf-8")
    iac = scan_deployment(tmp_path).to_dict()

    raw = build_from_ai(submission(), {}, iac=iac)
    cached_endpoint = next(ep for ep in raw["endpoints"] if ep["method"] == "GET")
    user_query, lookup = cached_endpoint["steps"]
    assert user_query["detail"] == "orm.get (User)"
    assert [step["detail"] for step in lookup["on_miss"]] == ["orm.get (Item)"]
    assert lookup["hit_ratio"]["value"] is None and lookup["hit_ratio"]["needs_review"]
    queue = raw["deployment"]["queues"]["refresh"]
    assert (queue["workers"]["value"], queue["workers"]["label"]) == (expected_workers, label)
    assert queue["job_steps"][0]["detail"] == "orm.get (Item)"
    missing = {m["field"] for m in raw["deployment"]["iac"]["missing"]}
    assert missing >= {f"overrides.cache_hit_ratio.{lookup['at']}", "deployment.queues.refresh.max_length"}
    assert ("deployment.queues.refresh.workers" in missing) == (concurrency is None)

    model = load_model(raw)
    post_steps = next(ep for ep in model.endpoints if ep.id == "POST /refresh").steps
    assert [step.queue for step in post_steps] == ["refresh"]
    default_run = simulate(model, rps=100, duration_s=5, seed=1)
    assert default_run.cache.hits == 0 and default_run.cache.misses > 0
    assert default_run.queues[0].processed > 0

    configured = build_from_ai(
        submission(),
        {
            "overrides": {"cache_hit_ratio": {lookup["at"]: 0.5}},
            "deployment": {"queues": {"refresh": {"max_length": 8}}},
        },
        iac=iac,
    )
    assert configured["deployment"]["queues"]["refresh"]["max_length"]["value"] == 8
    run = simulate(load_model(configured), rps=100, duration_s=5, seed=1)
    assert run.cache.hits > 0 and run.cache.misses > 0


def test_shared_queue_does_not_assign_one_task_profile_to_every_job():
    sub = submission().model_dump()
    sub["endpoints"][1]["effects"].append({**sub["endpoints"][1]["effects"][0], "task": "refreshUser", "line": 32})
    sub["jobs"].append({**sub["jobs"][0], "task": "refreshUser"})
    raw = build_from_ai(ArchitectureSubmission.model_validate(sub))
    assert not load_model(raw).queues  # dos perfiles de trabajo en una cola: no se adivina
    assert [s["resource"] for s in raw["endpoints"][1]["steps"]] == ["background", "background"]
