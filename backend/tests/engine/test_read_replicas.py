"""JAJ-140: réplicas de lectura de la DB, de la operación al motor, el grafo y el costo."""

from __future__ import annotations

import pytest

from app.agent.ops import OpError, apply_ops, ops_json_schema
from app.costs.estimate import estimate_cost
from app.engine.simulate import REPLICA_WARNING, simulate
from app.models.architecture import READ_SHAPES, load_model
from app.models.graph import build_graph
from app.samples import load_sample


@pytest.fixture
def raw():
    # db.t4g.medium con créditos de CPU: a 50 req/s la CPU de la DB es el cuello de botella, por lecturas
    return load_sample("fastapi-realworld-example-app")


def run(model, rps=50):
    return simulate(load_model(model), "pico_normal", rps=rps, duration_s=20, seed=1)


def util(r, name):
    return next(x.utilization for x in r.resources if x.name == name)


def test_a_replica_takes_the_reads_off_the_primary(raw):
    before = run(raw)
    after = run(apply_ops(raw, [{"op": "add_read_replica", "count": 2}]).model)
    assert util(before, "db_cpu") > 0.85
    assert util(after, "db_cpu") < 0.2
    assert after.latency.p95_ms < before.latency.p95_ms / 2
    assert {"replica_cpu:1", "replica_pool:1", "replica_cpu:2", "replica_pool:2"} <= {x.name for x in after.resources}
    assert REPLICA_WARNING in after.warnings
    assert "api->db_replica" in (after.measured_edges or [])
    assert any((second.edge_calls or {}).get("api->db_replica") for second in after.series)


def test_reads_are_split_between_replicas(raw):
    r = run(apply_ops(raw, [{"op": "add_read_replica", "count": 2}]).model)
    one, two = util(r, "replica_cpu:1"), util(r, "replica_cpu:2")
    assert one > 0.2 and two > 0.2
    assert abs(one - two) < 0.15


def test_writes_stay_on_the_primary(raw):
    for e in raw["endpoints"]:  # solo escrituras: las réplicas no deberían hacer nada
        for s in e.get("steps", []):
            if s.get("shape") in READ_SHAPES:
                s["shape"] = "commit"
    r = run(apply_ops(raw, [{"op": "add_read_replica", "count": 1}]).model)
    assert util(r, "replica_cpu:1") == 0
    assert util(r, "db_cpu") > 0
    assert "api->db_replica" not in (r.measured_edges or [])
    assert any((second.edge_calls or {}).get("api->db") for second in r.series)


def test_replica_uses_cpu_credits_like_the_primary(raw):
    m = apply_ops(raw, [{"op": "add_read_replica", "count": 1}]).model
    assert m["deployment"]["db"]["read_replicas"]["cpu_credits"]["sustained_vcpu"]["value"] < 2
    sustained = load_model(m).db.replica_sustained_vcpu
    assert sustained is not None and sustained < load_model(m).db.replica_vcpu


def test_add_then_remove_leaves_the_model_and_cost_as_before(raw):
    added = apply_ops(raw, [{"op": "add_read_replica", "count": 2}]).model
    back = apply_ops(added, [{"op": "remove_read_replica"}]).model
    assert back["deployment"] == raw["deployment"]
    assert estimate_cost(back).total["value"] == estimate_cost(raw).total["value"]


def test_replica_count_is_an_assumption_unless_the_user_said_it(raw):
    agent = apply_ops(raw, [{"op": "add_read_replica", "count": 1}]).model["deployment"]["db"]["read_replicas"]
    assert agent["count"]["label"] == "SUPUESTO" and agent["count"]["needs_review"]
    assert agent["count"]["source"].startswith("Propuesta del agente")
    assert agent["routing"]["label"] == "SUPUESTO"
    quote = "pon dos réplicas de lectura"
    user = apply_ops(raw, [{"op": "add_read_replica", "count": 2, "quote": quote}]).model
    assert quote in user["deployment"]["db"]["read_replicas"]["count"]["source"]


def test_result_warns_about_routing_and_lag(raw):
    result = apply_ops(raw, [{"op": "add_read_replica", "count": 1}])
    assert any("retraso de replicación" in w for w in result.warnings)
    assert result.changes[0].startswith("DB: réplicas de lectura 1 × rds_postgres db.t4g.medium")


def test_cost_line_per_replica(raw):
    one = estimate_cost(apply_ops(raw, [{"op": "add_read_replica", "count": 1}]).model)
    two = estimate_cost(apply_ops(raw, [{"op": "add_read_replica", "count": 2}]).model)
    line = {x.id: x for x in two.lines}["db_replica"]
    assert line.node == "db_replica"
    assert line.usd_month["value"] == pytest.approx(2 * {x.id: x for x in one.lines}["db_replica"].usd_month["value"])


def test_graph_draws_the_replica_with_the_read_endpoints(raw):
    m = apply_ops(raw, [{"op": "add_read_replica", "count": 2}]).model
    g = build_graph(load_model(m), m)
    node = next(n for n in g.nodes if n.id == "db_replica")
    assert node.label == "Réplica de lectura ×2" and node.kind == "db"
    assert node.resources == ["replica_cpu:1", "replica_pool:1", "replica_cpu:2", "replica_pool:2"]
    edges = {(e.source, e.target) for e in g.edges}
    assert ("api", "db_replica") in edges and ("api", "db") in edges


def test_without_replicas_the_graph_and_run_do_not_change(raw):
    g = build_graph(load_model(raw), raw)
    assert all(n.id != "db_replica" for n in g.nodes)
    assert all(not x.name.startswith("replica_") for x in run(raw).resources)


@pytest.mark.parametrize(
    ("ops", "message"),
    [
        ([{"op": "remove_read_replica"}], "no tiene réplicas de lectura"),
        ([{"op": "add_read_replica", "count": 1, "plan": "db.x9.huge"}], "no tiene el plan 'db.x9.huge'"),
    ],
)
def test_clear_errors(raw, ops, message):
    with pytest.raises(OpError, match=message):
        apply_ops(raw, ops)


def test_schema_lists_the_new_ops():
    schema = str(ops_json_schema())
    assert "add_read_replica" in schema and "remove_read_replica" in schema
