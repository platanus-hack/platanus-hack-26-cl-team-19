"""``load_model``: cómo se lee un modelo ``branchpoint.model/v1`` (JAJ-110).

Hasta ahora ``load_model`` solo se probaba de forma indirecta, a través del motor y la API. Estos
tests fijan lo que hace. Desde JAJ-101 también valida la forma y los rangos (tiempos negativos, 0
réplicas, un texto donde va un número…), con el campo en el mensaje.
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


# --- forma y rangos (JAJ-101) ----------------------------------------------------------------------

STEP = {"kind": "db", "resource": "db_connection", "time": 2, "at": "a.py:1"}


@pytest.mark.parametrize(
    "change, match",
    [
        (
            lambda r: r["deployment"]["api"].update(replicas=0),
            r"deployment\.api\.replicas debe ser al menos 1 \(es 0\)",
        ),
        (lambda r: r["deployment"]["api"].update(workers=0), r"deployment\.api\.workers debe ser al menos 1"),
        (lambda r: r["deployment"]["api"].update(threads_per_worker=0), r"threads_per_worker debe ser al menos 1"),
        (lambda r: r["deployment"]["api"].update(vcpu=0), r"deployment\.api\.vcpu debe ser mayor que 0"),
        (lambda r: r["deployment"]["api"].update(memory_gb=0), r"deployment\.api\.memory_gb debe ser mayor que 0"),
        (lambda r: r["deployment"]["api"].update(latency_ms=-1), r"latency_ms no puede ser negativo \(es -1\)"),
        (lambda r: r["deployment"]["db"].update(vcpu=-2), r"deployment\.db\.vcpu debe ser mayor que 0"),
        (lambda r: r["deployment"]["db"].update(max_connections=0), r"max_connections debe ser al menos 1"),
        (
            lambda r: r["deployment"]["db"].update(pool_per_worker={"pool_size": 0, "max_overflow": 0}),
            r"pool_size \+ max_overflow debe ser al menos 1",
        ),
        (
            lambda r: r["deployment"]["db"].update(pool_per_worker={"pool_size": -1}),
            r"pool_size no puede ser negativo",
        ),
        (lambda r: r["deployment"]["db"].update(pooler={"client_connections": 0}), r"client_connections debe ser al"),
        (
            lambda r: r["deployment"].update(queues={"q": {"workers": 1, "max_length": 0}}),
            r"deployment\.queues\.q\.max_length debe ser al menos 1",
        ),
        (
            lambda r: r["deployment"].update(queues={"q": {"job_steps": [{**STEP, "time": -1}]}}),
            r"deployment\.queues\.q\.job_steps\[0\]\.time no puede ser negativo",
        ),
        (lambda r: r["endpoints"][0].update(weight=-1), r"endpoints\[0\]\.weight no puede ser negativo"),
        (lambda r: r["endpoints"][0].update(api_cpu_ms=-1), r"endpoints\[0\]\.api_cpu_ms no puede ser negativo"),
        (lambda r: r["endpoints"][0].update(steps=[{**STEP, "time": -3}]), r"steps\[0\]\.time no puede ser negativo"),
        (lambda r: r["endpoints"][0].update(steps=[{**STEP, "repeat": -1}]), r"steps\[0\]\.repeat no puede ser neg"),
        (lambda r: r["endpoints"][0].update(steps=[{**STEP, "repeat": 2.5}]), r"steps\[0\]\.repeat debe ser un entero"),
        (
            lambda r: r["endpoints"][0].update(
                steps=[{"kind": "cache", "resource": "cache", "time": 1, "on_miss": [{**STEP, "time": -1}]}]
            ),
            r"steps\[0\]\.on_miss\[0\]\.time no puede ser negativo",
        ),
        (lambda r: r["traffic"]["scenarios"]["base"].update(rps=0), r"traffic\.scenarios\.base\.rps debe ser mayor"),
        (lambda r: r["traffic"].update(peak_rps=-5), r"traffic\.peak_rps debe ser mayor que 0"),
        (lambda r: r.update(business={"conversion": 1.5}), r"business\.conversion es una fracción"),
        (lambda r: r.update(business={"ticket_usd": -1}), r"business\.ticket_usd no puede ser negativo"),
        (lambda r: r.update(schema="branchpoint.model/v1.1"), "Esquema no soportado"),
    ],
)
def test_out_of_range_values_name_the_field(change, match):
    raw = tiny()
    change(raw)
    with pytest.raises(ValueError, match=match):
        load_model(raw)


@pytest.mark.parametrize(
    "change, match",
    [
        (lambda r: r["deployment"].update(db=[]), r"deployment\.db debe ser un objeto \(\{…\}\), no una lista"),
        (lambda r: r.update(endpoints={"GET /a": {}}), r"endpoints debe ser una lista"),
        (lambda r: r.update(endpoints=["x"]), r"endpoints\[0\] debe ser un objeto \(\{…\}\), no un texto \('x'\)"),
        (lambda r: r["endpoints"][0].update(steps=[1]), r"endpoints\[0\]\.steps\[0\] debe ser un objeto"),
        (lambda r: r["endpoints"][0].update(id=""), r"endpoints\[0\]\.id debe ser un texto"),
        (lambda r: r["deployment"]["api"].update(replicas="2"), r"replicas debe ser un número, no un texto \('2'\)"),
        (lambda r: r["deployment"]["api"].update(vcpu=True), r"vcpu debe ser un número, no true"),
        (lambda r: r["deployment"]["api"].update(vcpu=[2]), r"vcpu debe ser un número, no una lista"),
        (lambda r: r["traffic"]["scenarios"].update(base=50), r"traffic\.scenarios\.base debe ser un objeto"),
        (lambda r: r["traffic"].update(profile=[]), r"traffic\.profile debe ser un objeto"),
        (lambda r: r.update(repo="tiny"), r"repo debe ser un objeto"),
        (lambda r: r["deployment"].update(queues=[]), r"deployment\.queues debe ser un objeto"),
    ],
)
def test_wrong_shapes_name_the_field(change, match):
    """Antes eran ``AttributeError`` o ``TypeError`` sin el campo, y en la API un 500 (BE-08)."""
    raw = tiny()
    change(raw)
    with pytest.raises(ValueError, match=match):
        load_model(raw)


def test_a_missing_required_field_names_its_path():
    raw = tiny()
    del raw["deployment"]["api"]["workers"]
    with pytest.raises(KeyError, match=r"deployment\.api\.workers"):
        load_model(raw)


def test_numbers_with_and_without_provenance_load_the_same():
    """La decisión de JAJ-101: los escalares valen en todo el modelo, igual que ``{"value": …}``."""
    plain = tiny()

    def boxed(x):
        return {"value": x, "label": "SUPUESTO"}

    raw = tiny()
    api = raw["deployment"]["api"]
    for k in ("replicas", "vcpu", "workers", "threads_per_worker", "latency_ms"):
        api[k] = boxed(api[k])
    raw["traffic"]["scenarios"]["base"]["rps"] = 50
    assert load_model(raw) == load_model(plain)


def test_valid_edge_values_still_load():
    """Los bordes que sí son válidos: tiempo 0, un endpoint con peso 0 (si otro tiene tráfico), sin
    límite de conexiones ni de cola (``null``), repeat 0 (se lee como 1, como antes) y conversión 1."""
    raw = tiny(steps=[{**STEP, "time": 0, "repeat": 0}])
    raw["endpoints"].append({**raw["endpoints"][0], "id": "GET /b", "weight": 0})
    raw["deployment"]["db"]["max_connections"] = None
    raw["deployment"]["queues"] = {"q": {"workers": 1, "max_length": None}}
    raw["business"] = {"conversion": 1, "ticket_usd": 0}
    m = load_model(raw)
    assert m.db.max_connections is None and m.queues["q"].max_length is None
    assert m.endpoints[0].steps[0].repeat == 1 and m.endpoints[1].weight == 0


def test_every_sample_and_fixture_still_loads():
    """La validación no rechaza ningún modelo real del repo."""
    from pathlib import Path

    from app.samples import sample_ids

    for sample_id in sample_ids():
        load_model(load_sample(sample_id))
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    for path in fixtures.rglob("*.json"):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("schema") == "branchpoint.model/v1":
            load_model(raw)
