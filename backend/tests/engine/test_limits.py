"""Ninguna simulación puede ocupar la CPU sin límite (JAJ-99).

``POST /runs`` no pide login, y la simulación retiene el GIL: una corrida que no termina deja la API
sin responder. Tres frenos: un tope de pasos por request (contando ``repeat``), el rechazo de colas
que se encolan en ciclo y un presupuesto de eventos por corrida.
"""

from __future__ import annotations

import copy
import importlib
import time

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.engine import simulate
from app.engine.kernel import Sim, SimulationTooLarge
from app.models import load_model
from app.models.architecture import MAX_STEPS_PER_REQUEST

simulate_mod = importlib.import_module("app.engine.simulate")  # el módulo: app.engine.simulate es la función


def tiny() -> dict:
    """Modelo mínimo: un endpoint async con una consulta de 10 ms."""
    return copy.deepcopy(
        {
            "schema": "branchpoint.model/v1",
            "repo": {"path": "tiny"},
            "deployment": {
                "api": {"provider": "local", "replicas": {"value": 1}, "vcpu": {"value": 1}, "workers": {"value": 1}},
                "db": {
                    "provider": "local",
                    "plan": "docker",
                    "vcpu": {"value": 1},
                    "max_connections": {"value": 100},
                    "pool_per_worker": {
                        "pool_size": {"value": 5},
                        "max_overflow": {"value": 10},
                        "pool_timeout_s": {"value": 30},
                    },
                },
            },
            "traffic": {"peak_rps": {"value": 10}, "scenarios": {"s": {"rps": {"value": 10}}}},
            "endpoints": [
                {
                    "id": "GET /a",
                    "method": "GET",
                    "async": True,
                    "weight": {"value": 1},
                    "api_cpu_ms": {"value": 1},
                    "steps": [{"kind": "db", "resource": "db_connection", "at": "a.py:1", "time": {"value": 10}}],
                }
            ],
        }
    )


def background(queue: str | None, ms: float = 0) -> dict:
    step = {"kind": "background", "resource": "background", "at": "jobs.py:1", "time": {"value": ms}}
    return {**step, "queue": queue} if queue else step


def with_queues(queues: dict[str, list[dict]]) -> dict:
    """``tiny`` con colas cuyos trabajos hacen esos pasos, y el endpoint encolando en la primera."""
    m = tiny()
    m["deployment"]["queues"] = {name: {"workers": {"value": 1}, "job_steps": steps} for name, steps in queues.items()}
    m["endpoints"][0]["steps"] = [background(next(iter(queues)))]
    return m


@pytest.fixture
def client():
    return TestClient(create_app(auth=None))


def post_run(client, model, **params):
    t = time.perf_counter()
    r = client.post("/runs", json={"model": model, "scenario": "s", "duration_s": 2, **params})
    return r, time.perf_counter() - t


# --- pasos por request -----------------------------------------------------------------------------


def test_huge_repeat_is_rejected_before_simulating(client):
    """BE-03: con repeat 10⁹ una sola request ocupaba la CPU ~17 minutos."""
    m = tiny()
    m["endpoints"][0]["steps"][0]["repeat"] = {"value": 10**9}
    r, seconds = post_run(client, m)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_model"
    assert "GET /a" in r.json()["error"]["message"] and "repeat" in r.json()["error"]["message"]
    assert seconds < 5  # se rechaza antes de simular (milisegundos); margen amplio para un CI lento (JAJ-110)


def test_nested_cache_misses_count_towards_the_limit():
    """Una caché con on_miss dentro de otra multiplica los pasos: el tope cuenta el peor caso."""
    m = tiny()
    inner = {"kind": "db", "resource": "db_connection", "at": "a.py:2", "time": {"value": 1}, "repeat": {"value": 200}}
    cache = {"kind": "cache", "resource": "cache", "at": "a.py:3", "time": {"value": 1}, "hit_ratio": {"value": 0.9}}
    m["endpoints"][0]["steps"] = [{**cache, "repeat": {"value": 100}, "on_miss": [inner]}]  # 100 × (1 + 200)
    with pytest.raises(ValueError, match="20.100 pasos"):
        load_model(m)


