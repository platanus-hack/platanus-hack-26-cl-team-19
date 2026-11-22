"""Tests de las tools del agente (JAJ-67) sobre un proyecto en memoria."""

import pytest

from app.agent.tools import AgentTools, Limiter, Limits, _numbers_in
from app.api.store import InMemoryProjectStore
from app.samples import load_sample

QUOTE = "recibimos 100.000 pedidos al día y en CyberDay 20×, el SLO es p95 < 300 ms"


@pytest.fixture
def store():
    return InMemoryProjectStore()


@pytest.fixture
def project(store):
    return store.create("tienda", load_sample("full-stack-fastapi-template"), "full-stack-fastapi-template")


@pytest.fixture
def tools(store):
    return AgentTools(store, None)


def test_schemas_cover_every_tool(tools):
    names = {s["name"] for s in tools.schemas()}
    assert names == {
        "list_projects",
        "get_model",
        "list_assumptions",
        "list_scenarios",
        "simulate",
        "compare",
        "estimate_cost",
        "ops_schema",
        "propose_version",
        "set_traffic",
        "set_deployment",
        "set_goals",
        "submit_architecture",
    }
    assert all(s["input_schema"].get("additionalProperties") is False for s in tools.schemas())


@pytest.mark.parametrize(
    "quote,expected",
    [
        ("100.000 pedidos", 100000),
        ("100,000 orders", 100000),
        ("unos 100k usuarios", 100000),
        ("2 millones al mes", 2_000_000),
        ("medio vCPU, 0,5", 0.5),
        ("CyberDay 20×", 20),
        ("p95 < 300 ms", 300),
    ],
)
def test_numbers_in_quote(quote, expected):
    assert any(abs(n - expected) < 1e-9 for n in _numbers_in(quote))


def test_unknown_tool_and_arguments_are_rejected(tools, project):
    assert "No existe la tool" in tools.call("hackear", {})["error"]
    err = tools.call("simulate", {"project_id": project.id, "rps": 5000})["error"]
    assert "rps" in err and "Extra inputs are not permitted" in err


def test_other_owner_cannot_see_the_project(store, project):
    other = AgentTools(store, "00000000-0000-0000-0000-000000000001")
    assert other.call("list_projects", {}) == {"projects": []}
    assert "No existe el proyecto" in other.call("simulate", {"project_id": project.id})["error"]


def test_set_traffic_requires_numbers_in_quote(tools, project):
    err = tools.call(
        "set_traffic",
        {"project_id": project.id, "volume": 200000, "unit": "orders_per_day", "quote": QUOTE},
    )["error"]
    assert "volume = 200000 no aparece en quote" in err
    assert len(tools.store.get(project.id).versions) == 1  # no guardó nada


def test_set_traffic_orders_per_day(tools, store, project):
    r = tools.call(
        "set_traffic",
        {"project_id": project.id, "volume": 100000, "unit": "orders_per_day", "peak_factor": 20, "quote": QUOTE},
    )
    assert (r["version"], r["parent"]) == (2, 1)
    v2 = store.get_version(project.id, 2)
    assert v2.origin == "agente"
    # 100.000 pedidos / 2 % de conversión × 17 requests/sesión / 86.400 s × K_hora 2,5 (JAJ-11)
    assert r["peak_rps"]["value"] == pytest.approx(100000 / 0.02 * 17 / 86400 * 2.5, rel=1e-3)
    assert r["peak_rps"]["label"] == "SUPUESTO" and QUOTE in r["peak_rps"]["source"]
    assert v2.model["traffic"]["declared"]["quote"] == QUOTE
    cyber = {s.name: s for s in store.list_scenarios(project.id)}["cyberday"]
    assert (cyber.multiplier, cyber.description) == (20, QUOTE)


def test_set_goals_and_simulate_checks_them(tools, project):
    assert (
        "slo_p95_ms = 250"
        in tools.call("set_goals", {"project_id": project.id, "slo_p95_ms": 250, "quote": QUOTE})["error"]
    )
    g = tools.call("set_goals", {"project_id": project.id, "slo_p95_ms": 300, "quote": QUOTE})
    assert g["goals"]["slo_p95_ms"] == 300
    pct = tools.call(
        "set_goals", {"project_id": project.id, "slo_error_rate": 0.01, "quote": "menos de 1 % de errores"}
    )
    assert pct["goals"] == {"slo_p95_ms": 300, "slo_error_rate": 0.01, "budget_usd_month": None}
    r = tools.call("simulate", {"project_id": project.id, "scenario": "cyberday"})
    assert r["bottleneck"]["line"] == "backend/app/core/security.py:36"
    p95 = r["goals"]["p95"]
    assert p95["goal_ms"] == 300 and p95["ok"] is False and r["goals"]["meets_all"] is False
    assert r["provenance"]["label"] == "SUPUESTO" and "60 s simulados" in r["provenance"]["source"]


