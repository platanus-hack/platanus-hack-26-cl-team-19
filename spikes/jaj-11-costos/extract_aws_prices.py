"""Arma el snapshot de precios de AWS desde los archivos públicos oficiales.

Descarga (o lee de una carpeta) los archivos de la Price List API de AWS y
guarda solo los precios que usa el modelo de costos, con la fecha de
publicación y la descripción literal de cada SKU para poder auditarlos.

Uso:
    python3 extract_aws_prices.py --cache /tmp/aws -o prices/aws.json

No necesita credenciales: los archivos tienen URL pública.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

BASE = "https://pricing.us-east-1.amazonaws.com"
REGIONS = ("us-east-1", "sa-east-1")
SERVICES = (
    "AmazonRDS",
    "AmazonS3",
    "AmazonElastiCache",
    "AWSELB",
    "AmazonECS",
    "AWSDataTransfer",
)

RDS_INSTANCES = (
    "db.t4g.micro",
    "db.t4g.medium",
    "db.m7g.large",
    "db.m7g.xlarge",
    "db.m7g.2xlarge",
    "db.m7g.4xlarge",
)


def fetch_json(url: str, cache: Path) -> dict:
    name = url.removeprefix(BASE).strip("/").replace("/", "_")
    path = cache / name
    if not path.exists():
        with urllib.request.urlopen(url, timeout=120) as resp:
            path.write_bytes(resp.read())
    return json.loads(path.read_text())


def region_file(service: str, region: str, cache: Path) -> tuple[str, dict]:
    idx = fetch_json(f"{BASE}/offers/v1.0/aws/{service}/current/region_index.json", cache)
    url = BASE + idx["regions"][region]["currentVersionUrl"]
    return url, fetch_json(url, cache)


def rows(offer: dict):
    """Precios on-demand: (atributos, unidad, USD, descripción, desde, hasta)."""
    terms = offer["terms"]["OnDemand"]
    for sku, product in offer["products"].items():
        attrs = product.get("attributes", {})
        for term in terms.get(sku, {}).values():
            for dim in term["priceDimensions"].values():
                yield (
                    attrs,
                    dim["unit"],
                    float(dim["pricePerUnit"].get("USD", 0)),
                    dim["description"].strip(),
                    dim.get("beginRange"),
                    dim.get("endRange"),
                )


def pick(offer: dict, match, label: str) -> dict:
    """Devuelve el único precio que cumple `match`; falla si hay 0 o varios distintos."""
    found = {(p, u, d) for a, u, p, d, *_ in rows(offer) if match(a, d)}
    prices = {p for p, _, _ in found}
    if len(prices) != 1:
        raise SystemExit(f"{label}: esperaba 1 precio, encontré {sorted(found)}")
    price, unit, desc = sorted(found)[0]
    return {"usd": price, "unit": unit, "sku_description": desc}


def tiers(offer: dict, match) -> list[dict]:
    out = {
        (float(b), None if e == "Inf" else float(e), p, d)
        for a, _, p, d, b, e in rows(offer)
        if match(a, d)
    }
    return [
        {"from_gb": b, "to_gb": e, "usd_per_gb": p, "sku_description": d}
        for b, e, p, d in sorted(out)
    ]


def extract_region(region: str, cache: Path) -> dict:
    out: dict = {"sources": {}}
    offers = {}
    for svc in SERVICES:
        url, offer = region_file(svc, region, cache)
        offers[svc] = offer
        out["sources"][svc] = {"url": url, "publication_date": offer["publicationDate"]}

    rds = offers["AmazonRDS"]

    def rds_instance(itype: str, deployment: str):
        needle = f"{itype} {deployment} instance hour"
        return lambda a, d: (
            a.get("databaseEngine") == "PostgreSQL" and needle in d and "Aurora" not in d
        )

    out["rds_postgres"] = {
        "single_az_per_hour": {
            i: pick(rds, rds_instance(i, "Single-AZ"), f"RDS {i}") for i in RDS_INSTANCES
        },
        "multi_az_per_hour": {
            i: pick(rds, rds_instance(i, "Multi-AZ"), f"RDS {i} Multi-AZ")
            for i in RDS_INSTANCES
        },
        "gp3_gb_month": pick(
            rds,
            lambda a, d: "per GB-month of provisioned GP3 storage running PostgreSQL" in d,
            "RDS gp3",
        ),
        "gp3_gb_month_multi_az": pick(
            rds,
            lambda a, d: "GP3 storage for Multi-AZ deployments running PostgreSQL" in d,
            "RDS gp3 Multi-AZ",
        ),
        "backup_gb_month": pick(
            rds,
            lambda a, d: "backup storage exceeding free allocation running PostgreSQL" in d,
            "RDS backup",
        ),
    }

    s3 = offers["AmazonS3"]
    out["s3_standard"] = {
        "storage_tiers": tiers(
            s3,
            lambda a, d: a.get("storageClass") == "General Purpose"
            and "storage used" in d
            and "Annotations" not in d,
        ),
        "put_per_request": pick(
            s3, lambda a, d: d.endswith("per 1,000 PUT, COPY, POST, or LIST requests"),
            "S3 PUT"
        ),
        "get_per_request": pick(
            s3, lambda a, d: d.endswith("per 10,000 GET and all other requests"),
            "S3 GET"
        ),
    }

    ec = offers["AmazonElastiCache"]
    out["elasticache_valkey"] = {
        "serverless_gb_hour": pick(
            ec, lambda a, d: "per GB-hour for Valkey data storage" in d, "Valkey GB-hora"
        ),
        "serverless_ecpu": pick(
            ec, lambda a, d: "per million Valkey ECPUs" in d, "Valkey ECPU"
        ),
        "node_cache.t4g.micro_hour": pick(
            ec, lambda a, d: "T4G Micro Cache node-hour" in d and "Valkey" in d, "t4g.micro"
        ),
        "node_cache.m7g.large_hour": pick(
            ec, lambda a, d: "m7g.large node hour running Valkey" in d, "m7g.large"
        ),
    }

    elb = offers["AWSELB"]
    out["alb"] = {
        "hour": pick(elb, lambda a, d: "per Application LoadBalancer-hour" in d, "ALB hora"),
        "lcu_hour": pick(
            elb,
            lambda a, d: "per used Application load balancer capacity unit-hour" in d,
            "ALB LCU",
        ),
    }

    ecs = offers["AmazonECS"]
    out["fargate_linux_arm"] = {
        "vcpu_hour": pick(
            ecs, lambda a, d: d.startswith("AWS Fargate - ARM - vCPU -"), "Fargate vCPU"
        ),
        "gb_hour": pick(
            ecs, lambda a, d: d.startswith("AWS Fargate - ARM - Memory -"), "Fargate GB"
        ),
    }

    dt = offers["AWSDataTransfer"]
    out["data_transfer_out_internet"] = tiers(
        dt,
        lambda a, d: a.get("toLocation") == "External"
        and "data transfer out" in d
        and "accelerated" not in d,
    )
    return out


def extract_cloudfront(cache: Path) -> dict:
    url = f"{BASE}/offers/v1.0/aws/AmazonCloudFront/current/index.json"
    offer = fetch_json(url, cache)

    def loc(region: str):
        return lambda a, d: (a.get("fromLocation") or a.get("location")) == region

    out = {"source": {"url": url, "publication_date": offer["publicationDate"]}}
    for key, region in (("north_america", "United States"), ("south_america", "South America"),
                        ("europe", "Europe")):
        m = loc(region)
        out[key] = {
            "transfer_tiers": tiers(
                offer, lambda a, d, m=m: m(a, d) and "data transfer out" in d
                and "Origin" not in d
            ),
            "https_per_request": pick(
                offer, lambda a, d, m=m: m(a, d) and d.endswith("HTTPS Requests")
                and "Proxy" not in d and "Field" not in d, f"CloudFront HTTPS {region}"
            ),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True, help="carpeta para los archivos crudos")
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "currency": "USD",
        "note": "Precios on-demand, Linux, sin impuestos. Extraídos de la AWS Price List API pública.",
        "regions": {r: extract_region(r, args.cache) for r in REGIONS},
        "cloudfront": extract_cloudfront(args.cache),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    print(f"snapshot escrito en {args.output}")


if __name__ == "__main__":
    main()
