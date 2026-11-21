"""Tests del lector de archivos de despliegue (JAJ-60), con repos mínimos armados en tmp_path."""

from pathlib import Path

import pytest

from app.ingest import scan_deployment
from app.ingest.iac import QUESTIONS


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def services(findings):
    return {s.name: s for s in findings.services}


# Lo esencial de full-stack-fastapi-template (77e550a): compose.yml + override + Dockerfile con CMD exec
TEMPLATE = {
    "compose.yml": """services:

  proxy:
    image: traefik:v3.7

  db:
    image: postgres:18
    environment:
      - POSTGRES_DB=app

  adminer:
    image: adminer

  backend:
    image: backend:latest
    build:
      context: .
      dockerfile: backend/Dockerfile
""",
    "compose.override.yml": """services:
  backend:
    ports:
      - "8000:8000"
  playwright:
    build:
      context: .
      dockerfile: frontend/Dockerfile.playwright
""",
    "backend/Dockerfile": """FROM python:3.14
WORKDIR /app/backend/
CMD ["fastapi", "run", "--workers", "4"]
""",
    "frontend/Dockerfile.playwright": "FROM mcr.microsoft.com/playwright\n",
    ".github/workflows/deploy.yml": "jobs:\n  deploy:\n    steps:\n      - run: uv run fastapi deploy\n",
}


def test_template_compose_gives_services_and_workers(tmp_path):
    f = scan_deployment(write(tmp_path, TEMPLATE))
    svc = services(f)
    assert {n: s.role for n, s in svc.items()} == {
        "proxy": "proxy",
        "db": "db",
        "adminer": "other",
        "backend": "api",
        "playwright": "other",  # se construye, pero no corre un servidor
    }
    assert (svc["db"].engine, svc["db"].version, svc["db"].at) == ("postgres", "18", "compose.yml:6")
    w = svc["backend"].workers
    assert (w["value"], w["label"], w["at"]) == (4, "OBSERVADO", "backend/Dockerfile:3")
    out = f.to_dict()
    assert out["observed"]["api.workers"]["value"] == 4
    assert out["observed"]["api.provider"]["value"] == "fastapi cloud"
    assert {m["field"] for m in out["missing"]} == {"api.replicas", "api.vcpu", "api.memory_gb", "db.plan"}
    assert [x["kind"] for x in out["files"]].count("compose") == 2


def test_repo_without_iac_is_empty_and_asks_everything(tmp_path):
    write(tmp_path, {"app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n"})
    out = scan_deployment(tmp_path).to_dict()
    assert out["files"] == [] and out["services"] == [] and out["observed"] == {}
    assert [m["field"] for m in out["missing"]] == list(QUESTIONS)
    assert all(m["question"].startswith("¿") for m in out["missing"])


def test_compose_replicas_limits_and_worker(tmp_path):
    write(
        tmp_path,
        {
            "docker-compose.yml": """services:
  api:
    build: .
    command: gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 3
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: "0.5"
          memory: 512M
  worker:
    build: .
    command: celery -A app.worker worker --concurrency 8
  cache:
    image: redis:7-alpine
  broker:
    image: rabbitmq:3-management
"""
        },
    )
    out = scan_deployment(tmp_path).to_dict()
    svc = {s["name"]: s for s in out["services"]}
    assert {n: s["role"] for n, s in svc.items()} == {
        "api": "api",
        "worker": "worker",
        "cache": "cache",
        "broker": "queue",
    }
    api = svc["api"]
    assert (api["replicas"]["value"], api["replicas"]["at"]) == (2, "docker-compose.yml:6")
    assert (api["vcpu"]["value"], api["memory_gb"]["value"]) == (0.5, 0.512)
    assert api["workers"]["value"] == 3
    assert svc["worker"]["workers"]["value"] == 8
    assert {"api.replicas", "api.vcpu", "api.memory_gb", "api.workers"} <= set(out["observed"])


def test_uvicorn_without_workers_is_one_process(tmp_path):
    write(
        tmp_path,
        {"Dockerfile": "FROM python:3.12\nCMD poetry run alembic upgrade head && \\\n    uvicorn app.main:app\n"},
    )
    w = scan_deployment(tmp_path).to_dict()["observed"]["api.workers"]
    assert (w["value"], w["at"]) == (1, "Dockerfile:2")
    assert "1 proceso por defecto" in w["source"]


