"""El catálogo del backend es una copia del de spikes/jaj-45-numeros: este test avisa si se separan."""

from pathlib import Path

import pytest

from app.catalog import CATALOG_PATH, catalog, core_factor, cpu_credits, db_usd_month, num, weakest

SPIKE_CATALOG = Path(__file__).parents[3] / "spikes" / "jaj-45-numeros" / "catalog.json"


@pytest.mark.skipif(not SPIKE_CATALOG.exists(), reason="sin la carpeta spikes (ej. en un despliegue)")
def test_backend_catalog_is_the_spike_catalog():
    assert CATALOG_PATH.read_bytes() == SPIKE_CATALOG.read_bytes(), (
        "El catálogo cambió en spikes/jaj-45-numeros: copiarlo a backend/app/catalog/catalog.json"
    )


def test_catalog_is_a_fresh_copy():
    a = catalog()
    a["db_plans"]["supabase"]["micro"]["vcpu"] = 99
    assert catalog()["db_plans"]["supabase"]["micro"]["vcpu"] == 0.5


def test_db_usd_month_matches_build_model():
    """Supabase: 25 + max(0, compute − 10). RDS: US$/hora × 730 (JAJ-11)."""
    plans = catalog()["db_plans"]
    assert db_usd_month("supabase", plans["supabase"]["micro"]) == 25
    assert db_usd_month("supabase", plans["supabase"]["small"]) == 30
    assert db_usd_month("rds_postgres", plans["rds_postgres"]["db.t4g.medium"]) == round(0.065 * 730, 2)


def test_factor_and_credits():
    plans = catalog()["db_plans"]
    f = core_factor(plans["rds_postgres"]["db.m7g.large"], "Plan rds_postgres db.m7g.large")
    assert (f["value"], f["processor"]) == (1.55, "graviton3")
    vcpu = num(2, "vCPU", "ESTIMADO", "catálogo")
    assert cpu_credits("db.t4g.medium", vcpu)["sustained_vcpu"]["value"] == 0.4
    assert cpu_credits("db.m7g.large", vcpu) is None


def test_weakest_and_labels():
    assert weakest("CALIBRADO", "SUPUESTO", "ESTIMADO") == "SUPUESTO"
    with pytest.raises(ValueError):
        num(1, "x", "INVENTADO", "fuente")
