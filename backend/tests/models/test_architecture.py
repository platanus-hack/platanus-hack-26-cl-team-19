"""``load_model``: cómo se lee un modelo ``branchpoint.model/v1`` (JAJ-110).

Hasta ahora ``load_model`` solo se probaba de forma indirecta, a través del motor y la API. Estos
tests fijan lo que hace hoy. Los rangos que todavía deja pasar (tiempos negativos, 0 réplicas…)
son JAJ-101.
"""

from __future__ import annotations

import copy
import json

import pytest

from app.models import load_model
from app.models.architecture import value
from app.samples import load_sample

SAMPLE = "full-stack-fastapi-template"


def tiny(**endpoint) -> dict:
    """Un modelo mínimo con un endpoint; ``endpoint`` reemplaza sus campos."""
    return {
        "schema": "branchpoint.model/v1",
        "repo": {"path": "tiny"},
        "deployment": {
            "api": {"replicas": 2, "vcpu": 2, "workers": 4, "threads_per_worker": 10, "latency_ms": 1},
            "db": {"vcpu": 2, "max_connections": 100, "pool_per_worker": {"pool_size": 5, "max_overflow": 5}},
        },
        "endpoints": [{"id": "GET /a", "weight": 1, "async": True, "api_cpu_ms": 10, "steps": [], **endpoint}],
        "traffic": {"scenarios": {"base": {"rps": {"value": 50, "label": "SUPUESTO"}}}},
    }


def test_value_reads_numbers_with_and_without_provenance():
    assert value({"value": 3, "label": "OBSERVADO"}) == 3
    assert value(3) == 3
    assert value(None, 7) == 7 and value({"label": "x"}, 7) == 7


def test_sample_loads():
    m = load_model(load_sample(SAMPLE))
    assert sum(e.weight for e in m.endpoints) == pytest.approx(1.0)
    assert {"pico_normal", "cyberday"} <= set(m.scenarios)
    assert m.scenario("cyberday").rps > m.scenario("pico_normal").rps


def test_loads_from_a_file(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps(tiny()), encoding="utf-8")
    assert load_model(path).name == "tiny"


def test_derived_capacities():
    """Cada worker usa como mucho 1 vCPU (GIL); hilos y conexiones se multiplican por workers y réplicas."""
    m = load_model(tiny())
    assert m.api.cores == min(4, 2) * 2
    assert m.api.threads == 10 * 4 * 2
    assert m.app_connections == (5 + 5) * 4 * 2


def test_weights_are_normalized():
    raw = tiny()
    raw["endpoints"].append({**raw["endpoints"][0], "id": "GET /b", "weight": 3})
    m = load_model(raw)
    assert [e.weight for e in m.endpoints] == pytest.approx([0.25, 0.75])


def test_base_cpu_is_api_cpu_minus_cpu_steps():
    hash_step = {"kind": "cpu", "resource": "api_cpu", "time": 4, "repeat": 2, "at": "h.py:1"}
    assert load_model(tiny(steps=[hash_step])).endpoints[0].base_cpu_ms == pytest.approx(10 - 8)
    assert load_model(tiny(api_cpu_ms=5, steps=[hash_step])).endpoints[0].base_cpu_ms == 0  # nunca negativa


def test_step_without_time_is_zero_with_a_warning():
    m = load_model(tiny(steps=[{"kind": "db", "resource": "db_connection", "at": "a.py:1"}]))
    assert m.endpoints[0].steps[0].time_ms == 0
    assert any("no tiene tiempo" in w for w in m.warnings)


def test_cache_without_hit_ratio_is_the_worst_case():
    cache = {"kind": "cache", "resource": "cache", "time": 1, "at": "c.py:1", "on_miss": []}
    m = load_model(tiny(steps=[cache]))
    assert m.endpoints[0].steps[0].hit_ratio == 0.0
    assert any("tasa de aciertos" in w for w in m.warnings)
    with pytest.raises(ValueError, match="hit_ratio"):
        load_model(tiny(steps=[{**cache, "hit_ratio": 1.5}]))


def test_background_step_uses_the_only_queue_or_warns():
    step = {"kind": "background", "resource": "background", "time": 1, "at": "b.py:1"}
    with_queue = tiny(steps=[step])
    with_queue["deployment"]["queues"] = {"emails": {"workers": 2, "job_steps": []}}
    assert load_model(with_queue).endpoints[0].steps[0].queue == "emails"
    without = load_model(tiny(steps=[step]))
    assert without.endpoints[0].steps[0].queue is None
    assert any("no tiene cola configurada" in w for w in without.warnings)


def test_unknown_scenario_names_the_ones_that_exist():
    with pytest.raises(KeyError, match="Hay: base"):
        load_model(tiny()).scenario("nope")


@pytest.mark.parametrize(
    "change, error, match",
    [
        (lambda r: r.update(schema="otra/v1"), ValueError, "Esquema no soportado"),
        (lambda r: r.pop("deployment"), KeyError, "deployment"),
        (lambda r: r["endpoints"][0].update(weight=0), ValueError, "suman 0"),
        (lambda r: r["deployment"]["api"].update(cpu_core_factor=0), ValueError, "cpu_core_factor"),
        (lambda r: r["deployment"]["db"].update(cpu_credits={"sustained_vcpu": 5}), ValueError, "sustained_vcpu"),
        (lambda r: r["deployment"].update(queues={"q": {"workers": 0}}), ValueError, "workers"),
    ],
)
def test_invalid_models(change, error, match):
    raw = copy.deepcopy(tiny())
    change(raw)
    with pytest.raises(error, match=match):
        load_model(raw)
