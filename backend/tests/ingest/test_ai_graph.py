"""La arquitectura que propone la IA, para cualquier framework (JAJ-85, JAJ-86, ADR 0002)."""

import copy

import pytest
from pydantic import ValidationError

from app.agent.tools import AgentTools
from app.api.store import InMemoryProjectStore
from app.ingest.ai_graph import ArchitectureSubmission, build_from_ai
from app.ingest.iac import scan_deployment
from app.models import load_model
from app.models.graph import build_graph

EXPRESS = {
    "repo": "acme/tienda-express",
    "framework": "express",
    "language": "typescript",
    "commit": "77e550a",
    "endpoints": [
        {
            "method": "GET",
            "path": "/orders",
            "handler": "listOrders",
            "file": "src/routes/orders.ts",
            "line": 12,
            "why": "router.get('/orders', listOrders)",
            "is_async": True,
            "effects": [
                {
                    "kind": "db",
                    "op": "read",
                    "shape": "range",
                    "entity": "Order",
                    "detail": "prisma.order.findMany",
                    "file": "src/routes/orders.ts",
                    "line": 14,
                    "why": "findMany con take: 20",
                },
                {
                    "kind": "db",
                    "op": "read",
                    "shape": "pk",
                    "entity": "Customer",
                    "detail": "prisma.customer.findUnique",
                    "file": "src/routes/orders.ts",
                    "line": 17,
                    "in_loop": True,
                    "why": "dentro de orders.map: una consulta por pedido",
                },
            ],
        },
        {
            "method": "POST",
            "path": "/checkout",
            "handler": "checkout",
            "file": "src/routes/checkout.ts",
            "line": 8,
            "why": "router.post('/checkout', checkout)",
            "is_async": True,
            "effects": [
                {
                    "kind": "external",
                    "service": "Stripe",
                    "detail": "stripe.paymentIntents.create",
                    "file": "src/routes/checkout.ts",
                    "line": 20,
                    "why": "SDK de Stripe",
                },
                {
                    "kind": "db",
                    "op": "write",
                    "shape": "commit",
                    "detail": "prisma.order.create",
                    "file": "src/routes/checkout.ts",
                    "line": 25,
                    "why": "create hace su propia transacción",
                },
                {
                    "kind": "cache",
                    "detail": "redis.del(cart)",
                    "file": "src/routes/checkout.ts",
                    "line": 27,
                    "why": "borra el carro",
                },
            ],
        },
    ],
    "components": [
        {
            "name": "redis",
            "role": "cache",
            "technology": "Redis 7",
            "file": "docker-compose.yml",
            "line": 10,
            "why": "servicio redis del compose",
        },
        {
            "name": "Stripe",
            "role": "external",
            "technology": "Stripe API",
            "file": "src/lib/stripe.ts",
            "line": 1,
            "why": "new Stripe(process.env.STRIPE_KEY)",
        },
        {
            "name": "uploads",
            "role": "storage",
            "technology": "S3",
            "file": "src/lib/s3.ts",
            "line": 4,
            "why": "new S3Client para las fotos de productos",
        },
    ],
}


def submission(**changes) -> dict:
    data = copy.deepcopy(EXPRESS)
    data.update(changes)
    return data