def test_the_limit_itself_is_allowed():
    m = tiny()
    m["endpoints"][0]["steps"][0]["repeat"] = {"value": MAX_STEPS_PER_REQUEST}
    load_model(m)  # justo en el tope: se acepta


def test_queue_jobs_have_the_same_limit():
    m = with_queues({"q": [{"kind": "cpu", "resource": None, "time": {"value": 0}, "repeat": {"value": 10**6}}]})
    with pytest.raises(ValueError, match="cola q: recorre"):
        load_model(m)


# --- colas en ciclo --------------------------------------------------------------------------------


def test_job_that_enqueues_itself_is_rejected(client):
    """BE-03: el trabajo se re-encolaba en el mismo instante y simulate no volvía nunca."""
    r, seconds = post_run(client, with_queues({"q": [background("q")]}))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_model"
    assert "ciclo (q → q)" in r.json()["error"]["message"]
    assert seconds < 5  # se rechaza antes de simular (milisegundos); margen amplio para un CI lento (JAJ-110)


def test_indirect_cycle_is_rejected():
    with pytest.raises(ValueError, match=r"ciclo \(a → b → c → a\)"):
        load_model(with_queues({"a": [background("b")], "b": [background("c")], "c": [background("a")]}))


def test_chain_without_cycle_still_simulates():
    """Encolar en otra cola sigue permitido mientras no vuelva atrás."""
    m = with_queues({"a": [background("b", 1)], "b": [{"kind": "cpu", "resource": None, "time": {"value": 1}}]})
    run = simulate(load_model(m), "s", seed=1, duration_s=5)
    assert {q.name: q.processed for q in run.queues}["b"] > 0


def test_job_step_without_queue_does_not_infer_its_own_queue():
    """Con una sola cola, un endpoint sin cola nombrada usa esa; un trabajo no, porque se encolaría a sí
    mismo. Solo se simula la espera de encolar."""
    model = load_model(with_queues({"q": [background(None, 1)]}))
    assert model.queues["q"].job_steps[0].queue is None
    simulate(model, "s", seed=1, duration_s=3)


def test_job_step_to_a_queue_that_does_not_exist_is_a_warning_not_a_crash():
    """Antes, simular daba KeyError (500 en la API)."""
    model = load_model(with_queues({"q": [background("no_existe", 1)]}))
    assert any("cola q" in w and "no tiene cola configurada" in w for w in model.warnings)
    simulate(model, "s", seed=1, duration_s=3)


# --- presupuesto de eventos ------------------------------------------------------------------------


def test_kernel_stops_at_the_event_budget():
    """Un proceso que se reprograma en el mismo instante: sin presupuesto, el reloj no avanza nunca."""
    sim = Sim()

    def forever():
        while True:
            yield 0

    sim.start(forever())
    with pytest.raises(SimulationTooLarge, match="1.000 eventos") as e:
        sim.run(until=1, max_events=1000)
    assert e.value.max_events == 1000 and sim.now == 0


def test_api_answers_run_too_large_when_the_budget_runs_out(client, monkeypatch):
    monkeypatch.setattr(simulate_mod, "MAX_EVENTS", 10)
    r, _ = post_run(client, tiny())
    body = r.json()["error"]
    assert r.status_code == 422 and body["code"] == "run_too_large" and body["max_events"] == 10


def test_real_models_fit_in_the_budget():
    """El presupuesto no corta las simulaciones legítimas: la más pesada que permite la API usa ~14,4
    millones de eventos (fastapi-realworld-example-app en pico_normal al tope de requests)."""
    assert simulate_mod.MAX_EVENTS >= 14_400_000 * 1.25
