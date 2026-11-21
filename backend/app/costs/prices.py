"""Precios fechados para el costo de una arquitectura (JAJ-72), con su fuente.

``prices/aws.json`` y ``prices/manual.json`` son copias del snapshot del spike de JAJ-11
(``spikes/jaj-11-costos/prices``):

* ``aws.json``: archivo oficial de la AWS Price List API (us-east-1 y sa-east-1), con la URL del
  archivo, su fecha de publicación y la descripción literal del SKU de cada precio.
* ``manual.json``: precios sin archivo descargable (Supabase, Neon, Upstash, planes de CloudFront y
  tokens de LLM), cada bloque con su fuente y su fecha de lectura.

``tests/costs/test_prices.py`` falla si las copias dejan de ser iguales a las del spike. Para
actualizar precios: ``extract_aws_prices.py`` en el spike, y copiar los archivos aquí.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

PRICES_DIR = Path(__file__).parent / "prices"
REGIONS = ("us-east-1", "sa-east-1")


@cache
def _load(name: str) -> dict[str, Any]:
    return json.loads((PRICES_DIR / name).read_text(encoding="utf-8"))


def aws() -> dict[str, Any]:
    return _load("aws.json")


def manual() -> dict[str, Any]:
    return _load("manual.json")


@dataclass(frozen=True)
class Price:
    """Un precio con su procedencia: de dónde sale y de cuándo es."""

    usd: float
    unit: str
    source: str  # descripción del SKU o del bloque, más la URL
    date: str  # fecha de publicación del archivo (AWS) o de lectura (manual)


def aws_price(region: str, service: str, *path: str) -> Price:
    """Precio del archivo oficial de AWS. ``service`` es la clave de ``aws.json`` (ej. ``fargate_linux_arm``)."""
    if region not in REGIONS:
        raise ValueError(f"Región sin precios: '{region}'. Hay: {', '.join(REGIONS)}.")
    node = aws()["regions"][region][service]
    for p in path:
        node = node[p]
    origin = aws()["regions"][region]["sources"][_SOURCE_OF[service]]
    return Price(
        usd=node["usd"],
        unit=node["unit"],
        source=f"{node['sku_description']} ({origin['url']})",
        date=origin["publication_date"][:10],
    )


def aws_tiers(region: str, service: str) -> tuple[list[dict[str, Any]], str, str]:
    """Tramos por GB (ej. transferencia a internet), con la fuente y la fecha del archivo."""
    origin = aws()["regions"][region]["sources"][_SOURCE_OF[service]]
    return aws()["regions"][region][service], origin["url"], origin["publication_date"][:10]


def manual_block(name: str) -> dict[str, Any]:
    """Un bloque de ``manual.json`` (ej. ``supabase``), que trae ``source`` y ``read_on``."""
    return manual()[name]


# servicio de aws.json -> archivo de AWS del que sale (clave de "sources")
_SOURCE_OF = {
    "rds_postgres": "AmazonRDS",
    "s3_standard": "AmazonS3",
    "elasticache_valkey": "AmazonElastiCache",
    "alb": "AWSELB",
    "fargate_linux_arm": "AmazonECS",
    "data_transfer_out_internet": "AWSDataTransfer",
}
