"""Dónde está desplegado cada componente y qué rinde ahí (JAJ-143).

Cada componente del ``deployment`` (la DB, la API y el frontend) corre en un proveedor y un plan del
catálogo. El perfil de ese plan define a la vez lo que simula el motor (vCPU, conexiones, procesador,
red) y lo que cuesta, así que el rendimiento y el precio salen de la misma fuente.

Lo usan la ingesta (``build_model``), las operaciones del agente (``ops``) y la estimación de costos.
Todo número trae ``value``, ``unit``, ``label`` y ``source``, como el resto del modelo (ADR 0001).

* ``db_profile``: plan de la DB (Supabase, RDS, Neon, local).
* ``app_profile``: dónde corre la API. En Fargate (y local) se paga por vCPU y GB; en Fly y Render, por plan.
* ``frontend_profile``: dónde se sirve el frontend (Vercel, CloudFront, local). No cambia la simulación.
* ``db_provider_from_host`` y ``app_provider_from_target``: el proveedor a partir de lo que dice el repo.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.catalog import load_catalog
from app.costs.prices import manual_block

HOURS_MONTH = 730
RANK = {"OBSERVADO": 0, "CALIBRADO": 1, "ESTIMADO": 2, "SUPUESTO": 3}

# Proveedores de DB que solo ofrecen PostgreSQL: el motor se deduce del proveedor.
POSTGRES_PROVIDERS = {"supabase": "Supabase", "rds_postgres": "Amazon RDS", "neon": "Neon"}

# Host de la URL de conexión → proveedor de la DB. Los hosts son los que documenta cada proveedor.
DB_HOSTS = [
    (re.compile(r"\.neon\.tech\b|\.neon\.build\b"), "neon"),
    (re.compile(r"\.supabase\.(co|com)\b|pooler\.supabase\.com"), "supabase"),
    (re.compile(r"\.rds\.amazonaws\.com\b"), "rds_postgres"),
]

# Destino del despliegue que encontró la IaC (``iac.deploy_targets``) → proveedor de la API.
APP_TARGETS = {
    "fly": "fly",
    "render": "render",
    "aws ecs": "fargate",
    "aws (terraform)": "fargate",
}
FRONTEND_TARGETS = {"vercel": "vercel", "cloudfront": "cloudfront"}


class UnknownPlan(ValueError):
    """El proveedor o el plan no están en el catálogo. El mensaje dice cuáles hay."""


def _num(value: Any, unit: str, label: str, source: str, **extra: Any) -> dict[str, Any]:
    out = {"value": value, "unit": unit, "label": label, "source": source, "date": date.today().isoformat()}
    if label == "SUPUESTO":
        out["needs_review"] = True
    out.update(extra)
    return out


def weakest(*labels: str) -> str:
    return max(labels, key=lambda lab: RANK[lab])


def _providers(section: dict[str, Any]) -> list[str]:
    return [k for k, v in section.items() if isinstance(v, dict) and not k.startswith("_")]


def _plans(entry: dict[str, Any]) -> dict[str, Any]:
    """Los planes de un proveedor: los de Fly, Render y el frontend van en ``plans``; los de la DB, directo."""
    return entry["plans"] if "plans" in entry else {k: v for k, v in entry.items() if not k.startswith("_")}


def db_providers(catalog: dict[str, Any] | None = None) -> dict[str, list[str]]:
    plans = (catalog or load_catalog())["db_plans"]
    return {p: list(_plans(plans[p])) for p in _providers(plans)}


def app_providers(catalog: dict[str, Any] | None = None) -> dict[str, list[str]]:
    plans = (catalog or load_catalog())["app_plans"]
    return {p: list(plans[p]["plans"]) if "plans" in plans[p] else [] for p in _providers(plans)}


def _frontend_plans(entry: dict[str, Any]) -> dict[str, Any]:
    """Los planes del frontend con su US$/mes. Los de CloudFront salen de ``manual.json`` (JAJ-11)."""
    if "prices" in entry:
        return {k: {"usd_month": v["usd"]} for k, v in manual_block(entry["prices"])["plans_month"].items()}
    return entry["plans"]


def frontend_providers(catalog: dict[str, Any] | None = None) -> dict[str, list[str]]:
    plans = (catalog or load_catalog())["frontend_plans"]
    return {p: list(_frontend_plans(plans[p])) for p in _providers(plans)}


def _known(options: dict[str, list[str]]) -> str:
    return "; ".join(f"{p}: {', '.join(plans)}" if plans else p for p, plans in options.items())


def core_factor(catalog: dict[str, Any], plan: dict[str, Any], where: str) -> dict[str, Any]:
    """Cuántas veces más lento es 1 vCPU del plan que el núcleo donde se calibraron los tiempos (JAJ-46)."""
    proc = plan.get("processor", "local")
    f = catalog["cpu_core_factor"][proc]
    label = weakest(f["label"], plan.get("processor_label", f["label"]))
    return _num(
        f["value"],
        "×",
        label,
        f"{where}: procesador {proc}. {f['source']}. {catalog['cpu_core_factor']['_doc']}",
        processor=proc,
    )


def network_rtt(catalog: dict[str, Any], provider: str) -> dict[str, Any]:
    """Ida y vuelta API ↔ DB por consulta: 0 en local (ya está en la calibración), 1 ms en la nube."""
    entry = catalog["network_rtt_ms"]["local" if provider == "local" else "same_region"]
    return _num(entry["value"], entry["unit"], entry["label"], entry["source"])


def db_profile(provider: str, plan_name: str, why: str, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Los campos de ``deployment.db`` que dependen del plan. ``why``: por qué es este plan (quién lo dijo)."""
    catalog = catalog or load_catalog()
    plans = catalog["db_plans"]
    options = db_providers(catalog)
    if provider not in options:
        raise UnknownPlan(f"La DB en '{provider}' no está en el catálogo. Hay: {_known(options)}.")
    plan = _plans(plans[provider]).get(plan_name)
    if plan is None:
        raise UnknownPlan(
            f"{provider} no tiene el plan '{plan_name}' en el catálogo. Hay: {', '.join(options[provider])}."
        )
    src = f"{plans['_sources'][provider]}. Plan {provider} {plan_name}: {why}"
    if provider == "supabase":
        usd = plans["supabase_base_usd_month"] + max(
            0, plan["compute_usd_month"] - plans["supabase_compute_credit_usd_month"]
        )
        formula = "Supabase: 25 + max(0, compute − 10)"
    elif provider == "neon":
        neon = manual_block("neon")
        usd = plan["cu"] * neon["cu_hour"]["launch"] * HOURS_MONTH
        formula = f"CU × US$/CU-hora del plan Launch × {HOURS_MONTH} h, sin escalar a cero ({neon['source']})"
    else:
        usd = plan["usd_hour"] * HOURS_MONTH
        formula = f"US$/hora × {HOURS_MONTH} h"
    out: dict[str, Any] = {
        "provider": provider,
        "plan": plan_name,
        "vcpu": _num(plan["vcpu"], "vCPU", plan["vcpu_label"], src),
        "ram_gb": _num(plan["ram_gb"], "GB", "ESTIMADO", src),
        "max_connections": _num(plan["max_connections"], "conexiones", "ESTIMADO", src),
        "usd_month": _num(round(usd, 2), "US$/mes", "ESTIMADO", f"{src}. {formula}"),
        "cpu_core_factor": core_factor(catalog, plan, f"Plan {provider} {plan_name}"),
        "network_rtt_ms": network_rtt(catalog, provider),
    }
    base = catalog["burstable_baseline_per_vcpu"].get(plan_name)
    if base is not None:
        per_vcpu = {k: v for k, v in base.items()}
        out["cpu_credits"] = {
            "baseline_per_vcpu": per_vcpu,
            "sustained_vcpu": _num(
                round(plan["vcpu"] * base["value"], 3),
                "vCPU",
                weakest(plan["vcpu_label"], base["label"]),
                f"vCPU × base por vCPU: lo que rinde {plan_name} con carga sostenida. En modo unlimited rinde "
                "los vCPU nominales y cobra el exceso",
                derived=True,
            ),
        }
    if "pooler_connections" in plan:
        out["pooler_connections"] = _num(plan["pooler_connections"], "conexiones", "ESTIMADO", src)
    if provider in POSTGRES_PROVIDERS:
        out["technology"] = technology(
            "PostgreSQL",
            None,
            "ESTIMADO",
            f"{POSTGRES_PROVIDERS[provider]} solo ofrece PostgreSQL",
        )
    return out


