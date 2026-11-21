"""Los precios del backend son copias de los del spike de JAJ-11: este test avisa si se separan."""

from pathlib import Path

import pytest

from app.costs.prices import PRICES_DIR, aws_price, manual_block

SPIKE_PRICES = Path(__file__).parents[3] / "spikes" / "jaj-11-costos" / "prices"


@pytest.mark.skipif(not SPIKE_PRICES.exists(), reason="sin la carpeta spikes (ej. en un despliegue)")
@pytest.mark.parametrize("name", ["aws.json", "manual.json"])
def test_backend_prices_are_the_spike_prices(name):
    assert (PRICES_DIR / name).read_bytes() == (SPIKE_PRICES / name).read_bytes(), (
        f"Los precios cambiaron en spikes/jaj-11-costos/prices: copiar {name} a backend/app/costs/prices/"
    )


def test_aws_price_has_source_and_date():
    p = aws_price("us-east-1", "fargate_linux_arm", "vcpu_hour")
    assert p.usd == 0.03238
    assert "AWS Fargate - ARM - vCPU" in p.source and "pricing.us-east-1.amazonaws.com" in p.source
    assert p.date == "2026-11-11"


def test_unknown_region():
    with pytest.raises(ValueError, match="Región sin precios"):
        aws_price("eu-west-1", "alb", "hour")


def test_manual_block():
    sb = manual_block("supabase")
    assert sb["plans_month"]["pro"] == 25 and sb["read_on"] == "2026-11-21"
