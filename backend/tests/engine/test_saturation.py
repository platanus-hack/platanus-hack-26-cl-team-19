"""Requests sin respuesta al terminar: "0 % de errores" no puede esconder un colapso (JAJ-89)."""

import copy

import pytest

from app.api.routes.projects import compare_summary
from app.costs import cost_delta, estimate_cost
from app.engine import simulate
from app.models import load_model
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"


@pytest.fixture(scope="module")
def raw():
    return load_sample(SAMPLE)


@pytest.fixture(scope="module")
def model(raw):
    return load_model(raw)


def test_traffic_it_can_handle_is_not_saturated(model):
    run = simulate(model, "pico_normal", seed=1, duration_s=30)
    s = run.saturation
    assert s is not None and not s.saturated and s.message is None
    assert s.unanswered == run.in_flight and s.unanswered_rate < 0.01
    assert not any("no alcanza a atender" in w for w in run.warnings)


def test_overload_with_zero_errors_is_flagged(model):
    """Criterio 1: el sistema está colapsado, pero dentro de 20 s todavía no vence ningún timeout de 30 s."""
    run = simulate(model, "cyberday", seed=1, duration_s=20)
    assert run.error_rate == 0  # lo que se veía antes: "0 % de errores"
    s = run.saturation
    assert s.saturated and s.unanswered == run.in_flight > 0
    assert s.unanswered_rate >= 0.05
    assert s.error_rate_if_unanswered_fail == pytest.approx(s.unanswered_rate, abs=1e-4)
    assert s.offered_rps == pytest.approx(run.requests / 20, rel=1e-3)
    assert run.warnings[0] == s.message  # primero, porque cambia cómo leer lo demás
    assert "no alcanza a atender" in s.message and "fila" in s.message


def test_ceiling_includes_real_errors(model):
    run = simulate(model, "cyberday", seed=1, duration_s=60)
    s = run.saturation
    errors = sum(run.errors.values())
    assert s.error_rate_if_unanswered_fail == pytest.approx((errors + run.in_flight) / run.requests, abs=1e-4)
    assert s.error_rate_if_unanswered_fail >= run.error_rate * (run.ok + errors) / run.requests


def test_agent_goals_fail_when_saturated(model):
    """El agente no puede decir que una versión colapsada "cumple las metas" por su 0 % de errores."""
    from app.agent.tools import _goal_check
    from app.api.store import ProjectGoals

    run = simulate(model, "cyberday", seed=1, duration_s=20)
    assert run.error_rate == 0 and run.saturation.saturated
    check = _goal_check(ProjectGoals(slo_p95_ms=1_000_000, slo_error_rate=0.01), run, None)
    assert check["errors"]["ok"] is False and check["p95"]["ok"] is False and check["meets_all"] is False
    fine = simulate(model, "pico_normal", seed=1, duration_s=20)
    assert _goal_check(ProjectGoals(slo_p95_ms=1_000_000, slo_error_rate=0.01), fine, None)["meets_all"]


def test_compare_summary_says_which_version_does_not_keep_up(raw, model):
    bigger = copy.deepcopy(raw)
    bigger["deployment"]["api"]["replicas"]["value"] = 8
    run_a = simulate(model, "cyberday", seed=1, duration_s=20)
    run_b = simulate(load_model(bigger), "pico_normal", seed=1, duration_s=20)
    delta = cost_delta(estimate_cost(raw, "us-east-1"), estimate_cost(bigger, "us-east-1"))
    text = compare_summary(1, 2, delta, None, None, run_a, run_b)
    assert "Ojo: v1 no alcanza a atender este tráfico" in text and "v2 deja" not in text
    both = compare_summary(1, 2, delta, None, None, run_a, run_a)
    assert "Ninguna versión alcanza" in both
    assert "Ojo" not in compare_summary(1, 2, delta, None, None, run_b, run_b)
    assert "Ojo" not in compare_summary(1, 2, delta, None, None)  # sin runs, como antes
