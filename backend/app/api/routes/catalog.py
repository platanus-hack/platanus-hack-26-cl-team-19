"""``GET /catalog/deployment``: los proveedores y planes que se pueden elegir para cada componente (JAJ-148).

El editor muestra estas opciones en el inspector. Cada plan trae las especificaciones que usa el motor
(vCPU, memoria, conexiones, procesador) y su costo, con procedencia, porque salen del mismo perfil que
``app.catalog.deploy`` (JAJ-143). Elegir uno crea una versión nueva con la operación tipada que también
usa el chat (``change_db_plan``, ``change_api_host`` o ``change_frontend_host``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.catalog import deploy, load_catalog

router = APIRouter(tags=["catalog"])

# En Fargate y local el tamaño se elige en vCPU: el plan es una máquina de ejemplo para mostrar el costo.
SIZED_BY_VCPU = {"fargate", "local"}


def _spec(number: dict[str, Any] | None) -> dict[str, Any] | None:
    if not number:
        return None
    return {k: number.get(k) for k in ("value", "unit", "label", "source")}


def _db_options(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for provider, plans in deploy.db_providers(catalog).items():
        rows = []
        for plan in plans:
            p = deploy.db_profile(provider, plan, "opción del editor", catalog)
            rows.append(
                {
                    "id": plan,
                    "specs": {
                        "vcpu": _spec(p["vcpu"]),
                        "ram_gb": _spec(p["ram_gb"]),
                        "max_connections": _spec(p["max_connections"]),
                        "pooler_connections": _spec(p.get("pooler_connections")),
                        "sustained_vcpu": _spec((p.get("cpu_credits") or {}).get("sustained_vcpu")),
                        "cpu_core_factor": _spec(p["cpu_core_factor"]),
                        "network_rtt_ms": _spec(p["network_rtt_ms"]),
                        "usd_month": _spec(p["usd_month"]),
                    },
                }
            )
        out.append({"id": provider, "label": deploy.PROVIDER_LABELS.get(provider, provider), "plans": rows})
    return out


def _api_options(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    one = {"value": 1, "unit": "", "label": "SUPUESTO", "source": "1 réplica"}
    out = []
    for provider, plans in deploy.app_providers(catalog).items():
        rows = []
        for plan in plans:
            p = deploy.app_profile(provider, plan, one, one, one, "opción del editor", catalog)
            rows.append(
                {
                    "id": plan,
                    "specs": {
                        "vcpu": _spec(p["vcpu"]),
                        "memory_gb": _spec(p["memory_gb"]),
                        "cpu_core_factor": _spec(p["cpu_core_factor"]),
                        "usd_month": _spec(p["usd_month"]),
                    },
                }
            )
        entry = {"id": provider, "label": deploy.PROVIDER_LABELS.get(provider, provider), "plans": rows}
        if provider in SIZED_BY_VCPU:
            p = deploy.app_profile(provider, None, one, one, {**one, "value": 2}, "1 vCPU y 2 GB", catalog)
            entry["sized_by_vcpu"] = True
            entry["example"] = {"cpu_core_factor": _spec(p["cpu_core_factor"]), "usd_month": _spec(p["usd_month"])}
        out.append(entry)
    return out


def _frontend_options(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for provider, plans in deploy.frontend_providers(catalog).items():
        rows = [
            {
                "id": plan,
                "specs": {"usd_month": _spec(deploy.frontend_profile(provider, plan, "opción", catalog)["usd_month"])},
            }
            for plan in plans
        ]
        out.append({"id": provider, "label": deploy.PROVIDER_LABELS.get(provider, provider), "plans": rows})
    return out


def deployment_options() -> dict[str, Any]:
    catalog = load_catalog()
    return {"db": _db_options(catalog), "api": _api_options(catalog), "frontend": _frontend_options(catalog)}


@router.get("/catalog/deployment", summary="Proveedores y planes de la DB, la API y el frontend (JAJ-148)")
def get_deployment_options() -> dict[str, Any]:
    return deployment_options()