def test_express_repo_gets_a_v1_with_ai_provenance():
    model = build_from_ai(ArchitectureSubmission.model_validate(EXPRESS))
    load_model(model)  # el motor lo carga
    assert model["repo"]["source"] == {
        "kind": "ia",
        "via": "cli",
        "framework": "express",
        "language": "typescript",
        "commit": "77e550a",
    }
    orders = model["endpoints"][0]
    assert orders["origin"]["kind"] == "ia" and orders["at"] == "src/routes/orders.ts:12"
    # el número sale del catálogo, pero la clasificación de la IA lo deja como ESTIMADO como máximo
    pk = orders["steps"][1]
    assert pk["time"]["label"] == "ESTIMADO" and "src/routes/orders.ts:17" in pk["time"]["source"]
    assert pk["repeat"]["unit"] == "×"  # N+1
    assert "(Customer)" in pk["detail"]
    # la CPU base se midió en FastAPI: en Express es un supuesto
    assert orders["api_cpu_ms"]["label"] == "SUPUESTO"
    # pool y workers: el catálogo describe uvicorn y SQLAlchemy, así que en Express quedan por revisar
    api, pool = model["deployment"]["api"], model["deployment"]["db"]["pool_per_worker"]
    assert api["workers"]["needs_review"] and "express" in api["workers"]["source"]
    assert "uvicorn" not in api["workers"]["source"]
    assert pool["library"] == "desconocida" and pool["pool_size"]["needs_review"]
    assert "ORM o driver" in pool["pool_size"]["source"]
    services = {s["name"]: s for s in model["deployment"]["services"]}
    assert services["uploads"]["at"] == "src/lib/s3.ts:4" and services["uploads"]["origin"]["why"]


def test_every_ai_endpoint_step_and_component_has_provenance():
    model = build_from_ai(ArchitectureSubmission.model_validate(EXPRESS))
    for ep in model["endpoints"]:
        assert ep["origin"]["source"]
        for step in ep["steps"] + ep["alternatives"]:
            assert step["origin"]["kind"] == "ia" and step["at"]
    for service in model["deployment"]["services"]:
        assert service["origin"]["kind"] == "ia" and service["at"]


def test_diagram_shows_named_components():
    model = build_from_ai(ArchitectureSubmission.model_validate(EXPRESS))
    graph = build_graph(load_model(model), model).to_dict()
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["external:stripe"]["label"] == "Stripe"
    assert nodes["external:stripe"]["details"]["at"] == "src/lib/stripe.ts:1"
    assert nodes["cache"]["details"]["technology"] == "Redis 7"
    assert nodes["component:uploads"]["kind"] == "storage"  # sin aristas, pero en el diagrama
    edges = {e["id"]: e for e in graph["edges"]}
    assert edges["api->external:stripe"]["refs"] == ["src/routes/checkout.ts:20"]


@pytest.mark.parametrize(
    "path, value, message",
    [
        # números: ni tiempos ni filas
        (("endpoints", 0, "effects", 0, "time_ms"), 3.5, "Extra inputs"),
        (("endpoints", 0, "effects", 0, "rows"), 1000, "Extra inputs"),
        (("endpoints", 0, "latency_ms"), 40, "Extra inputs"),
        # evidencia obligatoria
        (("endpoints", 0, "effects", 0, "line"), None, "line"),
        (("endpoints", 0, "why"), None, "why"),
        (("components", 0, "file"), "/etc/passwd", "ruta relativa"),
        (("components", 0, "file"), "../secreto.ts", "ruta relativa"),
        # formas del catálogo, no inventadas
        (("endpoints", 0, "effects", 0, "shape"), "fast_query", "shape de db"),
        (("endpoints", 1, "effects", 0, "service"), None, "necesita service"),
        # on_miss solo con lecturas a la DB
        (
            ("endpoints", 1, "effects", 2, "on_miss"),
            [{"kind": "cpu", "shape": "password_hash", "detail": "x", "file": "a.ts", "line": 1, "why": "xxx"}],
            "on_miss lleva",
        ),
    ],
)
def test_submission_rejects_numbers_missing_evidence_and_unknown_shapes(path, value, message):
    data = submission()
    node = data
    for key in path[:-1]:
        node = node[key]
    if value is None:
        node.pop(path[-1])
    else:
        node[path[-1]] = value
    with pytest.raises(ValidationError, match=message):
        ArchitectureSubmission.model_validate(data)


def test_repeated_endpoints_are_rejected():
    data = submission()
    data["endpoints"].append(copy.deepcopy(data["endpoints"][0]))
    with pytest.raises(ValidationError, match="endpoints repetidos"):
        ArchitectureSubmission.model_validate(data)


