"""Dónde está desplegado cada componente (JAJ-143) y su tecnología (JAJ-87).

Con repos mínimos en ``tmp_path``: lo que dice el repo (URL de conexión de ejemplo, render.yaml,
vercel.json, compose) elige el perfil del catálogo, y ese perfil cambia la simulación y el costo.
"""

import copy
import json

import pytest

from app.agent import OpError, apply_ops
from app.catalog import deploy
from app.costs import estimate_cost
from app.engine import simulate
from app.ingest.ai_graph import ArchitectureSubmission, build_from_ai
from app.ingest.iac import scan_deployment
from app.models import load_model
from app.models.graph import build_graph
from app.samples import load_sample
from tests.ingest.test_ai_graph import EXPRESS

LABELS = {"OBSERVADO", "CALIBRADO", "ESTIMADO", "SUPUESTO"}


def write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def ingest(root, answers=None):
    sub = ArchitectureSubmission.model_validate(EXPRESS)
    return build_from_ai(sub, answers, iac=scan_deployment(root).to_dict(), root=root)


def p95(model, rps, seed=1):
    return simulate(load_model(model), "custom", rps=rps, seed=seed, duration_s=20).latency.p95_ms


# --- catálogo ---------------------------------------------------------------------------------------


def test_every_profile_number_has_provenance():
    for provider, plans in deploy.db_providers().items():
        for plan in plans:
            prof = deploy.db_profile(provider, plan, "test")
            for key in ("vcpu", "max_connections", "usd_month", "cpu_core_factor", "network_rtt_ms"):
                assert prof[key]["label"] in LABELS and prof[key]["source"], (provider, plan, key)
    one = {"value": 1, "unit": "réplicas", "label": "SUPUESTO", "source": "test"}
    for provider, plans in deploy.app_providers().items():
        for plan in plans or [None]:
            prof = deploy.app_profile(provider, plan, one, one, one, "test")
            assert prof["usd_month"]["source"] and prof["cpu_core_factor"]["label"] in LABELS
    for provider, plans in deploy.frontend_providers().items():
        for plan in plans:
            assert deploy.frontend_profile(provider, plan, "test")["usd_month"]["label"] == "ESTIMADO"


def test_neon_price_comes_from_the_jaj11_prices():
    """El US$/CU-hora de Neon es el de manual.json (JAJ-11), no un número nuevo del catálogo."""
    from app.costs.prices import manual_block

    cu_hour = manual_block("neon")["cu_hour"]["launch"]
    assert deploy.db_profile("neon", "2cu", "test")["usd_month"]["value"] == round(2 * cu_hour * 730, 2)


def test_unknown_plan_lists_what_exists():
    with pytest.raises(deploy.UnknownPlan, match="0.25cu, 0.5cu, 1cu"):
        deploy.db_profile("neon", "64cu", "test")
    with pytest.raises(deploy.UnknownPlan, match="Hay: .*fly: performance-1x"):
        deploy.app_profile("heroku", None, {}, {}, {}, "test")


# --- lo que dice el repo ----------------------------------------------------------------------------


def test_neon_url_in_env_example_picks_neon_and_asks_the_plan(tmp_path):
    write(tmp_path, {".env.example": "DATABASE_URL=postgres://u:p@ep-cool-1.us-east-2.aws.neon.tech/app\n"})
    db = ingest(tmp_path)["deployment"]["db"]
    assert (db["provider"], db["plan"], db["provider_seen_at"]) == ("neon", "0.25cu", ".env.example:1")
    assert db["max_connections"]["label"] == "SUPUESTO" and db["max_connections"]["needs_review"]
    assert db["technology"]["name"] == "PostgreSQL"
    assert db["network_rtt_ms"]["value"] == 1


def test_real_env_file_is_never_read(tmp_path):
    write(tmp_path, {".env": "DATABASE_URL=postgres://u:secreta@ep-1.aws.neon.tech/app\n"})
    assert ingest(tmp_path)["deployment"]["db"]["provider"] == "local"


