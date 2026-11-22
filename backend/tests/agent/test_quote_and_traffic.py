"""Los números que el agente copia de la frase del usuario (JAJ-102) y el tráfico que deja set_traffic (JAJ-103).

JAJ-102: con «máximo 1 % de errores» pasaba ``slo_error_rate=1`` (100 %: toda versión cumple), con «p95 bajo
2 s» pasaba 2 ms, «0,5 vCPU» también se leía como 5 y 2,7 réplicas se truncaban a 2. En el chat, la frase la
escribe el LLM y nadie comprobaba que el usuario la hubiera dicho.

JAJ-103: ``set_traffic`` no cambiaba ``traffic.mau`` (el costo no seguía al tráfico) ni las req/s de los
escenarios del modelo, y cambiaba el escenario del proyecto antes de guardar la versión.
"""

from __future__ import annotations

import pytest

from app.agent.chat_tools import ChatAgentTools
from app.agent.tools import AgentTools, Limiter, ToolError, _parse_number, _readings_in
from app.api.store import InMemoryProjectStore
from app.costs import estimate_cost
from app.models import load_model
from app.samples import load_sample


@pytest.fixture
def store():
    return InMemoryProjectStore()


@pytest.fixture
def project(store):
    return store.create("tienda", load_sample("full-stack-fastapi-template"), "full-stack-fastapi-template")


@pytest.fixture
def tools(store):
    return AgentTools(store, None)


def chat_tools(store, project, *messages):
    return ChatAgentTools(
        store, None, Limiter(), None, project_id=project.id, base_version=1, user_messages=list(messages)
    )


# ---------- JAJ-102: cada número con su unidad ----------


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("0,5", 0.5),  # antes también 5
        ("2.5", 2.5),  # antes también 25
        ("1,25", 1.25),
        ("100.000", 100000),  # miles: tres dígitos después del separador
        ("1.500", 1500),
        ("100,000", 100000),
        ("1.234.567", 1234567),
        ("0.500", 0.5),  # empieza con 0: decimal
        ("1.234,5", 1234.5),
        ("1,234.5", 1234.5),
        ("1.2.3", None),
    ],
)
def test_one_reading_per_number(raw, value):
    assert _parse_number(raw) == value


def test_numbers_come_with_their_unit():
    assert _readings_in("máximo 1 % de errores y p95 bajo 2 s") == [(1.0, "%"), (2.0, "s")]
    assert _readings_in("p95 < 300 ms, 100k usuarios, 2 millones") == [(300.0, "ms"), (100000.0, None), (2e6, None)]
    assert _readings_in("1,5 segundos o 250 milisegundos") == [(1.5, "s"), (250.0, "ms")]


def goals(tools, project, **kw):
    return tools.call("set_goals", {"project_id": project.id, **kw})


@pytest.mark.parametrize(
    ("kw", "ok"),
    [
        ({"slo_error_rate": 1, "quote": "máximo 1 % de errores"}, False),  # sería 100 %
        ({"slo_error_rate": 0.01, "quote": "máximo 1 % de errores"}, True),
        ({"slo_error_rate": 0.01, "quote": "una tasa de error de 0,01"}, True),
        ({"slo_p95_ms": 2, "quote": "p95 bajo 2 s"}, False),  # serían 2 ms
        ({"slo_p95_ms": 2000, "quote": "p95 bajo 2 s"}, True),
        ({"slo_p95_ms": 300, "quote": "p95 < 300 ms"}, True),
        ({"slo_p95_ms": 300, "quote": "p95 bajo 0,3 segundos"}, True),
        ({"slo_p95_ms": 1, "quote": "p95 bajo 1 %"}, False),  # un porcentaje no es una latencia
        ({"slo_p95_ms": 95, "quote": "p95 bajo 2 s"}, False),  # el 95 de «p95» no es un dato
    ],
)
def test_goals_are_read_with_their_unit(tools, project, kw, ok):
    r = goals(tools, project, **kw)
    assert ("error" not in r) is ok, r
    if not ok:
        assert "con esa unidad" in r["error"]


def deployment(tools, project, field, value, quote):
    return tools.call("set_deployment", {"project_id": project.id, "field": field, "value": value, "quote": quote})


def test_vcpu_decimal_is_not_read_as_ten_times_more(tools, store, project):
    assert "no aparece en quote" in deployment(tools, project, "api.vcpu", "5", "usamos 0,5 vCPU")["error"]
    r = deployment(tools, project, "api.vcpu", "0.5", "usamos 0,5 vCPU")
    assert store.get_version(project.id, r["version"]).model["deployment"]["api"]["vcpu"]["value"] == 0.5


def test_replicas_must_be_whole(tools, store, project):
    r = deployment(tools, project, "api.replicas", "2.7", "tenemos 2.7 réplicas")
    assert "número entero" in r["error"] and len(store.get(project.id).versions) == 1  # no se trunca a 2
    assert "error" not in deployment(tools, project, "api.replicas", "3", "tenemos 3 réplicas")