def app_profile(
    provider: str,
    plan_name: str | None,
    replicas: dict[str, Any],
    vcpu: dict[str, Any],
    memory_gb: dict[str, Any],
    why: str,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Los campos de ``deployment.api`` que dependen de dónde corre.

    En Fargate y local el tamaño lo dan ``vcpu`` y ``memory_gb`` (se paga por vCPU-hora y GB-hora). En
    Fly y Render el plan fija los vCPU y la memoria: el resultado los trae y reemplazan a los recibidos."""
    catalog = catalog or load_catalog()
    plans = catalog["app_plans"]
    options = app_providers(catalog)
    if provider not in options:
        raise UnknownPlan(f"La API en '{provider}' no está en el catálogo. Hay: {_known(options)}.")
    entry = plans[provider]
    out: dict[str, Any] = {"provider": provider}
    if "plans" in entry:
        if plan_name is None:
            raise UnknownPlan(f"En {provider} hay que elegir un plan. Hay: {', '.join(options[provider])}.")
        plan = entry["plans"].get(plan_name)
        if plan is None:
            raise UnknownPlan(f"{provider} no tiene el plan '{plan_name}'. Hay: {', '.join(options[provider])}.")
        src = f"{entry['_source']}. Plan {provider} {plan_name}: {why}"
        vcpu = _num(plan["vcpu"], "vCPU", "ESTIMADO", src)
        memory_gb = _num(plan["memory_gb"], "GB", "ESTIMADO", src)
        usd = replicas["value"] * plan["usd_month"]
        out.update(
            plan=plan_name,
            vcpu=vcpu,
            memory_gb=memory_gb,
            usd_month=_num(
                round(usd, 2),
                "US$/mes",
                weakest("ESTIMADO", replicas["label"]),
                f"{src}. réplicas × US$/mes del plan",
            ),
        )
    else:
        if plan_name is not None:
            raise UnknownPlan(f"En {provider} el tamaño se da con vCPU y memoria, no con un plan.")
        usd = (
            replicas["value"]
            * (vcpu["value"] * entry["usd_vcpu_hour"] + memory_gb["value"] * entry["usd_gb_hour"])
            * HOURS_MONTH
        )
        out.update(
            plan=None,
            usd_month=_num(
                round(usd, 2),
                "US$/mes",
                "ESTIMADO",
                f"{plans['_source']}. réplicas × (vCPU × US$/vCPU-h + GB × US$/GB-h) × {HOURS_MONTH} h",
            ),
        )
        plan = entry
    out["cpu_core_factor"] = core_factor(catalog, plan, f"API en {provider}" + (f" {plan_name}" if plan_name else ""))
    return out


def frontend_profile(provider: str, plan_name: str, why: str, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """``deployment.frontend``: dónde se sirve el frontend y cuánto cuesta. El motor no lo simula."""
    catalog = catalog or load_catalog()
    plans = catalog["frontend_plans"]
    options = frontend_providers(catalog)
    if provider not in options:
        raise UnknownPlan(f"El frontend en '{provider}' no está en el catálogo. Hay: {_known(options)}.")
    plan = _frontend_plans(plans[provider]).get(plan_name)
    if plan is None:
        raise UnknownPlan(f"{provider} no tiene el plan '{plan_name}'. Hay: {', '.join(options[provider])}.")
    src = f"{plans[provider]['_source']}. Plan {provider} {plan_name}: {why}"
    return {
        "provider": provider,
        "plan": plan_name,
        "usd_month": _num(plan["usd_month"], "US$/mes", "ESTIMADO", src),
        "simulated": False,
    }


def technology(name: str, version: str | None, label: str, source: str, **extra: Any) -> dict[str, Any]:
    """Bloque ``technology`` de un componente (JAJ-87): qué es, con procedencia como cualquier número."""
    out: dict[str, Any] = {"name": name, "version": version, "label": label, "source": source}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def db_provider_from_host(text: str) -> str | None:
    """El proveedor de la DB según el host de una URL de conexión (``ep-x.us-east-2.aws.neon.tech``)."""
    for rx, provider in DB_HOSTS:
        if rx.search(text.lower()):
            return provider
    return None


def app_provider_from_target(target: str) -> str | None:
    return APP_TARGETS.get(target)


def frontend_provider_from_target(target: str) -> str | None:
    return FRONTEND_TARGETS.get(target)
