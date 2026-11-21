"""Costo de fallar: ventas en juego por hora según lo que simuló el motor (JAJ-74).

La fórmula es la de JAJ-11: sesiones por hora × fracción que falla × conversión × ticket. Hasta ahora,
``checks.sales_at_stake_per_hour`` de ``build_model.py`` suponía que todo falla, una cota que no usa
la simulación. Aquí la fracción sale del ``Run``.

Una sesión hace varias requests (``traffic.requests_per_session``, 17 en el perfil medio de JAJ-11), y
no se sabe si una sesión con una request fallida pierde la venta. Por eso se entrega un **rango**
(principio del proyecto: rangos, no falsa precisión):

* **piso:** solo se pierde la venta de las sesiones cuya request falló, una por cada error. La
  fracción es la tasa de error ``e``.
* **techo:** se pierde la venta si falla *cualquier* request de la sesión. Con fallas independientes,
  la fracción es ``1 − (1 − e)^k``, con ``k`` requests por sesión.

Si algún recurso pasa el 90 % de uso, el motor es optimista (JAJ-44): la tasa de error es un piso, y
las ventas en juego también ("al menos").

Una simulación corta puede no mostrar errores aunque el sistema esté saturado: el timeout del cliente
es de 30 s, así que en 30 s simulados todavía no vence ninguno (JAJ-71). En ese caso ``too_short`` es
verdadero y el mensaje pide simular más tiempo, en vez de decir que no hay ventas en juego.

Las sesiones por hora salen de las requests que llegaron en el ``Run``. Con un perfil de tráfico
(JAJ-71) es el promedio del perfil, no el pico.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from app.models.architecture import value
from app.models.run import Run

LABELS = ("OBSERVADO", "CALIBRADO", "ESTIMADO", "SUPUESTO")
SATURATION = 0.9  # mismo umbral que el motor (SATURATION_WARNING, JAJ-44)


def _weakest(*labels: str | None) -> str:
    return max((lab for lab in labels if lab in LABELS), key=LABELS.index, default="SUPUESTO")


def _num(v: float, unit: str, label: str, source: str) -> dict[str, Any]:
    return {
        "value": v,
        "unit": unit,
        "label": label,
        "source": source,
        "date": date.today().isoformat(),
        "derived": True,
    }


@dataclass
class FailureCost:
    sessions_per_hour: dict[str, Any]
    error_rate: float  # tasa de error del Run (0 a 1)
    session_failure: dict[str, float]  # fracción de sesiones afectadas: {"low": e, "high": 1 − (1 − e)^k}
    lost_sales_per_hour: dict[str, Any]  # rango en US$/hora: {"low", "high"}, cada uno con procedencia
    at_stake_per_hour: dict[str, Any]  # si fallara todo (la cota de build_model.py)
    is_floor: bool  # algún recurso sobre el 90 %: la pérdida es "al menos"
    too_short: bool  # saturado y sin errores todavía: la simulación no alcanzó a mostrar los timeouts
    message: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# los datos del modelo que necesita el costo de fallar, con su nombre para mostrar (JAJ-128)
FAILURE_INPUTS = {
    "traffic.requests_per_session": "las requests por sesión",
    "business.conversion": "la tasa de conversión",
    "business.ticket_usd": "el ticket promedio",
}


def failure_missing(raw: dict[str, Any]) -> list[str]:
    """Los datos de ``FAILURE_INPUTS`` que le faltan al modelo (por ruta, ej. ``business.conversion``).
    Vacía si están todos: entonces ``failure_cost`` se puede calcular (JAJ-128)."""
    missing = []
    for path in FAILURE_INPUTS:
        section, key = path.split(".")
        x = (raw.get(section) or {}).get(key)
        if not (isinstance(x, dict) and value(x)):
            missing.append(path)
    return missing


def describe_failure_missing(missing: list[str]) -> str:
    """'El costo de fallar no se calcula: al modelo le falta la tasa de conversión y el ticket promedio
    (business.conversion, business.ticket_usd).'"""
    names = [FAILURE_INPUTS[p] for p in missing]
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" y {names[-1]}"
    return f"El costo de fallar no se calcula: al modelo le falta {listed} ({', '.join(missing)})."


