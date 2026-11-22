"""La API o la DB sin precio: el costo lo avisa y la comparación no dice "= Igual" como resultado (JAJ-88)."""

import copy

import pytest

from app.api.routes.projects import _usd, compare_summary
from app.costs import cost_delta, estimate_cost
from app.models.architecture import value
from app.samples import load_sample


@pytest.fixture
def template():
    return copy.deepcopy(load_sample("full-stack-fastapi-template"))  # API en fargate, DB en supabase


PLAN_OF = {"fly": "performance-1x", "render": "starter"}  # en Fly y Render el plan fija la máquina (JAJ-143)


def with_api(raw, provider=None, replicas=None, plan=None):
    out = copy.deepcopy(raw)
    if provider is not None:
        out["deployment"]["api"]["provider"] = provider
        if plan or provider in PLAN_OF:
            out["deployment"]["api"]["plan"] = plan or PLAN_OF[provider]
    if replicas is not None:
        out["deployment"]["api"]["replicas"]["value"] = replicas
    return out


def test_priced_model_has_nothing_missing(template):
    est = estimate_cost(template)
    assert est.missing == []
    assert not any(w.startswith("Sin precio") for w in est.warnings)


def test_local_api_and_db_are_flagged_first(template):
    raw = with_api(template, "local")
    raw["deployment"]["db"]["provider"] = "local"
    est = estimate_cost(raw)
    assert est.missing == ["api", "db"]
    w = est.warnings[0]
    assert w.startswith("Sin precio para la API (Local) ni la DB (Local): el total no las incluye")
    assert "la API en AWS Fargate, Fly.io o Render y la DB en Amazon RDS (PostgreSQL), Neon o Supabase" in w


def test_provider_without_prices_is_flagged(template):
    est = estimate_cost(with_api(template, "heroku"))
    assert est.missing == ["api"]
    w = est.warnings[0]
    assert "la API (heroku): el total no la incluye" in w  # singular
    assert w.endswith("indica dónde se desplegaría: la API en AWS Fargate, Fly.io o Render.")


def test_local_replicas_do_not_change_cost_and_summary_says_why(template):
    """Criterio 1: el caso de branchpoint-shop-demo (API en local, 1 contra 5 réplicas)."""
    a, b = with_api(template, "local", 1), with_api(template, "local", 5)
    delta = cost_delta(estimate_cost(a), estimate_cost(b))
    assert delta.diff == 0 and delta.missing == ["api"]
    text = compare_summary(1, 2, delta, None, None)
    assert text.startswith("v2 cuesta lo mismo que v1 sin contar la API, que no tiene precio")
    # con la DB también en local, el caso plural pasa de verdad por estimate_cost y cost_delta
    for raw in (a, b):
        raw["deployment"]["db"]["provider"] = "local"
    both = cost_delta(estimate_cost(a), estimate_cost(b))
    assert both.missing == ["api", "db"]
    assert "sin contar la API ni la DB, que no tienen precio" in compare_summary(1, 2, both, None, None)


def test_fargate_replicas_cost_more(template):
    """Criterio 2: con provider fargate, 5 réplicas cuestan más que 1."""
    one, five = estimate_cost(with_api(template, replicas=1)), estimate_cost(with_api(template, replicas=5))
    delta = cost_delta(one, five)
    assert delta.diff > 0 and delta.by_line["api"] > 0 and delta.missing == []
    assert "sin contar" not in compare_summary(1, 2, delta, None, None)
    # sin componentes que falten, a y b son los totales, como antes de JAJ-88 (sin diferencias de centavos)
    assert delta.a == one.total["value"] and delta.b == five.total["value"]


def test_agent_budget_is_not_judged_without_prices(template):
    """La revisión de #55: con la API en local, el agente no puede decir que "cumple el presupuesto"."""
    from app.agent.tools import _goal_check
    from app.api.store import ProjectGoals
    from app.engine import simulate
    from app.models import load_model

    raw = with_api(template, "local")
    est = estimate_cost(raw)
    run = simulate(load_model(raw), "pico_normal", seed=1, duration_s=5)
    goals = ProjectGoals(budget_usd_month=1_000_000, slo_error_rate=0.5)
    check = _goal_check(goals, run, est.total["value"], est.missing)
    assert check["budget"]["ok"] is None and "no evaluable" in check["budget"]["basis"]
    assert "la API, que no tiene precio" in check["budget"]["basis"]
    assert check["meets_all"] is None  # nada falla, pero el presupuesto no se pudo evaluar
    priced = estimate_cost(template)
    assert _goal_check(goals, run, priced.total["value"], priced.missing)["budget"]["ok"] is True
    # si el parcial ya se pasa del presupuesto, no cumple: lo que falta solo puede sumar
    over = _goal_check(ProjectGoals(budget_usd_month=1.0), run, est.total["value"], est.missing)
    assert est.total["value"] > 1.0 and over["budget"]["ok"] is False and over["meets_all"] is False
    assert over["budget"]["basis"].startswith("no cumple")
    # si otra meta falla, meets_all es False aunque el presupuesto no se pueda evaluar
    strict = ProjectGoals(budget_usd_month=1_000_000, slo_p95_ms=0.001)
    assert _goal_check(strict, run, est.total["value"], est.missing)["meets_all"] is False


