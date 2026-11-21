"""La arquitectura que propone la IA del usuario para repos que no son FastAPI (JAJ-85, JAJ-86)."""

import copy
import json

import pytest
from pydantic import ValidationError

from app.agent.tools import AgentTools
from app.api.store import InMemoryProjectStore
from app.ingest.ai_graph import ArchitectureSubmission, build_from_ai
from app.ingest.build_model import NoEndpoints, build
from app.models import load_model
from app.models.graph import build_graph
from app.samples import load_sample

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


def test_diagram_shows_named_components_the_extractor_cannot_see():
    model = build_from_ai(ArchitectureSubmission.model_validate(EXPRESS))
    graph = build_graph(load_model(model), model).to_dict()
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["external:stripe"]["label"] == "Stripe"
    assert nodes["external:stripe"]["details"]["at"] == "src/lib/stripe.ts:1"
    assert nodes["cache"]["details"]["technology"] == "Redis 7"
    assert nodes["component:uploads"]["kind"] == "storage"  # sin aristas, pero en el diagrama
    edges = {e["id"]: e for e in graph["edges"]}
    assert edges["api->external:stripe"]["refs"] == ["src/routes/checkout.ts:20"]


def test_fastapi_models_do_not_change():
    raw = load_sample("full-stack-fastapi-template")
    assert "origin" not in json.dumps(raw)
    nodes = [n["id"] for n in build_graph(load_model(raw), raw).to_dict()["nodes"]]
    assert nodes == ["api", "db"]


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


def test_no_endpoints_message_points_to_the_cli(tmp_path):
    (tmp_path / "server.js").write_text("app.get('/x', (req, res) => res.send('ok'))\n")
    with pytest.raises(NoEndpoints, match="submit_architecture"):
        build(tmp_path, {})


def test_submit_architecture_creates_a_project_that_simulates():
    tools = AgentTools(InMemoryProjectStore(), None)
    out = tools.call("submit_architecture", EXPRESS)
    assert out["version"] == 1 and out["endpoints_from_ai"] == 2 and out["components_from_ai"] == 3
    sim = tools.call("simulate", {"project_id": out["project_id"], "scenario": "pico_normal"})
    assert "error" not in sim, sim
    assert sim["provenance"]["label"] == "SUPUESTO"


def test_code_wins_when_adding_to_an_extracted_project():
    store = InMemoryProjectStore()
    project = store.create("tienda", load_sample("full-stack-fastapi-template"), None)
    v1 = store.get_version(project.id, 1).model
    taken = next(ep for ep in v1["endpoints"] if ep["method"] == "GET")
    data = submission(framework="fastapi", language="python")
    data["endpoints"][0].update(method="GET", path=taken["path"])  # ya lo encontró el extractor
    out = AgentTools(store, None).call("submit_architecture", {**data, "project_id": project.id})
    assert out["version"] == 2
    assert out["ignored_because_code_found_them"]["endpoints"] == [taken["id"]]
    v2 = store.get_version(project.id, 2)
    assert v2.origin == "agente"
    same = next(ep for ep in v2.model["endpoints"] if ep["id"] == taken["id"])
    assert "origin" not in same  # el del extractor quedó intacto
    assert len(v2.model["endpoints"]) == len(v1["endpoints"]) + 1


def test_editor_chat_does_not_offer_submit_architecture():
    tools = AgentTools(InMemoryProjectStore(), None)
    assert "submit_architecture" in [s["name"] for s in tools.schemas()]
    assert "submit_architecture" not in [s["name"] for s in tools.schemas(cli=False)]