def failure_cost(raw: dict[str, Any], run: Run) -> FailureCost | None:
    """Ventas en juego por hora del ``Run``. ``None`` si el modelo no trae conversión, ticket o requests
    por sesión (``failure_missing`` dice cuáles)."""
    if failure_missing(raw):
        return None
    t, biz = raw["traffic"], raw["business"]
    per_session, conversion, ticket = t["requests_per_session"], biz["conversion"], biz["ticket_usd"]
    k, conv, tick = value(per_session), value(conversion), value(ticket)

    rps = run.requests / run.duration_s if run.duration_s else 0.0
    sessions_h = rps * 3600 / k
    label = _weakest(per_session.get("label"), conversion.get("label"), ticket.get("label"), "SUPUESTO")
    e = run.error_rate
    low, high = e, 1 - (1 - e) ** k
    value_per_session = conv * tick
    is_floor = any(r.utilization >= SATURATION for r in run.resources)

    src = (
        f"sesiones/hora × fracción que falla × conversión ({conv:g}) × ticket (US${tick:g}) (JAJ-11); "
        f"sesiones/hora = req/s del Run × 3600 / {k:g} requests por sesión"
    )
    # de dónde salen la conversión y el ticket: del modelo o del escenario (JAJ-131)
    origin = "; ".join(
        f"{name}: {x['source']}" for name, x in (("conversión", conversion), ("ticket", ticket)) if x.get("source")
    )
    if origin:
        src += f" ({origin})"
    lost = {
        "low": _num(round(sessions_h * low * value_per_session, 0), "US$/hora", label, f"{src}. Piso: fracción = e"),
        "high": _num(
            round(sessions_h * high * value_per_session, 0),
            "US$/hora",
            label,
            f"{src}. Techo: fracción = 1 − (1 − e)^{k:g}, si falla cualquier request de la sesión",
        ),
    }
    at_stake = _num(round(sessions_h * value_per_session, 0), "US$/hora", label, f"{src}. Si fallara todo")

    warnings = []
    if is_floor:
        warnings.append(
            "Algún recurso pasa el 90 % de uso: el motor es optimista ahí (JAJ-44), así que la tasa de error y "
            "las ventas en juego son un piso (al menos)."
        )
    if run.in_flight:
        warnings.append(
            f"{run.in_flight} requests seguían en curso al terminar y no cuentan como error: con una simulación "
            "más larga la tasa de error puede subir."
        )
    lo, hi = value(lost["low"]), value(lost["high"])
    too_short = e == 0 and is_floor and run.in_flight > 0
    if too_short:
        message = (
            f"Sin errores todavía, pero el sistema está saturado y {run.in_flight} requests seguían esperando: "
            f"la simulación ({run.duration_s:g} s) es muy corta para ver los timeouts. Simula más tiempo "
            "(ej. 120 s o un perfil de tráfico) antes de leer las ventas en juego."
        )
    elif e == 0:
        message = "Sin errores en la simulación: no hay ventas en juego."
    else:
        prefix = "al menos " if is_floor else ""
        message = (
            f"Con {e:.1%} de errores, {prefix}US${lo:,.0f} a US${hi:,.0f} por hora en ventas en juego "
            f"(US${value(at_stake):,.0f}/hora si fallara todo)."
        )
    return FailureCost(
        sessions_per_hour=_num(round(sessions_h, 1), "sesiones/hora", label, src),
        error_rate=e,
        session_failure={"low": round(low, 4), "high": round(high, 4)},
        lost_sales_per_hour=lost,
        at_stake_per_hour=at_stake,
        is_floor=is_floor,
        too_short=too_short,
        message=message,
        warnings=warnings,
    )
