"""Tests del motor con el modelo del full-stack-fastapi-template (generado por build_model.py, JAJ-45).

Cubren los criterios de aceptación de JAJ-14: misma semilla = mismo resultado, 60 s simulados en
menos de 1 s, tráfico bajo casi sin espera, y sobre la capacidad la cola crece y hay timeouts.
"""

import copy
import json
from pathlib import Path

import pytest

from app.engine import simulate
from app.models import load_model

FIXTURE = Path(__file__).parents[1] / "fixtures" / "full-stack-fastapi-template.model.json"


@pytest.fixture(scope="module")
def raw():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def model(raw):
    return load_model(raw)


def without_timing(run):
    d = run.to_dict()
    d.pop("elapsed_ms")
    return d


def test_load_model(model):
    assert model.api.workers == 4
    assert model.api.cores == 1  # 4 workers en 1 vCPU
    assert model.app_connections == 60  # 4 workers × (5 + 10)
    assert model.db.vcpu == 0.5
    assert model.scenario("cyberday").rps == pytest.approx(262.4)
    assert sum(e.weight for e in model.endpoints) == pytest.approx(1.0)
    login = next(e for e in model.endpoints if e.id == "POST /login/access-token")
    assert login.base_cpu_ms == pytest.approx(0.68)  # api_cpu_ms 50,68 menos el hash de 50 ms
    assert any(s.shape == "password_hash" for s in login.steps)


def test_same_seed_same_result(model):
    a = simulate(model, "cyberday", seed=7, duration_s=20)
    b = simulate(model, "cyberday", seed=7, duration_s=20)
    assert without_timing(a) == without_timing(b)


def test_different_seed_different_result(model):
    a = simulate(model, "cyberday", seed=1, duration_s=20)
    b = simulate(model, "cyberday", seed=2, duration_s=20)
    assert without_timing(a) != without_timing(b)


def test_low_traffic_almost_no_wait(model):
    run = simulate(model, rps=5, duration_s=60)
    assert sum(run.errors.values()) == 0
    for r in run.resources:
        assert r.mean_wait_ms < 1.0, f"{r.label} espera {r.mean_wait_ms} ms con tráfico bajo"
        assert r.utilization < 0.2
    assert run.bottleneck.resource is None


def test_over_capacity_queue_grows_and_times_out(model):
    run = simulate(model, rps=2000, duration_s=30, client_timeout_s=5)
    api_cpu = next(r for r in run.resources if r.name == "api_cpu")
    assert run.bottleneck.resource == "api_cpu"
    assert api_cpu.final_queue > 0
    assert run.errors["client_timeout"] > 0
    first, last = run.series[0], run.series[-1]
    assert last.queue["api_cpu"] > first.queue["api_cpu"]
    assert any("optimista" in w for w in run.warnings)


def test_pool_timeout(raw):
    """Con un pool de 1 conexión y timeout corto, las requests que no alcanzan conexión fallan."""
    small = copy.deepcopy(raw)
    small["deployment"]["api"]["workers"]["value"] = 1
    pool = small["deployment"]["db"]["pool_per_worker"]
    pool["pool_size"]["value"], pool["max_overflow"]["value"], pool["pool_timeout_s"]["value"] = 1, 0, 0.05
    run = simulate(load_model(small), rps=300, duration_s=10)
    assert run.errors["pool_timeout"] > 0
    db_pool = next(r for r in run.resources if r.name == "db_pool")
    assert db_pool.timeouts == run.errors["pool_timeout"]
    # JAJ-135: la espera media cuenta a quienes vencieron, que esperaron los 50 ms del pool_timeout. Aquí
    # vence más de la mitad (1.312 de 2.497), así que no puede bajar de ~26 ms. Contando solo a quienes
    # obtuvieron conexión, como antes, salía 21,2 ms; ahora sale 36,3 ms.
    assert db_pool.mean_wait_ms > 30


def test_cyberday_60s_matches_checks(model, raw):
    """60 s de CyberDay: el cuello de botella coincide con los checks de JAJ-45.

    No se mide el tiempo real (JAJ-110): en un CI lento o cargado fallaba sin que nada cambiara. El
    trabajo de una corrida lo acota el presupuesto de eventos (JAJ-99, ``tests/engine/test_limits.py``).
    """
    run = simulate(model, "cyberday", duration_s=60)
    assert run.elapsed_ms > 0
    assert run.bottleneck.resource == raw["checks"]["scenarios"]["cyberday"]["bottleneck"]  # api_cpu
    assert len(run.series) == 60
