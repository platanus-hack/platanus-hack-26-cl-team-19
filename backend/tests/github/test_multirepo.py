"""IA-5 (JAJ-121): un proyecto a partir de varios repos. El LLM falso responde según el repo que lee."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.agent.loop import Turn
from app.api.main import create_app
from app.api.store import InMemoryProjectStore
from app.github.client import Repo
from app.github.ingestion import model_from_tarball
from tests.github.test_github import SHA, FakeGitHub, connect, tarball

KEY = "sk-ant-key-multirepo-que-nunca-sale"
API = b"""const express = require('express')
const app = express()
app.get('/orders', async (req, res) => res.json(await db.order.findMany({ take: 20 })))
app.post('/orders', async (req, res) => {
  await fetch('http://worker:8080/jobs', { method: 'POST' })
  await stripe.charges.create({ amount: 100 })
  res.json(await db.order.create({ data: req.body }))
})
app.listen(3000)
"""
WORKER = b"""from fastapi import FastAPI
app = FastAPI()
@app.post('/jobs')
def create_job():
    redis.lpush('jobs', 1)
    return db.query(Job).all()
"""


def ev(file, line, why="leído en el archivo"):
    return {"file": file, "line": line, "why": why}


ARCH = {
    "acme/api": {
        "framework": "express",
        "language": "javascript",
        "endpoints": [
            {"method": "GET", "path": "/orders", "handler": "list", **ev("src/app.js", 3), "is_async": True,
             "effects": [{"kind": "db", "op": "read", "shape": "range", "entity": "Order", "detail": "db.order.findMany",
                          **ev("src/app.js", 3)}]},
            {"method": "POST", "path": "/orders", "handler": "create", **ev("src/app.js", 4), "is_async": True,
             "effects": [
                 {"kind": "external", "service": "worker-http", "detail": "fetch http://worker:8080/jobs",
                  **ev("src/app.js", 5)},
                 {"kind": "external", "service": "Stripe", "detail": "stripe.charges.create", **ev("src/app.js", 6)},
                 {"kind": "db", "op": "write", "shape": "commit", "entity": "Order", "detail": "db.order.create",
                  **ev("src/app.js", 7)},
             ]},
        ],
        "components": [
            {"name": "worker-http", "role": "external", "technology": "HTTP", **ev("src/app.js", 5)},
            {"name": "postgres", "role": "db", "technology": "Postgres", **ev("src/app.js", 3)},
        ],
    },
    "acme/worker": {
        "framework": "fastapi",
        "language": "python",
        "endpoints": [
            {"method": "POST", "path": "/jobs", "handler": "create_job", **ev("main.py", 3),
             "effects": [{"kind": "db", "op": "read", "shape": "scan", "entity": "Job", "detail": "db.query(Job)",
                          **ev("main.py", 6)}]},
        ],
        "components": [
            {"name": "postgres", "role": "db", "technology": "Postgres", **ev("main.py", 6)},
            {"name": "redis", "role": "cache", "technology": "Redis", **ev("main.py", 5)},
        ],
    },
}  # fmt: skip


class RepoAnalyst:
    """Entrega la arquitectura del repo que nombra el primer mensaje. ``fail`` lo hace fallar."""

    model = "claude-opus-5-5"

    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()

    def complete(self, system, messages, tools):
        repo = messages[0]["content"].split()[1].rstrip(",.")
        if repo in self.fail:  # entrega algo sin endpoints válidos hasta que se acaba la paciencia
            bad = {**ARCH[repo], "endpoints": [{**ARCH[repo]["endpoints"][0], "file": "no-existe.js"}]}
            return Turn([{"type": "tool_use", "id": "s", "name": "submit_architecture", "input": bad}], "tool_use")
        call = {"type": "tool_use", "id": "s", "name": "submit_architecture", "input": ARCH[repo]}
        return Turn([call], "tool_use", {"input": 1000, "output": 100})


class TwoRepoGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.repos = {42: [Repo(7, "acme/api", True, "main", 42), Repo(8, "acme/worker", True, "main", 42),
                           Repo(9, "acme/c", True, "main", 42), Repo(10, "acme/d", True, "main", 42),
                           Repo(11, "acme/e", True, "main", 42)]}  # fmt: skip
        self.tarballs = {
            "acme/api": tarball({"src/app.js": API}, root=f"acme-api-{SHA[:7]}"),
            "acme/worker": tarball({"main.py": WORKER}, root=f"acme-worker-{SHA[:7]}"),
        }


@pytest.fixture
def store():
    return InMemoryProjectStore()


def make_client(store, analyst):
    app = create_app(store=store, auth=None, github_app=TwoRepoGitHub(), attachment_storage=None)
    app.state.llm_factory = lambda key, model=None: analyst
    client = TestClient(app, follow_redirects=False, headers={"X-Anthropic-Api-Key": KEY})
    connect(client)
    return client


BODY = {"repos": [{"full_name": "acme/worker"}, {"full_name": "acme/api"}], "primary": "acme/api", "name": "Tienda"}


def run(client, body=BODY):
    r = client.post("/github/ingestions", json=body)
    assert r.status_code == 202, r.text
    for _ in range(100):
        job = client.get(f"/github/ingestions/{r.json()['id']}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("no terminó")


def test_two_repos_simulate_the_primary_and_show_the_secondary(store):
    client = make_client(store, RepoAnalyst())
    job = run(client)
    assert job["status"] == "done", job["error_message"]
    assert job["repo_full_name"] == "acme/api"
    assert [(r["full_name"], r["primary"], r["status"], r["endpoints"]) for r in job["repos"]] == [
        ("acme/api", True, "done", 2),
        ("acme/worker", False, "done", 1),
    ]
    model = store.get_version(job["project_id"], 1).model
    assert [e["id"] for e in model["endpoints"]] == ["GET /orders", "POST /orders"]  # solo el principal
    services = {(s["name"], s.get("role")): s for s in model["deployment"]["services"] if s.get("origin")}
    worker = services[("worker", "service")]
    assert worker["simulated"] is False and worker["repo"] == "acme/worker"
    assert worker["technology"] == "fastapi" and worker["endpoints"] == 1
    assert services[("redis", "cache")]["simulated"] is False  # componente del secundario
    assert ("postgres", "db") in services and services[("postgres", "db")]["repo"] == "acme/api"  # no se duplica
    assert [s["full_name"] for s in model["repo"]["sources"]] == ["acme/api", "acme/worker"]
    assert model["repo"]["source"]["framework"] == "express"  # source sigue siendo el principal


def test_external_step_naming_the_secondary_is_linked(store):
    client = make_client(store, RepoAnalyst())
    model = store.get_version(run(client)["project_id"], 1).model
    steps = {s["at"]: s for e in model["endpoints"] for s in e["steps"]}
    assert steps["src/app.js:5"]["service"] == "worker" and steps["src/app.js:5"]["linked_repo"] == "acme/worker"
    assert steps["src/app.js:6"]["service"] == "Stripe"  # no calza: sigue externo
    names = [s["name"] for s in model["deployment"]["services"]]
    assert "worker-http" not in names  # el externo que nombraba al secundario pasó a ser su servicio


def test_graph_has_both_services_with_repo_and_simulated(store):
    client = make_client(store, RepoAnalyst())
    model = store.get_version(run(client)["project_id"], 1).model
    graph = client.post("/graph", json={"model": model}).json()
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["api"]["repo"] == "acme/api" and nodes["api"]["simulated"] is True
    assert nodes["service:worker"]["kind"] == "service" and nodes["service:worker"]["simulated"] is False
    assert nodes["service:worker"]["repo"] == "acme/worker"
    assert nodes["external:stripe"]["simulated"] is True
    assert any(e["target"] == "service:worker" for e in graph["edges"])
    redis = [n for n in graph["nodes"] if n["label"] == "redis"]
    assert redis and redis[0]["simulated"] is False and redis[0]["repo"] == "acme/worker"


def test_secondary_failure_is_a_warning(store):
    client = make_client(store, RepoAnalyst(fail={"acme/worker"}))
    job = run(client)
    assert job["status"] == "done"
    assert job["repos"][1]["status"] == "failed" and job["repos"][1]["error_message"]
    model = store.get_version(job["project_id"], 1).model
    assert any("acme/worker" in w for w in model["warnings"])
    worker = next(s for s in model["deployment"]["services"] if s.get("role") == "service")
    assert worker["simulated"] is False and "error" in worker


def test_primary_failure_fails_the_ingestion(store):
    client = make_client(store, RepoAnalyst(fail={"acme/api"}))
    job = run(client)
    assert job["status"] == "failed" and job["error_message"].startswith("acme/api:")


@pytest.mark.parametrize(
    "body",
    [
        {"repos": [{"full_name": "acme/api"}, {"full_name": "acme/worker"}]},  # sin primary
        {"repos": [{"full_name": "acme/api"}, {"full_name": "acme/worker"}], "primary": "acme/otro"},
        {"repos": [{"full_name": f"acme/{n}"} for n in ("api", "worker", "c", "d", "e")], "primary": "acme/api"},
        {"repos": [{"full_name": "acme/api"}, {"full_name": "ACME/api"}], "primary": "acme/api"},
        {"repo_full_name": "acme/api", "repos": [{"full_name": "acme/api"}]},
    ],
)
def test_invalid_repo_lists_are_422(store, body):
    client = make_client(store, RepoAnalyst())
    assert client.post("/github/ingestions", json=body).status_code == 422


def test_old_single_repo_body_gives_the_same_model(store):
    client = make_client(store, RepoAnalyst())
    job = run(client, {"repo_full_name": "acme/api"})
    assert job["repos"] is None
    stored = store.get_version(job["project_id"], 1).model
    direct = model_from_tarball(TwoRepoGitHub().tarballs["acme/api"], "acme/api", RepoAnalyst(), SHA, "anthropic")
    sources = stored["repo"].pop("sources")
    assert sources == [{"full_name": "acme/api", "branch": "main", "commit": SHA, "primary": True,
                        "analysis": stored["repo"]["source"]["analysis"]}]  # fmt: skip
    for m in (stored, direct):  # la fecha del análisis no es parte del modelo comparable
        m.pop("assumptions", None)
    assert json.dumps(stored, sort_keys=True, default=str) == json.dumps(direct, sort_keys=True, default=str)


def test_projects_list_all_repos_primary_first(store):
    client = make_client(store, RepoAnalyst())
    job = run(client)
    listed = client.get(f"/projects/{job['project_id']}").json()["repositories"]
    assert [(r["fullName"], r["primary"]) for r in listed] == [("acme/api", True), ("acme/worker", False)]


def test_the_key_never_reaches_the_job(store):
    client = make_client(store, RepoAnalyst())
    job = run(client)
    assert KEY not in json.dumps(job)
    assert KEY not in json.dumps(store.get_version(job["project_id"], 1).model)