def test_kubernetes_deployment_and_hpa(tmp_path):
    write(
        tmp_path,
        {
            "k8s/api.yaml": """apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: api
          image: ghcr.io/acme/api:1.2
          args: ["uvicorn", "app.main:app", "--workers", "2"]
          resources:
            requests:
              cpu: 250m
            limits:
              cpu: 500m
              memory: 1Gi
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
spec:
  scaleTargetRef:
    name: api
  minReplicas: 3
  maxReplicas: 10
"""
        },
    )
    api = services(scan_deployment(tmp_path))["api"]
    assert api.role == "api"
    assert (api.replicas["value"], api.replicas["at"]) == (10, "k8s/api.yaml:28")  # el máximo del HPA
    assert (api.vcpu["value"], api.memory_gb["value"], api.workers["value"]) == (0.5, 1.0, 2)


def test_fly_toml(tmp_path):
    write(
        tmp_path,
        {
            "fly.toml": """app = "tienda"

[http_service]
  internal_port = 8000
  min_machines_running = 2

[[vm]]
  cpus = 2
  memory = "1gb"
"""
        },
    )
    f = scan_deployment(tmp_path)
    s = services(f)["tienda"]
    assert (s.replicas["value"], s.replicas["at"]) == (2, "fly.toml:5")
    assert (s.vcpu["value"], s.vcpu["at"], s.memory_gb["value"]) == (2.0, "fly.toml:8", 1.0)
    assert f.to_dict()["observed"]["api.provider"]["value"] == "fly"


def test_render_yaml(tmp_path):
    write(
        tmp_path,
        {
            "render.yaml": """services:
  - type: web
    name: api
    plan: standard
    numInstances: 2
    startCommand: uvicorn app.main:app --workers 4
  - type: worker
    name: jobs
databases:
  - name: tienda-db
    plan: basic-1gb
"""
        },
    )
    svc = {s["name"]: s for s in scan_deployment(tmp_path).to_dict()["services"]}
    assert (svc["api"]["plan"]["value"], svc["api"]["replicas"]["value"], svc["api"]["workers"]["value"]) == (
        "standard",
        2,
        4,
    )
    assert svc["jobs"]["role"] == "worker"
    assert (svc["tienda-db"]["role"], svc["tienda-db"]["plan"]["value"]) == ("db", "basic-1gb")


def test_terraform_aws(tmp_path):
    write(
        tmp_path,
        {
            "infra/main.tf": """resource "aws_db_instance" "main" {
  engine         = "postgres"
  instance_class = "db.t4g.medium" # sube a m7g en CyberDay
  tags = {
    instance_class = "no-es-este"
  }
}

resource "aws_ecs_service" "api" {
  desired_count = 2
}

resource "aws_ecs_task_definition" "api" {
  cpu    = "1024"
  memory = "2048"
}

resource "aws_elasticache_cluster" "cache" {
  node_type = "cache.t4g.micro"
}
"""
        },
    )
    f = scan_deployment(tmp_path)
    svc = services(f)
    assert (svc["main"].role, svc["main"].engine) == ("db", "postgres")
    assert (svc["main"].plan["value"], svc["main"].plan["at"]) == ("db.t4g.medium", "infra/main.tf:3")
    api = svc["api"]
    assert (api.replicas["value"], api.vcpu["value"], api.memory_gb["value"]) == (2, 1.0, 2.0)
    assert svc["cache"].plan["value"] == "cache.t4g.micro"
    assert f.to_dict()["observed"]["db.plan"]["value"] == "db.t4g.medium"


def test_procfile(tmp_path):
    write(tmp_path, {"Procfile": "web: gunicorn app.main:app -w 5\nworker: rq worker default\n"})
    svc = services(scan_deployment(tmp_path))
    assert (svc["web"].role, svc["web"].workers["value"]) == ("api", 5)
    assert svc["worker"].role == "worker"


@pytest.mark.parametrize(
    "files",
    [
        {"compose.yml": "services: [esto no es: un mapping"},
        {"fly.toml": "app = "},
        {"k8s/x.yaml": "kind: Deployment\nspec: : :\n"},
    ],
)
def test_invalid_files_warn_instead_of_failing(tmp_path, files):
    out = scan_deployment(write(tmp_path, files)).to_dict()
    assert out["services"] == []
    assert out["warnings"] and "inválido" in out["warnings"][0]


def test_skips_vendored_dirs(tmp_path):
    write(tmp_path, {"node_modules/pkg/docker-compose.yml": "services:\n  db:\n    image: postgres\n"})
    assert scan_deployment(tmp_path).to_dict()["files"] == []