def test_high_traffic_shortens_the_simulation(tools, project):
    tools.call(
        "set_traffic",
        {"project_id": project.id, "volume": 100000, "unit": "orders_per_day", "peak_factor": 20, "quote": QUOTE},
    )
    r = tools.call("simulate", {"project_id": project.id, "scenario": "cyberday"})
    assert "error" not in r, r
    assert r["rps"] > 40000 and "s simulados" in r["provenance"]["source"]
    assert "60 s simulados" not in r["provenance"]["source"]  # el servidor la acortó, no el LLM


def test_unknown_scenario(tools, project):
    assert (
        "no tiene el escenario 'blackfriday'"
        in tools.call("simulate", {"project_id": project.id, "scenario": "blackfriday"})["error"]
    )


def test_propose_version_and_compare(tools, store, project):
    bad = tools.call("propose_version", {"project_id": project.id, "ops": [{"op": "change_db_plan", "plan": "nope"}]})
    assert "no tiene el plan 'nope'" in bad["error"]
    v = tools.call(
        "propose_version",
        {"project_id": project.id, "ops": [{"op": "scale_api", "replicas": 4}], "note": "API ×4"},
    )
    assert (v["version"], v["parent"]) == (2, 1) and store.get_version(project.id, 2).origin == "agente"
    c = tools.call("compare", {"project_id": project.id, "a": 1, "b": 2, "scenario": "cyberday"})
    assert c["delta"]["p95_ms"]["b"] < c["delta"]["p95_ms"]["a"]
    assert c["delta"]["usd_month"] > 0 and "v2 cuesta +US$" in c["summary"]
    assert c["a"]["usd_month"]["label"] and c["a"]["usd_month"]["source"]


def test_add_cache_without_quote_is_rejected(tools, project):
    r = tools.call(
        "propose_version",
        {"project_id": project.id, "ops": [{"op": "add_cache", "endpoint": "GET /users/", "hit_ratio": 0.9}]},
    )
    assert "quote" in r["error"]


def test_set_deployment(tools, store, project):
    assert (
        "no aparece en quote"
        in tools.call(
            "set_deployment",
            {"project_id": project.id, "field": "api.replicas", "value": "5", "quote": "tenemos 3 réplicas"},
        )["error"]
    )
    r = tools.call(
        "set_deployment",
        {"project_id": project.id, "field": "api.replicas", "value": "3", "quote": "tenemos 3 réplicas"},
    )
    assert store.get_version(project.id, r["version"]).model["deployment"]["api"]["replicas"]["value"] == 3
    plan = tools.call(
        "set_deployment",
        {"project_id": project.id, "field": "db.plan", "value": "large", "quote": "usamos Supabase large"},
    )
    assert "error" not in plan, plan
    neon = tools.call(
        "set_deployment",
        {"project_id": project.id, "field": "db.plan", "value": "1cu", "quote": "la base está en Neon, 1 CU"},
    )
    db = store.get_version(project.id, neon["version"]).model["deployment"]["db"]
    assert (db["provider"], db["plan"]) == ("neon", "1cu")  # el plan dice el proveedor (JAJ-143)


def test_read_tools(tools, project):
    m = tools.call("get_model", {"project_id": project.id})
    assert m["version"] == 1 and m["endpoints"][0]["at"] and m["assumptions"] > 0
    assert tools.call("list_assumptions", {"project_id": project.id})["total"] == m["assumptions"]
    assert {s["name"] for s in tools.call("list_scenarios", {"project_id": project.id})["scenarios"]} == {
        "cyberday",
        "pico_normal",
    }
    cost = tools.call("estimate_cost", {"project_id": project.id})
    assert cost["total"]["label"] and cost["lines"]
    assert "anyOf" in tools.call("ops_schema", {}) or tools.call("ops_schema", {})


def test_limits(store, project):
    t = AgentTools(store, None, Limiter(Limits(calls_per_minute=2, simulations_per_day=1)))
    assert "error" not in t.call("simulate", {"project_id": project.id})
    assert "simulaciones por día" in t.call("simulate", {"project_id": project.id})["error"]
    assert "llamadas por minuto" in t.call("list_projects", {})["error"]


def test_many_errors_never_meet_the_goals(tools, project):
    """Con 85 % de errores el p95 (solo de las exitosas) puede quedar bajo la meta: igual no cumple."""
    tools.call(
        "set_traffic",
        {"project_id": project.id, "volume": 100000, "unit": "orders_per_day", "peak_factor": 20, "quote": QUOTE},
    )
    tools.call("set_goals", {"project_id": project.id, "slo_p95_ms": 300, "quote": QUOTE})
    v = tools.call(
        "propose_version",
        {"project_id": project.id, "ops": [{"op": "scale_api", "replicas": 50, "vcpu": 4}, {"op": "add_pooler"}]},
    )
    r = tools.call("simulate", {"project_id": project.id, "version": v["version"], "scenario": "cyberday"})
    assert r["error_rate"] > 0.5, r["error_rate"]
    goals = r["goals"]
    assert goals["errors"]["ok"] is False and goals["errors"]["label"] == "SUPUESTO"
    assert goals["meets_all"] is False
