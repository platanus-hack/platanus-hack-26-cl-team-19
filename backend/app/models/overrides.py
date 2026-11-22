"""Reemplazos de un escenario (JAJ-131): lo que cambia la situación, no la arquitectura.

Un escenario siempre cambió cuánto tráfico llega (y su forma en el tiempo). Estos reemplazos cambian,
solo para una corrida, tres cosas que el motor ya simula pero que viven fijas en el modelo:

* ``endpoint_weights``: la mezcla de endpoints. En un CyberDay pesan más ``/checkout`` y
  ``/products``. Los endpoints que no aparecen conservan su peso; el motor normaliza como siempre.
* ``slowdowns``: dependencias más lentas (o más rápidas). La clave es el id del nodo en el grafo
  (``POST /graph``): ``db``, ``cache``, ``external`` (los servicios externos sin nombre) o
  ``external:<servicio>``. El valor multiplica el tiempo de sus pasos: ``{"external:pagos": 10}``.
  Así el editor puede degradar una dependencia desde su nodo.
* ``business``: conversión y ticket promedio para el costo de fallar de esa corrida (JAJ-74).

``apply_overrides`` devuelve **una copia** del modelo con los cambios y una frase por reemplazo, para
el ``Run`` y el resumen. No crea versiones: el modelo guardado no cambia. Los números que pone llevan
procedencia ("Escenario: …"), con la etiqueta SUPUESTO, porque los declara el usuario sin medición.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from app.models.architecture import RESOURCE_CACHE, RESOURCE_DB_CONNECTION, value

RESOURCE_EXTERNAL = "external"
BUSINESS_FIELDS = {"conversion": ("fracción", "conversión"), "ticket_usd": ("US$", "ticket promedio")}


class OverrideError(ValueError):
    """Un reemplazo que no calza con el modelo. ``available`` son los valores que sí existen."""

    def __init__(self, message: str, available: list[str]) -> None:
        super().__init__(message)
        self.available = available


def _slug(name: str) -> str:
    # el mismo id que usa el grafo para un servicio externo (app/models/graph.py)
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "servicio"


def _secondary_services(raw: dict[str, Any]) -> set[str]:
    """Servicios que son otro repo del proyecto (IA-5): en el grafo son ``service:<x>``, no se simulan."""
    services = (raw.get("deployment") or {}).get("services") or []
    return {s["name"].lower() for s in services if s.get("origin") and s.get("role") == "service" and s.get("name")}


def _node_of(step: dict[str, Any], secondary: set[str]) -> str | None:
    """El id del nodo del grafo al que pertenece el paso, para ``slowdowns``."""
    resource = step.get("resource")
    if resource == RESOURCE_DB_CONNECTION:
        return "db"
    if resource == RESOURCE_CACHE:
        return "cache"
    if resource == RESOURCE_EXTERNAL:
        service = step.get("service")
        if not service:
            return "external"
        prefix = "service" if service.lower() in secondary else "external"
        return f"{prefix}:{_slug(service)}"
    return None


def _all_steps(raw: dict[str, Any]):
    """Todos los pasos del modelo, de los endpoints y de los trabajos de las colas, con los de on_miss."""

    def walk(steps):
        for s in steps or []:
            yield s
            yield from walk(s.get("on_miss"))

    for e in raw.get("endpoints") or []:
        yield from walk(e.get("steps"))
    for q in ((raw.get("deployment") or {}).get("queues") or {}).values():
        yield from walk(q.get("job_steps"))


def slowdown_targets(raw: dict[str, Any]) -> list[str]:
    """Los nodos que se pueden hacer más lentos en este modelo (los que tienen pasos con tiempo)."""
    secondary = _secondary_services(raw)
    return sorted({n for s in _all_steps(raw) if (n := _node_of(s, secondary))})


def _times(x: float) -> str:
    return f"×{x:g}".replace(".", ",")


def apply_overrides(
    raw: dict[str, Any],
    endpoint_weights: dict[str, float] | None = None,
    slowdowns: dict[str, float] | None = None,
    business: dict[str, float] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """El modelo con los reemplazos del escenario (una copia) y una frase por cada uno.

    ``OverrideError`` si un reemplazo no calza: un endpoint o un nodo que el modelo no tiene, o una
    mezcla que deja todos los pesos en 0."""
    if not (endpoint_weights or slowdowns or business):
        return raw, []
    out = copy.deepcopy(raw)
    notes: list[str] = []

    if endpoint_weights:
        endpoints = {e["id"]: e for e in out.get("endpoints") or []}
        unknown = sorted(set(endpoint_weights) - set(endpoints))
        if unknown:
            raise OverrideError(
                f"El modelo no tiene {'el endpoint' if len(unknown) == 1 else 'los endpoints'} "
                f"{', '.join(unknown)}. Hay: {', '.join(sorted(endpoints))}.",
                sorted(endpoints),
            )
        for eid, w in endpoint_weights.items():
            endpoints[eid]["weight"] = {
                "value": w,
                "unit": "peso",
                "label": "SUPUESTO",
                "source": "Escenario: mezcla de endpoints",
            }
        total = sum(float(value(e.get("weight"), 0.0)) for e in endpoints.values())
        if total <= 0:
            raise OverrideError("Con esa mezcla todos los endpoints quedan con peso 0: no hay tráfico.", [])
        shares = ", ".join(
            f"{eid} {float(value(endpoints[eid]['weight'])) / total:.0%}".replace("%", " %")
            for eid in sorted(endpoint_weights, key=lambda k: -endpoint_weights[k])
        )
        notes.append(f"Mezcla de endpoints del escenario: {shares} del tráfico (el resto, como en el modelo).")

    if slowdowns:
        secondary = _secondary_services(out)
        available = slowdown_targets(out)
        unknown = sorted(set(slowdowns) - set(available))
        if unknown:
            raise OverrideError(
                f"El modelo no tiene {'el nodo' if len(unknown) == 1 else 'los nodos'} {', '.join(unknown)} "
                f"para hacer más lento. Hay: {', '.join(available) or 'ninguno'}.",
                available,
            )
        for step in _all_steps(out):
            factor = slowdowns.get(_node_of(step, secondary) or "")
            if factor is None or step.get("time") is None:
                continue
            t = step["time"]
            if isinstance(t, dict):
                source = t.get("source")
                step["time"] = {
                    **t,
                    "value": float(value(t, 0.0)) * factor,
                    "source": f"{source} {_times(factor)} (escenario)" if source else f"escenario {_times(factor)}",
                }
            else:
                step["time"] = float(t) * factor
        parts = ", ".join(f"{node} {_times(f)}" for node, f in sorted(slowdowns.items()))
        notes.append(f"Dependencias del escenario: {parts} el tiempo de sus pasos.")

    if business:
        biz = out.setdefault("business", {})
        said = []
        for key, v in business.items():
            unit, name = BUSINESS_FIELDS[key]
            biz[key] = {"value": v, "unit": unit, "label": "SUPUESTO", "source": f"Declarado en el escenario: {name}"}
            said.append(f"{name} {v:.1%}".replace("%", " %") if key == "conversion" else f"{name} US${v:g}")
        notes.append(f"Negocio del escenario: {' y '.join(said)}, para el costo de fallar.")

    return out, notes
