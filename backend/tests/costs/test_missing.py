"""La API o la DB sin precio: el costo lo avisa y la comparación no dice "= Igual" como resultado (JAJ-88)."""

import copy

import pytest

from app.api.routes.projects import compare_summary
from app.costs import cost_delta, estimate_cost
from app.samples import load_sample


@pytest.fixture
def template():
    return copy.deepcopy(load_sample("full-stack-fastapi-template"))  # API en fargate, DB en supabase


def with_api(raw, provider=None, replicas=None):
    out = copy.deepcopy(raw)
    if provider is not None:
        out["deployment"]["api"]["provider"] = provider
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
    assert w.startswith("Sin precio para la API (local) ni la DB (local): el total no las incluye")
    assert "la API en fargate y la DB en rds_postgres o supabase" in w


def test_provider_without_prices_is_flagged(template):
    est = estimate_cost(with_api(template, "render"))
    assert est.missing == ["api"]
    w = est.warnings[0]
    assert "la API (render): el total no la incluye" in w  # singular
    assert w.endswith("indica dónde se desplegaría: la API en fargate.")


def test_local_replicas_do_not_change_cost_and_summary_says_why(template):
    """Criterio 1: el caso de branchpoint-shop-demo (API en local, 1 contra 5 réplicas)."""
    a, b = with_api(template, "local", 1), with_api(template, "local", 5)
    delta = cost_delta(estimate_cost(a), estimate_cost(b))
    assert delta.diff == 0 and delta.missing == ["api"]
    text = compare_summary(1, 2, delta, None, None)
    assert text.startswith("v2 cuesta +US$0.00/mes respecto de v1 sin contar la API, que no tiene precio")
    # con la DB también en local, el caso plural pasa de verdad por estimate_cost y cost_delta
    for raw in (a, b):
        raw["deployment"]["db"]["provider"] = "local"
    both = cost_delta(estimate_cost(a), estimate_cost(b))
    assert both.missing == ["api", "db"]
    assert "sin contar la API ni la DB, que no tienen precio" in compare_summary(1, 2, both, None, None)


def test_fargate_replicas_cost_more(template):
    """Criterio 2: con provider fargate, 5 réplicas cuestan más que 1."""
    delta = cost_delta(estimate_cost(with_api(template, replicas=1)), estimate_cost(with_api(template, replicas=5)))
    assert delta.diff > 0 and delta.by_line["api"] > 0 and delta.missing == []
    assert "sin contar" not in compare_summary(1, 2, delta, None, None)


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


def test_missing_in_either_version_counts(template):
    delta = cost_delta(estimate_cost(template), estimate_cost(with_api(template, "local")))
    assert delta.missing == ["api"]
