"""Tests del costo de fallar (JAJ-74): ventas en juego por hora según la tasa de error del Run."""

import copy

import pytest

from app.agent import apply_ops
from app.costs import failure_cost
from app.engine import simulate
from app.models import load_model
from app.samples import load_sample


@pytest.fixture(scope="module")
def template():
    return load_sample("full-stack-fastapi-template")


def run(raw, scenario="cyberday", duration_s=120, **kw):
    return simulate(load_model(raw), scenario, seed=1, duration_s=duration_s, **kw)


def test_more_errors_more_sales_at_stake(template):
    """Criterio de la tarjeta: en CyberDay, la versión con más errores muestra más ventas en juego."""
    v2 = apply_ops(template, [{"op": "scale_api", "replicas": 3}, {"op": "add_pooler"}]).model
    r1, r2 = run(template), run(v2)
    f1, f2 = failure_cost(template, r1), failure_cost(v2, r2)
    assert r1.error_rate > r2.error_rate > 0
    assert f1.lost_sales_per_hour["low"]["value"] > f2.lost_sales_per_hour["low"]["value"]


def test_formula_from_the_run(template):
    """Piso = sesiones/h × e × conversión × ticket; techo con 1 − (1 − e)^k; k = 17 requests por sesión."""
    r = run(template)
    f = failure_cost(template, r)
    k, conv, ticket = 17, 0.02, 30
    sessions_h = r.requests / r.duration_s * 3600 / k
    e = r.error_rate
    assert f.sessions_per_hour["value"] == pytest.approx(sessions_h, abs=0.1)
    assert f.lost_sales_per_hour["low"]["value"] == pytest.approx(sessions_h * e * conv * ticket, abs=1)
    assert f.lost_sales_per_hour["high"]["value"] == pytest.approx(
        sessions_h * (1 - (1 - e) ** k) * conv * ticket, abs=1
    )
    assert f.session_failure == {"low": round(e, 4), "high": round(1 - (1 - e) ** k, 4)}
    assert (
        f.lost_sales_per_hour["low"]["value"] <= f.lost_sales_per_hour["high"]["value"] <= f.at_stake_per_hour["value"]
    )


def test_at_stake_matches_build_model_check(template):
    """Si fallara todo, es la cota de build_model.py (checks.sales_at_stake_per_hour), salvo el azar de Poisson."""
    f = failure_cost(template, run(template))
    expected = template["checks"]["scenarios"]["cyberday"]["sales_at_stake_per_hour"]["value"]
    assert f.at_stake_per_hour["value"] == pytest.approx(expected, rel=0.03)
    uniform = failure_cost(template, run(template, arrivals="uniform"))
    assert uniform.at_stake_per_hour["value"] == pytest.approx(expected, rel=0.002)


def test_labels_and_floor(template):
    f = failure_cost(template, run(template))
    assert f.lost_sales_per_hour["low"]["label"] == "SUPUESTO"  # conversión y ticket son SUPUESTO
    assert "conversión (0.02)" in f.lost_sales_per_hour["low"]["source"]
    assert f.is_floor and "al menos" in f.message


def test_too_short_to_see_timeouts(template):
    """En 30 s saturado, todavía no vence ningún timeout: no hay que decir que no hay ventas en juego."""
    f = failure_cost(template, run(template, duration_s=30))
    assert f.error_rate == 0 and f.too_short
    assert "muy corta" in f.message


def test_no_errors_no_loss(template):
    f = failure_cost(template, run(template, "pico_normal", duration_s=30))
    assert f.error_rate == 0 and not f.too_short and not f.is_floor
    assert f.lost_sales_per_hour["high"]["value"] == 0 and "no hay ventas en juego" in f.message


def test_missing_business_data(template):
    raw = copy.deepcopy(template)
    del raw["business"]["ticket_usd"]
    assert failure_cost(raw, run(template, duration_s=10)) is None