def test_render_plan_sets_the_machine_and_the_cost(tmp_path):
    write(
        tmp_path,
        {"render.yaml": "services:\n  - type: web\n    name: api\n    plan: pro plus\n    numInstances: 2\n"},
    )
    model = ingest(tmp_path)
    api = model["deployment"]["api"]
    assert (api["provider"], api["plan"], api["vcpu"]["value"], api["memory_gb"]["value"]) == (
        "render",
        "pro_plus",
        4,
        8,
    )
    line = next(line for line in estimate_cost(model).lines if line.id == "api")
    assert line.usd_month["value"] == 2 * 175
    assert "api" not in estimate_cost(model).missing


def test_vercel_json_adds_the_frontend_node_and_its_cost(tmp_path):
    write(tmp_path, {"vercel.json": "{}\n", "fly.toml": 'app = "api"\n'})
    model = ingest(tmp_path)
    front = model["deployment"]["frontend"]
    assert (front["provider"], front["plan"], front["usd_month"]["needs_review"]) == ("vercel", "hobby", True)
    assert model["deployment"]["api"]["provider"] == "fly"  # el frontend no le quita el destino a la API
    graph = build_graph(load_model(model), model)
    assert any(n.id == "frontend" and n.kind == "frontend" for n in graph.nodes)
    assert any(e.source == "frontend" and e.target == "api" for e in graph.edges)
    assert any(line.id == "frontend" for line in estimate_cost(model).lines)


def test_provider_without_profile_warns_and_stays_local(tmp_path):
    write(tmp_path, {".github/workflows/deploy.yml": "steps:\n  - run: heroku container:release web\n"})
    model = ingest(tmp_path)
    assert model["deployment"]["api"]["provider"] == "local"
    assert any("heroku" in w and "no está en el catálogo" in w for w in model["deployment"]["iac"]["warnings"])
    simulate(load_model(model), "pico_normal", seed=1, duration_s=5)


# --- tecnología (JAJ-87) ----------------------------------------------------------------------------


def test_technology_of_each_component_has_provenance(tmp_path):
    write(
        tmp_path,
        {
            "compose.yml": "services:\n  db:\n    image: postgres:16\n  redis:\n    image: redis:7.2\n",
            "package.json": '{\n  "dependencies": {\n    "express": "^4.19.2"\n  }\n}\n',
        },
    )
    model = ingest(tmp_path)
    dep = model["deployment"]
    assert dep["db"]["technology"].items() >= {"name": "PostgreSQL", "version": "16", "label": "OBSERVADO"}.items()
    assert dep["db"]["technology"]["at"].startswith("compose.yml")
    assert dep["api"]["technology"].items() >= {"name": "Express", "version": "4.19.2", "label": "OBSERVADO"}.items()
    assert dep["api"]["technology"]["at"] == "package.json:3"
    redis = next(s for s in dep["services"] if s["name"] == "redis")
    assert (redis["technology"]["name"], redis["technology"]["version"]) == ("Redis", "7.2")
    stripe = next(s for s in dep["services"] if s["name"] == "Stripe")
    assert stripe["technology"]["label"] == "ESTIMADO"  # lo propuso la IA
    nodes = {n.id: n for n in build_graph(load_model(model), model).nodes}
    assert nodes["db"].details["technology"] == "PostgreSQL 16"
    assert nodes["api"].details["technology"] == "Express 4.19.2"


def test_framework_without_manifest_is_estimated():
    tech = build_from_ai(ArchitectureSubmission.model_validate(EXPRESS))["deployment"]["api"]["technology"]
    assert (tech["name"], tech["version"], tech["label"]) == ("Express", None, "ESTIMADO")


# --- el plan cambia la simulación -------------------------------------------------------------------


@pytest.fixture
def model():
    return load_sample("full-stack-fastapi-template")


def test_bigger_neon_compute_lowers_p95_and_db_use(model):
    """Criterio de JAJ-143: cambiar el tamaño de Neon cambia la simulación. A 40 req/s la DB de 0,25 CU
    va a la mitad de su CPU y suma espera; con 4 CU casi no se usa."""
    runs = {}
    for plan in ("0.25cu", "4cu"):
        m = apply_ops(model, [{"op": "change_db_plan", "provider": "neon", "plan": plan}, {"op": "add_pooler"}]).model
        runs[plan] = simulate(load_model(m), "custom", rps=40, seed=1, duration_s=20)
    use = {plan: next(r for r in run.resources if r.name == "db_cpu").utilization for plan, run in runs.items()}
    assert use["4cu"] < use["0.25cu"] / 5
    assert runs["4cu"].latency.p95_ms < runs["0.25cu"].latency.p95_ms * 0.8


