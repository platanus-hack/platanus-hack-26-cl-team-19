"""Tests del costo mensual por componente (JAJ-72).

El criterio de la tarjeta es que el costo del template coincida con el del spike de JAJ-11: los tests
importan ``spikes/jaj-11-costos/costs.py`` y comparan componente por componente. La única diferencia
buscada es la transferencia: el spike no descuenta los 100 GB gratis de AWS.
"""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

from app.costs import cost_delta, estimate_cost
from app.costs.estimate import LABELS
from app.samples import load_sample

SPIKE_COSTS = Path(__file__).parents[3] / "spikes" / "jaj-11-costos" / "costs.py"
TEMPLATE = "full-stack-fastapi-template"
REALWORLD = "fastapi-realworld-example-app"


@pytest.fixture(scope="module")
def spike():
    if not SPIKE_COSTS.exists():
        pytest.skip("sin la carpeta spikes")
    spec = importlib.util.spec_from_file_location("jaj11_costs", SPIKE_COSTS)
    module = importlib.util.module_from_spec(spec)
    sys.modules["jaj11_costs"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def template():
    return load_sample(TEMPLATE)


def lines(est):
    return {line.id: line for line in est.lines}


# --- el template coincide con el spike de JAJ-11 ------------------------------------------------


def test_template_api_matches_spike(spike, template):
    """1 tarea de Fargate ARM con 1 vCPU y 2 GB, como en costo_stack_mes."""
    p = lambda *path: spike.precio("us-east-1", *path)  # noqa: E731
    expected = (p("fargate_linux_arm", "vcpu_hour") + 2 * p("fargate_linux_arm", "gb_hour")) * spike.HOURS_MONTH
    assert lines(estimate_cost(template))["api"].usd_month["value"] == pytest.approx(expected, abs=0.01)


def test_template_db_matches_spike_supabase(spike, template):
    """Supabase Pro con compute Micro, 100.000 MAU: supabase_mes del spike (disco y egreso incluidos)."""
    s = spike.supuestos(100_000, "ligero")
    assert spike.supabase_tamano(spike.carga(s).qps_db_pico, s) == "micro"
    assert lines(estimate_cost(template))["db"].usd_month["value"] == pytest.approx(spike.supabase_mes(s), abs=0.01)


def test_template_alb_matches_spike(spike, template):
    est = lines(estimate_cost(template))
    requests = est["alb"].inputs["requests_month"]
    gb = requests * 50 / 1024**2
    lcu = max(requests / spike.SECONDS_MONTH * 0.10 / 25, gb / spike.HOURS_MONTH)
    p = lambda *path: spike.precio("us-east-1", *path)  # noqa: E731
    expected = (p("alb", "hour") + lcu * p("alb", "lcu_hour")) * spike.HOURS_MONTH
    assert est["alb"].usd_month["value"] == pytest.approx(expected, abs=0.01)


def test_template_transfer_applies_the_free_tier(spike, template):
    """El spike cobra desde el primer GB; AWS regala 100 GB al mes: la diferencia es 100 × 0,09 = US$9."""
    est = lines(estimate_cost(template))["transfer"]
    gb = est.inputs["gb_month"]
    tiers = spike.AWS["regions"]["us-east-1"]["data_transfer_out_internet"]
    assert gb > 100
    assert spike.por_tramos(gb, tiers) - est.usd_month["value"] == pytest.approx(100 * 0.09, abs=0.05)


def test_template_total_and_requests(template):
    """100.000 MAU × 8 sesiones × 17 requests = 13,6 M de requests al mes (perfil medio de JAJ-11)."""
    est = estimate_cost(template)
    assert lines(est)["transfer"].inputs["requests_month"] == 13_600_000
    assert est.total["value"] == pytest.approx(sum(line.usd_month["value"] for line in est.lines), abs=0.01)
    assert [line.id for line in est.lines] == ["api", "db", "alb", "transfer"]
    assert est.unpriced == []


# --- procedencia --------------------------------------------------------------------------------


def test_every_cost_has_provenance(template):
    est = estimate_cost(template)
    for item in [est.total, *(line.usd_month for line in est.lines)]:
        assert item["label"] in LABELS and item["source"] and item["date"]
    assert lines(est)["api"].usd_month["date"] == "2026-11-11"  # fecha del archivo de AWS
    assert "pricing.us-east-1.amazonaws.com" in lines(est)["api"].usd_month["source"]


def test_label_is_the_weakest_input(template):
    """Las réplicas y los usuarios del template son SUPUESTO: el costo también."""
    est = estimate_cost(template)
    assert lines(est)["api"].usd_month["label"] == "SUPUESTO"
    assert est.total["label"] == "SUPUESTO"
    observed = copy.deepcopy(template)
    for k in ("replicas", "vcpu", "memory_gb"):
        observed["deployment"]["api"][k]["label"] = "OBSERVADO"
    assert lines(estimate_cost(observed))["api"].usd_month["label"] == "ESTIMADO"  # el precio de lista


# --- otros componentes y casos ------------------------------------------------------------------


def test_rds_and_missing_traffic():
    """realworld: db.t4g.medium (0,065 × 730 + 20 GB × 0,115) y tráfico en req/s, sin usuarios mensuales."""
    est = estimate_cost(load_sample(REALWORLD))
    db = lines(est)["db"]
    assert db.usd_month["value"] == pytest.approx(0.065 * 730 + 20 * 0.115, abs=0.01)
    assert "transfer" not in lines(est) and "alb" not in lines(est)
    assert any("usuarios mensuales" in u for u in est.unpriced)


def test_region_changes_aws_prices(template):
    us, sa = estimate_cost(template), estimate_cost(template, "sa-east-1")
    assert lines(sa)["api"].usd_month["value"] > lines(us)["api"].usd_month["value"]
    assert lines(sa)["db"].usd_month["value"] == lines(us)["db"].usd_month["value"]  # Supabase: precio plano
    with pytest.raises(ValueError):
        estimate_cost(template, "eu-west-1")


def test_cache_line_appears_with_a_cache_step(template):
    raw = copy.deepcopy(template)
    ep = next(e for e in raw["endpoints"] if e["id"] == "GET /items/")
    query = ep["steps"].pop(0)
    ep["steps"].insert(0, {"kind": "cache", "resource": "cache", "time": 0.03, "hit_ratio": 0.9, "on_miss": [query]})
    est = lines(estimate_cost(raw))
    cache = est["cache"]
    assert cache.node == "cache" and cache.usd_month["value"] > 0
    # 1 GB + 1 KB × 100.000 usuarios, a 0,084 US$/GB-h
    assert cache.inputs["gb"] == pytest.approx(1 + 100_000 / 1024**2, abs=0.001)


def test_queues_and_local_are_reported(template):
    raw = copy.deepcopy(template)
    raw["deployment"]["queues"] = {"emails": {"workers": 2, "job_steps": []}}
    est = estimate_cost(raw)
    assert any("cola 'emails'" in u for u in est.unpriced)
    local = copy.deepcopy(template)
    local["deployment"]["api"]["provider"] = "local"
    local["deployment"]["db"] = {**local["deployment"]["db"], "provider": "local", "plan": "docker"}
    assert lines(estimate_cost(local))["api"].usd_month["value"] == 0
    assert lines(estimate_cost(local))["db"].usd_month["value"] == 0


def test_unknown_plan_is_unpriced(template):
    raw = copy.deepcopy(template)
    raw["deployment"]["db"]["plan"] = "gigante"
    est = estimate_cost(raw)
    assert "db" not in lines(est) and any("gigante" in u for u in est.unpriced)


def test_cost_delta(template):
    bigger = copy.deepcopy(template)
    bigger["deployment"]["api"]["replicas"]["value"] = 3
    a, b = estimate_cost(template), estimate_cost(bigger)
    d = cost_delta(a, b)
    one_task = (0.03238 + 2 * 0.00356) * 730  # 28,836 US$/mes: cada línea se redondea a centavos
    assert d.by_line["api"] == pytest.approx(2 * one_task, abs=0.03)
    assert d.diff == pytest.approx(d.by_line["api"], abs=0.03)
    assert d.pct == pytest.approx(d.diff / a.total["value"], abs=1e-3)
