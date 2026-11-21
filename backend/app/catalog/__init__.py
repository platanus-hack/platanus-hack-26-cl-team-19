"""Catálogo de números por defecto del modelo v1, con su procedencia (JAJ-8, JAJ-11, JAJ-45, JAJ-46, JAJ-47).

``catalog.json`` es una copia de ``spikes/jaj-45-numeros/catalog.json``, que es la fuente que usa
``build_model.py``. Está aquí para que el backend no dependa de la carpeta de spikes al desplegarse.
``tests/models/test_catalog.py`` falla si las dos copias dejan de ser iguales: cuando cambie el
catálogo del spike, hay que copiarlo de nuevo.

Las funciones arman los números como los arma ``build_model.py``: ``{"value", "unit", "label",
"source", "date"}``. Así, lo que agrega una operación (JAJ-68) se ve igual que lo que vino del repo.
"""

from __future__ import annotations

import json
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).parent / "catalog.json"
HOURS_MONTH = 730  # el mismo que usa build_model.py para pasar US$/hora a US$/mes (JAJ-11)

# de más a menos respaldo (JAJ-8)
LABELS = ("OBSERVADO", "CALIBRADO", "ESTIMADO", "SUPUESTO")


@cache
def _raw() -> str:
    return CATALOG_PATH.read_text(encoding="utf-8")


def catalog() -> dict[str, Any]:
    """El catálogo como dict (una copia nueva cada vez, para que nadie lo modifique sin querer)."""
    return json.loads(_raw())


def today() -> str:
    return date.today().isoformat()


def num(value: Any, unit: str, label: str, source: str, **extra: Any) -> dict[str, Any]:
    """Un número del modelo v1 con su procedencia."""
    if label not in LABELS:
        raise ValueError(f"Etiqueta de procedencia desconocida: {label}")
    out = {"value": value, "unit": unit, "label": label, "source": source, "date": extra.pop("date", today())}
    out.update(extra)
    return out


def from_catalog(entry: dict[str, Any], **over: Any) -> dict[str, Any]:
    """Un número del catálogo, con su etiqueta, fuente y fecha. ``over`` reemplaza campos."""
    return num(
        over.pop("value", entry.get("value")),
        over.pop("unit", entry["unit"]),
        over.pop("label", entry["label"]),
        over.pop("source", entry["source"]),
        date=over.pop("date", entry.get("date", today())),
        **over,
    )


def weakest(*labels: str) -> str:
    """La etiqueta con menos respaldo: un número calculado vale lo que su entrada más débil."""
    return max(labels, key=LABELS.index)


def db_plans(provider: str) -> dict[str, Any]:
    """Planes de DB de un proveedor (``supabase``, ``rds_postgres``, ``local``), sin las claves internas."""
    plans = catalog()["db_plans"].get(provider)
    if not isinstance(plans, dict):
        return {}
    return {name: plan for name, plan in plans.items() if isinstance(plan, dict)}


def db_plan_source(provider: str, plan: str) -> str:
    return f"{catalog()['db_plans']['_sources'][provider]}. Plan {provider} {plan} del catálogo"


def db_usd_month(provider: str, plan: dict[str, Any]) -> float:
    """Costo mensual de la DB, con la misma fórmula que build_model.py (JAJ-11)."""
    plans = catalog()["db_plans"]
    if provider == "supabase":
        compute = plan["compute_usd_month"] - plans["supabase_compute_credit_usd_month"]
        return round(plans["supabase_base_usd_month"] + max(0, compute), 2)
    return round(plan["usd_hour"] * HOURS_MONTH, 2)


def core_factor(plan: dict[str, Any], where: str) -> dict[str, Any]:
    """``cpu_core_factor`` del procesador del plan (JAJ-46), como lo arma build_model.py."""
    proc = plan.get("processor", "local")
    factors = catalog()["cpu_core_factor"]
    f = factors[proc]
    label = weakest(f["label"], plan.get("processor_label", f["label"]))
    return num(f["value"], "×", label, f"{where}: procesador {proc}. {f['source']}. {factors['_doc']}", processor=proc)


def cpu_credits(plan_name: str, vcpu: dict[str, Any]) -> dict[str, Any] | None:
    """Base de créditos de CPU de las instancias ``db.t4g.*`` (JAJ-46), o ``None`` si el plan no tiene créditos."""
    base = catalog()["burstable_baseline_per_vcpu"].get(plan_name)
    if base is None:
        return None
    per_vcpu = from_catalog(base)
    sustained = num(
        round(vcpu["value"] * per_vcpu["value"], 3),
        "vCPU",
        weakest(vcpu["label"], per_vcpu["label"]),
        f"vCPU × base por vCPU: lo que rinde {plan_name} con carga sostenida. En modo unlimited rinde los vCPU "
        "nominales y cobra el exceso",
        derived=True,
    )
    return {"baseline_per_vcpu": per_vcpu, "sustained_vcpu": sustained}