def test_network_round_trip_adds_latency_with_the_connection_taken(model):
    near = copy.deepcopy(model)
    far = copy.deepcopy(model)
    near["deployment"]["db"]["network_rtt_ms"] = {"value": 0, "unit": "ms", "label": "SUPUESTO", "source": "t"}
    far["deployment"]["db"]["network_rtt_ms"] = {"value": 20, "unit": "ms", "label": "SUPUESTO", "source": "t"}
    assert p95(far, 5) > p95(near, 5) + 20


# --- operaciones del agente -------------------------------------------------------------------------


def test_change_api_host_to_render_takes_the_plan_machine(model):
    r = apply_ops(model, [{"op": "change_api_host", "provider": "render", "plan": "pro"}])
    api = r.model["deployment"]["api"]
    assert (api["provider"], api["plan"], api["vcpu"]["value"]) == ("render", "pro", 2)
    with pytest.raises(OpError, match="los fija el plan"):
        apply_ops(r.model, [{"op": "scale_api", "replicas": 2, "vcpu": 4}])
    back = apply_ops(r.model, [{"op": "change_api_host", "provider": "fargate", "vcpu": 1}]).model["deployment"]["api"]
    assert "plan" not in back and back["provider"] == "fargate"


def test_change_api_host_sets_replicas_and_the_cost_follows(model):
    """JAJ-148: el inspector elige réplicas y vCPU; el costo es réplicas × (vCPU × US$/vCPU-h + GB × US$/GB-h)."""
    one = apply_ops(model, [{"op": "change_api_host", "provider": "fargate", "vcpu": 1, "replicas": 1}]).model
    three = apply_ops(model, [{"op": "change_api_host", "provider": "fargate", "vcpu": 1, "replicas": 3}]).model
    api = three["deployment"]["api"]
    assert api["replicas"]["value"] == 3
    assert api["usd_month"]["value"] == pytest.approx(3 * one["deployment"]["api"]["usd_month"]["value"], abs=0.02)
    cost = next(line for line in estimate_cost(three).lines if line.id == "api")
    assert cost.usd_month["value"] == pytest.approx(api["usd_month"]["value"], rel=0.05)
    render = apply_ops(model, [{"op": "change_api_host", "provider": "render", "plan": "pro", "replicas": 2}]).model
    assert render["deployment"]["api"]["usd_month"]["value"] == 170
    # más réplicas, más núcleos: el motor las simula
    assert load_model(three).api.cores == 3 * load_model(one).api.cores


def test_workers_set_the_cores_and_warn_when_vcpu_are_wasted(model):
    """JAJ-148: los workers no cambian el costo, pero el motor usa mín(workers, vCPU) × réplicas núcleos."""
    full = apply_ops(model, [{"op": "change_api_host", "provider": "fargate", "vcpu": 4, "workers": 4, "replicas": 2}])
    short = apply_ops(model, [{"op": "scale_api", "replicas": 2, "vcpu": 4, "workers": 1}])
    assert full.model["deployment"]["api"]["workers"]["value"] == 4 and not full.warnings
    assert load_model(full.model).api.cores == 8
    assert load_model(short.model).api.cores == 2
    assert any("Sobran vCPU" in w for w in short.warnings)
    same_cost = full.model["deployment"]["api"]["usd_month"]["value"]
    assert short.model["deployment"]["api"]["usd_month"]["value"] == same_cost


def test_neon_pooler_is_pgbouncer(model):
    r = apply_ops(model, [{"op": "change_db_plan", "provider": "neon", "plan": "1cu"}, {"op": "add_pooler"}])
    pooler = r.model["deployment"]["db"]["pooler"]
    assert (pooler["kind"], pooler["client_connections"]["value"]) == ("pgbouncer", 10000)


def test_change_frontend_host_only_changes_cost(model):
    r = apply_ops(model, [{"op": "change_frontend_host", "provider": "cloudfront", "plan": "pro"}])
    assert r.model["deployment"]["frontend"]["usd_month"]["value"] == 15
    assert any("no cambia la simulación" in w for w in r.warnings)
    json.dumps(r.model)  # serializable para guardarlo
