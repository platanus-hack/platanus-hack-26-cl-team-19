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
    assert errors > 0 and run.in_flight > 0  # a los 60 s ya vencieron timeouts y sigue habiendo fila
    assert s.error_rate_if_unanswered_fail == pytest.approx((errors + run.in_flight) / run.requests, abs=1e-4)
    assert s.error_rate_if_unanswered_fail > errors / run.requests  # suma las sin respuesta a los errores
    assert s.error_rate_if_unanswered_fail >= run.error_rate  # nunca por debajo de lo que ya se veía


def with_slow_call(raw, ms):
    """El template con una llamada externa de ``ms`` en cada endpoint: lento pero sin recurso que saturar."""
    out = copy.deepcopy(raw)
    for e in out["endpoints"]:
        e["steps"] = [{"kind": "external", "resource": None, "at": "slow.py:1", "time": {"value": ms}}, *e["steps"]]
    return load_model(out)


@pytest.mark.parametrize(
    "ms, rps, duration_s, profile",
    [
        (3000, 2, 30, None),  # una llamada a un LLM de 3 s: ~10 % sigue en curso al terminar, y está sana
        (600, 20, 6, None),  # simulación corta: ~10 % en curso, lejos del umbral
        (3000, 2, 30, "subida"),  # tasa que sube: la fila crece, pero la espera no
    ],
)
def test_slow_but_healthy_is_not_saturated(raw, ms, rps, duration_s, profile):
    """Lo que señaló la revisión: quedar en curso no basta; tiene que crecer la espera (Ley de Little)."""
    from app.models.traffic import TrafficProfile, TrafficSegment

    tp = TrafficProfile((TrafficSegment(duration_s, 0.2, 1.0),)) if profile == "subida" else None
    run = simulate(with_slow_call(raw, ms), "x", seed=1, duration_s=duration_s, rps=rps, traffic_profile=tp)
    s = run.saturation
    assert s.unanswered_rate >= 0.05  # el umbral solo lo habría marcado como saturado
    assert not s.saturated and s.message is None
    assert s.wait_end_s < 1.5 * s.wait_mid_s + 0.25


def test_wait_grows_when_overloaded(model):
    s = simulate(model, "cyberday", seed=1, duration_s=20).saturation
    assert s.wait_end_s > 1.5 * s.wait_mid_s
    assert "La espera crece sin parar" in s.message and "%" in s.message and " %" in s.message


def test_very_short_simulation_is_not_judged(model):
    s = simulate(model, "cyberday", seed=1, duration_s=3).saturation
    assert not s.saturated and s.wait_mid_s == s.wait_end_s == 0.0


def test_saved_run_round_trips_saturation_as_dataclass(model):
    """Un Run guardado (JAJ-75) vuelve con saturation como Saturation, no como dict: así lo leen
    _goal_check y el resumen de compare."""
    from app.api.run_cache import run_from_json, run_to_json
    from app.models.run import Saturation

    run = simulate(model, "cyberday", seed=1, duration_s=20)
    back = run_from_json(run_to_json(run))
    assert isinstance(back.saturation, Saturation) and back.saturation == run.saturation
    assert back.saturation.saturated


def test_queue_left_when_traffic_drops_to_zero_is_not_hidden(model):
    """Si el perfil baja a 0 req/s y queda fila, la espera no puede salir 0 (sería esconder la fila)."""
    from app.models.traffic import TrafficProfile, TrafficSegment

    tp = TrafficProfile((TrafficSegment(14, 1.0, 1.0), TrafficSegment(6, 0.0, 0.0)))
    s = simulate(model, "cyberday", seed=1, traffic_profile=tp).saturation
    assert s.wait_end_s > 0 and s.saturated


def test_compare_route_says_it(raw):
    """Por HTTP: compare pasa los dos Run al resumen."""
    from fastapi.testclient import TestClient

    from app.api.main import create_app
    from app.api.store import InMemoryProjectStore

    client = TestClient(create_app(store=InMemoryProjectStore(), auth=None))
    pid = client.post("/projects", json={"sample": SAMPLE}).json()["id"]
    client.post(f"/projects/{pid}/versions/1/ops", json={"ops": [{"op": "scale_api", "replicas": 2}]})
    r = client.post(f"/projects/{pid}/compare", json={"a": 1, "b": 2, "scenario": "cyberday", "duration_s": 20})
    body = r.json()
    assert r.status_code == 200 and body["run_a"]["saturation"]["saturated"]
    assert "Ojo:" in body["summary"] and "alcanza a atender" in body["summary"]


def test_old_saved_run_without_saturation_still_loads(model):
    """Un Run guardado antes de JAJ-89 no trae saturation: se lee igual (queda en None)."""
    from app.api.run_cache import run_from_json, run_to_json

    data = run_to_json(simulate(model, "pico_normal", seed=1, duration_s=5))
    del data["saturation"]
    assert run_from_json(data).saturation is None


def test_agent_goals_fail_when_saturated(model):
    """El agente no puede decir que una versión colapsada "cumple las metas" por su 0 % de errores."""
    from app.agent.tools import _goal_check
    from app.api.store import ProjectGoals

    run = simulate(model, "cyberday", seed=1, duration_s=20)
    assert run.error_rate == 0 and run.saturation.saturated
    check = _goal_check(ProjectGoals(slo_p95_ms=1_000_000, slo_error_rate=0.01), run, None)
    assert check["errors"]["ok"] is False and check["p95"]["ok"] is False and check["meets_all"] is False
    # dice con qué tasa juzgó, para que el agente pueda explicar el "no cumple" con 0 % de errores
    assert check["errors"]["basis"].startswith("techo por saturación") and check["errors"]["error_rate"] == 0
    assert check["errors"]["value"] == run.saturation.error_rate_if_unanswered_fail
    assert "saturación" in check["p95"]["basis"]
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
    assert "Ninguna versión alcanza" in both and "sus tasas de error son un piso" in both
    assert "su tasa de error es un piso" in text
    assert "Ojo" not in compare_summary(1, 2, delta, None, None, run_b, run_b)
    assert "Ojo" not in compare_summary(1, 2, delta, None, None)  # sin runs, como antes