def test_thousands_still_work(tools, project):
    r = tools.call(
        "set_traffic",
        {"project_id": project.id, "volume": 1500, "unit": "orders_per_day", "quote": "unos 1.500 pedidos al día"},
    )
    assert "error" not in r, r


# ---------- JAJ-102: en el chat, la quote tiene que estar en lo que escribió el usuario ----------


def test_chat_quote_must_be_something_the_user_said(store, project):
    tools = chat_tools(store, project, "Hola", "Queremos  un p95 bajo 300 ms, por favor")
    invented = goals(tools, project, slo_p95_ms=300, quote="el p95 tiene que ser menor a 300 ms")
    assert "no está en lo que escribió el usuario" in invented["error"]
    # la misma frase, con otras mayúsculas y espacios, sí
    assert "error" not in goals(tools, project, slo_p95_ms=300, quote="«p95 BAJO 300 ms»")
    assert store.get_goals(project.id).slo_p95_ms == 300


def test_chat_op_quotes_are_checked_too(store, project):
    tools = chat_tools(store, project, "la caché acierta el 90 % de las veces")
    op = {"op": "add_cache", "endpoint": "GET /items/", "hit_ratio": 0.9}
    invented = tools.call("propose_version", {"project_id": project.id, "ops": [{**op, "quote": "acierta 90 %"}]})
    assert "no está en lo que escribió el usuario" in invented["error"]
    said = tools.call("propose_version", {"project_id": project.id, "ops": [{**op, "quote": "acierta el 90 %"}]})
    assert "proposal" in said, said


def test_without_the_conversation_the_quote_is_not_checked(tools, project):
    """En MCP el backend no ve la conversación: solo se comprueba el número dentro de la frase."""
    assert tools.user_messages is None
    assert "error" not in goals(tools, project, slo_p95_ms=300, quote="nadie dijo esto: 300 ms")


# ---------- JAJ-103: set_traffic deja todo el bloque traffic coherente ----------


def set_traffic(tools, project, volume, unit, quote, **kw):
    r = tools.call("set_traffic", {"project_id": project.id, "volume": volume, "unit": unit, "quote": quote, **kw})
    assert "error" not in r, r
    return r


def transfer(model):
    return next(line.usd_month["value"] for line in estimate_cost(model).lines if line.id == "transfer")


def test_ten_times_the_users_raises_the_transfer_cost(tools, store, project):
    v1 = store.get_version(project.id, 1).model
    r = set_traffic(tools, project, 1_000_000, "users_per_month", "tenemos 1.000.000 de usuarios al mes")
    v2 = store.get_version(project.id, r["version"]).model
    assert v2["traffic"]["mau"]["value"] == 1_000_000 and v2["traffic"]["mau"]["unit"] == "usuarios/mes"
    assert transfer(v2) > transfer(v1)


def test_scenario_rates_follow_the_new_peak(tools, store, project):
    r = set_traffic(tools, project, 1_000_000, "users_per_month", "tenemos 1.000.000 de usuarios al mes")
    v2 = store.get_version(project.id, r["version"]).model
    peak = v2["traffic"]["peak_rps"]["value"]
    model = load_model(v2)
    assert model.scenarios["pico_normal"].rps == pytest.approx(peak)
    assert model.scenarios["cyberday"].rps == pytest.approx(peak * 20)  # todos, no solo el del evento


def test_other_units_derive_the_users_from_the_peak(tools, store, project):
    r = set_traffic(tools, project, 50, "requests_per_second_peak", "en el pico llegamos a 50 req/s")
    mau = store.get_version(project.id, r["version"]).model["traffic"]["mau"]
    assert mau["derived"] is True and mau["label"] == "SUPUESTO" and mau["value"] > 0
    assert any(c.startswith("Usuarios al mes derivados del pico") for c in r["changes"])
    # vuelta completa: con esos usuarios, la fórmula directa da el mismo pico
    again = set_traffic(tools, project, mau["value"], "users_per_month", f"son {mau['value']} usuarios al mes")
    assert again["peak_rps"]["value"] == pytest.approx(50, rel=0.01)


def test_if_saving_fails_the_project_scenario_is_untouched(tools, store, project, monkeypatch):
    before = {s.name: s for s in store.list_scenarios(project.id)}

    def broken(*args, **kwargs):
        raise ToolError("no se pudo guardar")

    monkeypatch.setattr(tools, "_save", broken)
    quote = "100.000 pedidos al día y en CyberDay 3×"
    r = tools.call(
        "set_traffic",
        {"project_id": project.id, "volume": 100000, "unit": "orders_per_day", "peak_factor": 3, "quote": quote},
    )
    assert r == {"error": "no se pudo guardar"}
    assert {s.name: s for s in store.list_scenarios(project.id)} == before
