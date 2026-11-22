"""Números con procedencia completa (JAJ-109): la fecha de los modelos ingeridos y el precio de la
escritura de caché del LLM."""

from __future__ import annotations

import datetime as dt

import pytest

from app.agent.loop import MODEL, cost_usd
from app.costs.prices import manual_block
from app.ingest import build_model as bm
from app.ingest.ai_graph import build_from_ai
from app.ingest.iac import scan_deployment
from tests.ingest.test_cache_queue_model import submission


def frozen(day: dt.date) -> type[dt.date]:
    class FrozenDate(dt.date):
        @classmethod
        def today(cls):
            return day

    return FrozenDate


def dates(node) -> set[str]:
    """Todas las fechas ``date`` de los números del modelo."""
    if isinstance(node, dict):
        own = {node["date"]} if isinstance(node.get("date"), str) else set()
        return own.union(*(dates(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(dates(v) for v in node))
    return set()


def test_ingested_models_are_dated_the_day_they_are_built(tmp_path, monkeypatch):
    """Antes, ``TODAY`` se calculaba al importar el módulo: un servidor con días arriba fechaba todo
    con el día en que arrancó. Dos ingestas en días distintos, sin reimportar, dan fechas distintas."""
    iac = scan_deployment(tmp_path).to_dict()
    built = {}
    # días lejanos, para no coincidir con hoy ni con las fechas del catálogo
    for day in (dt.date(2030, 1, 1), dt.date(2030, 1, 5)):
        monkeypatch.setattr(bm, "date", frozen(day))
        built[day] = build_from_ai(submission(), {}, iac=iac)
    first, second = built.values()
    assert first["repo"]["extracted_at"] == "2030-01-01"
    assert second["repo"]["extracted_at"] == "2030-01-05"
    # los números que arma la ingesta llevan el día en que se armaron; los del catálogo, su propia fecha
    assert "2030-01-01" in dates(first) and "2030-01-05" not in dates(first)
    assert "2030-01-05" in dates(second) and "2030-01-01" not in dates(second)


def test_num_keeps_an_explicit_date():
    assert bm.num(1, "x", "OBSERVADO", "s", date="2026-01-01")["date"] == "2026-01-01"


# --- precios del LLM -------------------------------------------------------------------------------

USAGE = {"input": 1_000_000, "output": 1_000_000, "cache_read": 1_000_000, "cache_write": 1_000_000}


@pytest.mark.parametrize("model", sorted(manual_block("llm_tokens")["usd_per_million"]))
def test_every_llm_in_the_price_table_has_the_four_prices(model):
    """``cost_usd`` lee los cuatro precios de la tabla. Si a un modelo le falta ``cache_write`` (o
    cualquier otro), este test falla: antes la escritura era un ×1,25 escrito en el código."""
    p = manual_block("llm_tokens")["usd_per_million"][model]
    assert {"input", "output", "cache_read", "cache_write"} <= set(p), f"{model}: faltan precios en manual.json"
    assert cost_usd(model, USAGE)["value"] == pytest.approx(
        p["input"] + p["output"] + p["cache_read"] + p["cache_write"]
    )


def test_cache_write_comes_from_the_table(monkeypatch):
    table = manual_block("llm_tokens")
    p = table["usd_per_million"]["claude-opus-5-5"]
    assert p["cache_write"] == 5.00  # 1,25 × US$4 de entrada, la escritura de 5 minutos
    cost = cost_usd("claude-opus-5-5", {"cache_write": 2_000_000})
    assert cost["value"] == 10.0 and cost["source"] == table["source"]


def test_a_model_without_cache_write_has_no_cost(monkeypatch):
    """Sin el precio en la tabla, no hay costo: mejor ``None`` que un número sin fuente."""
    import app.agent.loop as loop

    table = manual_block("llm_tokens")
    broken = {**table, "usd_per_million": {"m": {"input": 1, "output": 1, "cache_read": 0.1}}}
    monkeypatch.setattr(loop, "manual", lambda: {"llm_tokens": broken})
    assert cost_usd("m", USAGE) is None


def test_the_default_agent_model_is_priced():
    assert cost_usd(MODEL, USAGE) is not None