def test_only_one_version_priced_is_not_counted_as_difference(template):
    """La revisión de #55: v1 en local y v2 en Fargate. El +US$X no puede ser la API de v2."""
    a, b = estimate_cost(with_api(template, "local")), estimate_cost(template)
    delta = cost_delta(a, b)
    assert delta.missing == ["api"] and delta.missing_a == ["api"] and delta.missing_b == []
    assert "api" not in delta.by_line and "alb" not in delta.by_line  # ni la API ni su balanceador
    assert delta.diff == pytest.approx(0, abs=0.01)  # el resto (DB, transferencia) es igual
    assert delta.b - delta.a == pytest.approx(delta.diff, abs=0.01)
    assert value_of(b) > value_of(a)  # los totales completos siguen en cada CostEstimate
    # JAJ-156: la API se dice aparte con su monto, y la diferencia comparable no se presenta como "+US$0"
    api = sum(value(line.usd_month) for line in b.lines if line.id in ("api", "alb"))
    assert delta.priced_in_one == {"api": pytest.approx(api, abs=0.01)} and delta.comparable is False
    text = compare_summary(1, 2, delta, None, None)
    assert text == f"v2 suma {_usd(api)}/mes en la API (v1 no tiene precio); el resto cuesta lo mismo."
    reverse = compare_summary(1, 2, cost_delta(b, a), None, None)
    assert reverse.startswith(f"v1 suma {_usd(api)}/mes en la API (v2 no tiene precio)")


def test_mixed_missing_reads_well(template):
    """La DB sin precio en las dos y la API con precio solo en v2: una frase que se entiende."""
    v1, v2 = with_api(template, "local"), copy.deepcopy(template)
    for raw in (v1, v2):
        raw["deployment"]["db"]["provider"] = "local"
    text = compare_summary(1, 2, cost_delta(estimate_cost(v1), estimate_cost(v2)), None, None)
    assert text.startswith("v2 suma US$")
    assert "/mes en la API (v1 no tiene precio)" in text
    assert text.endswith("sin contar la DB, que no tiene precio (despliegue local o proveedor sin precios).")
    # cada componente con precio en una sola versión distinta
    db_only_v1 = copy.deepcopy(v2)
    db_only_v1["deployment"]["db"]["provider"] = "supabase"
    cross = compare_summary(1, 2, cost_delta(estimate_cost(db_only_v1), estimate_cost(v1)), None, None)
    assert "en la API (v2 no tiene precio); v1 suma US$" in cross and "en la DB (v2 no tiene precio)" in cross


def value_of(est):
    return est.total["value"]


def test_priced_provider_sets_match_the_price_functions(template):
    """PRICED_API y PRICED_DB (para el aviso) coinciden con lo que de verdad tiene precio."""
    from app.costs.estimate import PRICED_API, PRICED_DB, _api_line, _db_line

    for provider in PRICED_API:
        assert estimate_cost(with_api(template, provider)).missing == []
        assert not isinstance(_api_line(with_api(template, provider), "us-east-1"), str)
    assert isinstance(_api_line(with_api(template, "heroku"), "us-east-1"), str)
    rds = copy.deepcopy(template)
    rds["deployment"]["db"].update(provider="rds_postgres", plan="db.t4g.micro")
    neon = copy.deepcopy(template)
    neon["deployment"]["db"].update(provider="neon", plan="1cu")
    for provider, raw in (("supabase", template), ("rds_postgres", rds), ("neon", neon)):
        assert provider in PRICED_DB
        assert not isinstance(_db_line(raw, "us-east-1", 1000, None), str), provider
        assert "db" not in estimate_cost(raw).missing