def test_submit_architecture_creates_a_project_that_simulates():
    tools = AgentTools(InMemoryProjectStore(), None)
    out = tools.call("submit_architecture", EXPRESS)
    assert out["version"] == 1 and out["endpoints_from_ai"] == 2 and out["components_from_ai"] == 3
    sim = tools.call("simulate", {"project_id": out["project_id"], "scenario": "pico_normal"})
    assert "error" not in sim, sim
    assert sim["provenance"]["label"] == "SUPUESTO"


def test_editor_chat_does_not_offer_submit_architecture():
    tools = AgentTools(InMemoryProjectStore(), None)
    assert "submit_architecture" in [s["name"] for s in tools.schemas()]
    assert "submit_architecture" not in [s["name"] for s in tools.schemas(cli=False)]


def test_resubmitting_replaces_the_architecture_and_keeps_the_deployment():
    store = InMemoryProjectStore()
    tools = AgentTools(store, None)
    first = tools.call("submit_architecture", EXPRESS)
    pid = first["project_id"]
    declared = tools.call(
        "set_deployment", {"project_id": pid, "field": "api.replicas", "value": "3", "quote": "corremos 3 réplicas"}
    )
    assert "error" not in declared, declared
    data = submission()
    data["endpoints"] = data["endpoints"][:1]
    out = tools.call("submit_architecture", {**data, "project_id": pid})
    v3 = store.get_version(pid, out["version"])
    assert v3.origin == "agente" and [ep["id"] for ep in v3.model["endpoints"]] == ["GET /orders"]
    assert v3.model["deployment"]["api"]["replicas"]["value"] == 3  # lo que dijo el usuario se queda


def test_iac_wins_over_ai_components(tmp_path):
    (tmp_path / "compose.yml").write_text("services:\n  redis:\n    image: redis:7.2\n", encoding="utf-8")
    model = build_from_ai(ArchitectureSubmission.model_validate(EXPRESS), iac=scan_deployment(tmp_path).to_dict())
    redis = [s for s in model["deployment"]["services"] if s["name"] == "redis"]
    assert len(redis) == 1 and "origin" not in redis[0] and redis[0]["at"].startswith("compose.yml")


@pytest.mark.parametrize(
    "written, label",
    [("const pool = new Pool({ max: 20 })", "OBSERVADO"), ("const pool = new Pool({ max: 10 })", None)],
    ids=["el-numero-esta", "la-ia-se-equivoco"],
)
def test_observations_are_checked_against_the_cited_line(tmp_path, written, label):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "db.ts").write_text(f"import {{ Pool }} from 'pg'\n{written}\n", encoding="utf-8")
    obs = {"field": "db.pool_size", "value": 20, "file": "src/db.ts", "line": 2, "why": "max del Pool de pg"}
    sub = ArchitectureSubmission.model_validate(submission(observations=[obs]))
    model = build_from_ai(sub, via="ingesta", root=tmp_path)
    pool = model["deployment"]["db"]["pool_per_worker"]["pool_size"]
    if label:
        assert (pool["value"], pool["label"], pool["at"]) == (20, "OBSERVADO", "src/db.ts:2")
    else:
        assert pool["label"] == "SUPUESTO"  # se descartó: el número no está en esa línea
        assert any("no está en esa línea" in w for w in model["deployment"]["iac"]["warnings"])


def test_observations_from_the_cli_stay_estimated():
    obs = {"field": "api.workers", "value": 4, "file": "ecosystem.config.js", "line": 5, "why": "instances: 4"}
    model = build_from_ai(ArchitectureSubmission.model_validate(submission(observations=[obs])))
    workers = model["deployment"]["api"]["workers"]
    assert (workers["value"], workers["label"], workers["needs_review"]) == (4, "ESTIMADO", True)
