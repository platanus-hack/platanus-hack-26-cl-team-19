"""Arma el reporte de una corrida y el de una comparación (JAJ-127). Ver ``app/reports/__init__.py``.

Diagnóstico por componente (un componente es un nodo del diagrama: ``api``, ``db``, ``queue:<nombre>``):

* **uso:** el promedio del recurso más ocupado del componente durante la corrida, y su pico por segundo.
* **estado:** ``overloaded`` si el uso promedio llega a ``OVERLOADED`` o el sistema dejó requests sin atender
  y el componente es el cuello de botella; ``idle`` si el uso pico no llega a ``IDLE`` y el componente cuesta
  algo; si no, ``ok``. Los umbrales los eligió el equipo: van con etiqueta ``SUPUESTO``.
* **margen hasta saturar:** req/s de la corrida ÷ uso promedio. Es una aproximación lineal (``ESTIMADO``):
  el uso crece con el tráfico hasta que el recurso se llena, pero las colas no son lineales cerca del 100 %.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.costs import CostEstimate, FailureCost
from app.models.compare import model_changes
from app.models.run import Run
from app.reports import es

REPORT_SCHEMA = "branchpoint.report/v1"
OVERLOADED = 0.8
IDLE = 0.3
TOP_ENDPOINTS = 10
TOP_ASSUMPTIONS = 10
TOP_CHANGES = 30

_THRESHOLDS = {
    "overloaded": {
        "value": OVERLOADED,
        "unit": "fracción",
        "label": "SUPUESTO",
        "source": "Umbral elegido por el equipo: un recurso sobre 80 % de uso promedio tiene poco margen para picos",
    },
    "idle": {
        "value": IDLE,
        "unit": "fracción",
        "label": "SUPUESTO",
        "source": "Umbral elegido por el equipo: un componente pagado que no llega a 30 % ni en su pico está holgado",
    },
}
_COMPONENT_NAMES = {"api": "API", "db": "Base de datos", "cache": "Caché", "frontend": "Frontend"}
# el nombre en una frase, con su artículo, y si es femenino (para "sobrecargada" o "sobrecargado")
_IN_SENTENCE = {
    "api": ("la API", True),
    "db": ("la base de datos", True),
    "cache": ("la caché", True),
    "frontend": ("el frontend", False),
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _num(value: float | None, unit: str, label: str, source: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "label": label, "source": source}


def _node(resource: str) -> str:
    if resource.startswith("queue:"):
        return resource
    return resource.split("_", 1)[0]  # api_cpu, api_threads → api; db_cpu, db_pool → db


def _component_label(node: str) -> str:
    if node.startswith("queue:"):
        return f"Cola {node.split(':', 1)[1]}"
    return _COMPONENT_NAMES.get(node, node)


def _components(run: Run, cost: CostEstimate) -> list[dict[str, Any]]:
    peaks: dict[str, float] = {}
    for second in run.series:
        for name, used in second.utilization.items():
            peaks[name] = max(peaks.get(name, 0.0), used)
    by_node: dict[str, list[dict[str, Any]]] = {}
    offered = run.saturation.offered_rps if run.saturation else run.rps
    for r in run.resources:
        saturates = round(offered / r.utilization, 2) if r.utilization > 0 and offered else None
        by_node.setdefault(_node(r.name), []).append(
            {
                "id": r.name,
                "label": r.label,
                "capacity": r.capacity,
                "utilization": round(r.utilization, 4),
                "peak_utilization": round(peaks.get(r.name, r.utilization), 4),
                "max_queue": r.max_queue,
                "timeouts": r.timeouts,
                "saturates_at_rps": _num(
                    saturates,
                    "req/s",
                    "ESTIMADO",
                    f"req/s de la corrida ({es.num(offered, 2)}) ÷ uso promedio ({es.pct(r.utilization)}): "
                    "aproximación lineal",
                )
                if saturates is not None
                else None,
            }
        )
    cost_by_node: dict[str, float] = {}
    for line in cost.lines:
        if line.node:
            cost_by_node[line.node] = cost_by_node.get(line.node, 0.0) + float(line.usd_month.get("value") or 0.0)
    unanswered = bool(run.saturation and run.saturation.unanswered)
    bottleneck_node = _node(run.bottleneck.resource) if run.bottleneck.resource else None
    out = []
    for node, resources in by_node.items():
        busiest = max(resources, key=lambda r: r["utilization"])
        peak = max(r["peak_utilization"] for r in resources)
        priced = node not in cost.missing and cost_by_node.get(node, 0.0) > 0
        usd = round(cost_by_node[node], 2) if node in cost_by_node else None
        if busiest["utilization"] >= OVERLOADED or (unanswered and node == bottleneck_node):
            status, why = (
                "overloaded",
                (
                    f"{busiest['label']} al {es.pct(busiest['utilization'], 0)} de uso promedio"
                    + (" y quedaron requests sin atender" if unanswered and node == bottleneck_node else "")
                ),
            )
        elif priced and peak < IDLE:
            status, why = "idle", f"no pasa del {es.pct(peak, 0)} de uso ni en su pico y cuesta {es.usd(usd)}/mes"
        else:
            status, why = "ok", f"{busiest['label']} al {es.pct(busiest['utilization'], 0)} de uso promedio"
        # ya saturado (uso promedio cerca del 100 %): no hay margen que estimar
        saturating = [r["saturates_at_rps"] for r in resources if r["saturates_at_rps"] and r["utilization"] < 0.95]
        first = min(saturating, key=lambda s: s["value"]) if saturating else None
        out.append(
            {
                "id": node,
                "label": _component_label(node),
                "status": status,
                "why": why,
                "utilization": busiest["utilization"],
                "peak_utilization": peak,
                "usd_month": usd,
                "priced": priced,
                "saturates_at_rps": first,
                "headroom_x": round(first["value"] / offered, 2) if first and offered else None,
                "resources": resources,
            }
        )
    out += _cost_only_components(run, cost, cost_by_node, set(by_node))
    order = {"overloaded": 0, "idle": 1, "ok": 2}
    return sorted(out, key=lambda c: (order[c["status"]], -(c["utilization"] or 0.0)))


def _cost_only_components(
    run: Run, cost: CostEstimate, cost_by_node: dict[str, float], simulated: set[str]
) -> list[dict[str, Any]]:
    """Los componentes que cuestan pero no tienen un recurso en el motor, como la caché o el frontend (JAJ-164).

    Sin esto, la tabla dejaba fuera a la caché aunque el diagrama y Costos la mostraran. Van con estado ``ok`` y
    sin uso (``None``, que el editor muestra como «—»): el motor no simula su ocupación. La caché dice sus
    aciertos, que sí salen de la corrida."""
    out = []
    for node, usd in cost_by_node.items():
        if node in simulated:
            continue
        why = "El motor no simula su uso: aparece por su costo"
        if node == "cache" and run.cache is not None and run.cache.hit_rate is not None:
            total = run.cache.hits + run.cache.misses
            why = f"Acertó {es.pct(run.cache.hit_rate)} de {es.num(total, 0)} consultas. {why}"
        out.append(
            {
                "id": node,
                "label": _component_label(node),
                "status": "ok",
                "why": why,
                "utilization": None,
                "peak_utilization": None,
                "usd_month": round(usd, 2),
                "priced": node not in cost.missing and usd > 0,
                "saturates_at_rps": None,
                "headroom_x": None,
                "resources": [],
            }
        )
    return out


def _assumptions(model: dict[str, Any], scenario_source: str | None = None) -> dict[str, Any]:
    """Los supuestos del modelo, con el escenario de la corrida primero.

    Los escenarios que trae el modelo (``traffic.scenarios``) no se listan: la corrida usa un escenario
    de la tabla del proyecto, y citar el del catálogo diría que el usuario no lo definió (JAJ-152). En su
    lugar va ``scenario_source``, que dice de dónde sale la tasa de esta corrida."""
    a = model.get("assumptions") or {}
    groups = a.get("by_source") or []
    kept = [g for g in groups if not str(g.get("example_path", "")).startswith("traffic.scenarios.")]
    total = a.get("total", 0) - sum(g.get("count", 0) for g in groups if g not in kept)
    if scenario_source:
        kept = [{"source": scenario_source, "count": 1, "needs_review": False, "example_path": "scenario"}, *kept]
    return {"total": total, "by_source": kept[:TOP_ASSUMPTIONS]}


def _in_sentence(node: str) -> tuple[str, bool]:
    """'la API', 'la base de datos', 'la cola emails'…, y si es femenino."""
    if node.startswith("queue:"):
        return f"la cola {node.split(':', 1)[1]}", True
    return _IN_SENTENCE.get(node, (f"el componente {node}", False))


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


def _state_sentence(nodes: list[str], singular: tuple[str, str], plural: tuple[str, str]) -> str:
    """'La API está sobrecargada.', 'La API y la base de datos tienen holgura para este tráfico.'"""
    named = [_in_sentence(n) for n in nodes]
    feminine = all(f for _, f in named)
    verb, word = singular if len(named) == 1 else plural
    word = word.format(a="a" if feminine else "o")
    text = f"{_join([n for n, _ in named])} {verb}{word}."
    return text[0].upper() + text[1:]


def _throughput(res: dict[str, Any], sc: dict[str, Any]) -> str:
    """'atiende 26,2 req/s' o, si atiende menos que la tasa del escenario, 'atiende en promedio 21,9 req/s (el
    escenario llega a 26,2 req/s)' (JAJ-164). Sin la aclaración, una corrida sin errores parecía perder
    requests; la diferencia sale de la forma del tráfico (subida y bajada) o, si el sistema no alcanza, de
    las requests que quedaron en fila, que explica la frase de saturación."""
    thr, rps = res["throughput_rps"], sc["rps"]
    if rps and thr < rps * 0.95:
        return f"atiende en promedio {es.num(thr)} req/s (el escenario llega a {es.num(rps)} req/s)"
    return f"atiende {es.num(thr)} req/s"


def _conclusion(r: dict[str, Any]) -> str:
    """La conclusión del reporte, armada con una plantilla y con los números en formato es-CL (JAJ-164).

    Ejemplo: 'En cyberday, v3 atiende en promedio 21,9 req/s (el escenario llega a 26,2 req/s), con p95 de
    15 ms y sin errores. El recurso más ocupado es CPU de la API (40 %). La API tiene holgura para este
    tráfico. Cuesta US$68,91/mes sin contar la base de datos, que no tiene precio.'"""
    res, sc = r["results"], r["scenario"]
    p95 = res["latency"]["p95_ms"]
    saturated = bool(res["saturation"] and res["saturation"].get("saturated"))
    if saturated:  # la tasa de error no cuenta las que siguen en fila (JAJ-89): no decir "sin errores"
        errors = f"{es.pct(res['error_rate'])} de errores entre las que terminaron"
    else:
        errors = "sin errores" if res["error_rate"] == 0 else f"{es.pct(res['error_rate'])} de errores"
    head = f"En {sc['label']}, v{r['version']['number']} {_throughput(res, sc)}"
    parts = [head + (f", con p95 de {es.num(p95, 0)} ms y {errors}." if p95 is not None else f", {errors}.")]
    b = r["bottleneck"]
    if b.get("resource"):
        parts.append(
            f"El recurso más ocupado es {b['label']} ({es.pct(b['utilization'], 0)})"
            + (f", sobre todo por {b['line']}" if b.get("line") else "")
            + "."
        )
    if saturated:  # el mensaje ya parte con "El sistema no alcanza a atender este tráfico: …"
        parts.append(res["saturation"]["message"])
    over = [c["id"] for c in r["components"] if c["status"] == "overloaded"]
    idle = [c["id"] for c in r["components"] if c["status"] == "idle"]
    if over:
        parts.append(_state_sentence(over, ("está sobrecargad", "{a}"), ("están sobrecargad", "{a}s")))
    if idle:
        parts.append(
            _state_sentence(idle, ("tiene holgura", " para este tráfico"), ("tienen holgura", " para este tráfico"))
        )
    margins = [c["headroom_x"] for c in r["components"] if c["headroom_x"]]
    if margins and not over:
        parts.append(f"El primer recurso se saturaría cerca de {es.num(min(margins))}× este tráfico (estimado).")
    total = r["costs"]["total"]
    if total and total.get("value") is not None:
        missing = [_in_sentence(c)[0] for c in r["costs"]["missing"]]
        unpriced = f", que no {'tienen' if len(missing) > 1 else 'tiene'} precio" if missing else ""
        parts.append(
            f"Cuesta {es.usd(total['value'])}/mes"
            + (f" sin contar {' ni '.join(missing)}{unpriced}" if missing else "")
            + "."
        )
    return " ".join(parts)


def build_report(
    *,
    project: dict[str, Any],
    version: dict[str, Any],
    model: dict[str, Any],
    run: Run,
    run_dict: dict[str, Any],
    params: dict[str, Any],
    custom_rps: bool,
    cost: CostEstimate,
    failure: FailureCost | None,
    engine_version: str,
    scenario_source: str | None = None,
) -> dict[str, Any]:
    """El reporte de una corrida. ``run_dict`` es el ``Run`` serializado; ``params``, los ``RunParams``
    resueltos (con las req/s finales). ``scenario_source``: de dónde sale la tasa de la corrida, que va
    primero en los supuestos (``scenario_source`` de ``app/api/routes/reports.py``)."""
    sat = run_dict.get("saturation")
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "kind": "run",
        "id": str(uuid.uuid4()),
        "created_at": _now(),
        "project": project,
        "version": version,
        "scenario": {
            "name": params.get("scenario"),
            "label": f"personalizado ({es.num(run.rps, 2)} req/s)" if custom_rps else params.get("scenario"),
            "custom": custom_rps,
            "rps": round(run.rps, 2),
            "seed": run.seed,
            "duration_s": run.duration_s,
            "arrivals": run.arrivals,
            "traffic_profile": run_dict.get("traffic_profile"),
            # ajustes del escenario de esta corrida (mezcla de endpoints, dependencias lentas, negocio; JAJ-131)
            "adjustments": list(run_dict.get("overrides") or []),
        },
        "engine_version": engine_version,
        "params": params,
        "results": {
            "requests": run.requests,
            "ok": run.ok,
            "errors": run.errors,
            "error_rate": round(run.error_rate, 4),
            "in_flight": run.in_flight,
            "throughput_rps": round(run.throughput_rps, 2),
            "latency": run_dict["latency"],
            "saturation": sat,
            "cache": run_dict.get("cache"),
            "queues": run_dict.get("queues"),
            "provenance": {
                "label": "ESTIMADO",
                "source": f"Motor de eventos discretos, semilla {run.seed}, {run.duration_s:g} s simulados. "
                f"Los tiempos de cada paso salen del modelo, con {model.get('assumptions', {}).get('total', 0)} "
                "números SUPUESTO (ver supuestos)",
            },
        },
        "bottleneck": {
            **run_dict["bottleneck"],
            "label": next((r.label for r in run.resources if r.name == run.bottleneck.resource), None),
        },
        "endpoints": [
            {
                "id": e.id,
                "requests": e.requests,
                "error_rate": round(e.error_rate, 4),
                "p95_ms": e.latency.p95_ms,
            }
            for e in sorted(run.endpoints, key=lambda e: -e.requests)[:TOP_ENDPOINTS]
        ],
        "components": _components(run, cost),
        "thresholds": _THRESHOLDS,
        "costs": {
            "total": cost.total,
            "lines": [
                {"id": line.id, "label": line.label, "node": line.node, "usd_month": line.usd_month}
                for line in cost.lines
            ],
            "missing": cost.missing,
            "unpriced": cost.unpriced,
            "warnings": cost.warnings,
            "region": cost.region,
        },
        "failure_cost": failure.to_dict() if failure is not None and hasattr(failure, "to_dict") else None,
        "assumptions": _assumptions(model, scenario_source),
        "warnings": run.warnings,
    }
    report["conclusion"] = _conclusion(report)
    return report


def _side(r: dict[str, Any]) -> dict[str, Any]:
    res = r["results"]
    return {
        "report_id": r["id"],
        "created_at": r["created_at"],
        "version": r["version"]["number"],
        "scenario": r["scenario"],
        "p95_ms": res["latency"]["p95_ms"],
        "p99_ms": res["latency"]["p99_ms"],
        "error_rate": res["error_rate"],
        "throughput_rps": res["throughput_rps"],
        "unanswered": (res.get("saturation") or {}).get("unanswered", 0),
        "usd_month": r["costs"]["total"].get("value") if r["costs"]["total"] else None,
        "bottleneck": r["bottleneck"].get("label"),
        "components": {
            c["id"]: {"label": c["label"], "status": c["status"], "utilization": c["utilization"]}
            for c in r["components"]
        },
    }


def _delta(a: float | None, b: float | None) -> dict[str, Any]:
    if a is None or b is None:
        return {"a": a, "b": b, "diff": None, "pct": None}
    return {"a": a, "b": b, "diff": round(b - a, 4), "pct": round((b - a) / a, 4) if a else None}


def build_comparison(
    a: dict[str, Any], b: dict[str, Any], model_a: dict[str, Any] | None, model_b: dict[str, Any] | None
) -> dict[str, Any]:
    """Compara dos reportes guardados. No simula: usa lo que cada uno ya tiene. ``model_*`` son los modelos de
    sus versiones, para listar qué cambió (``None`` si la versión ya no existe)."""
    sa, sb = _side(a), _side(b)
    same = (
        a["scenario"]["rps"] == b["scenario"]["rps"]
        and a["scenario"]["duration_s"] == b["scenario"]["duration_s"]
        and a["scenario"]["traffic_profile"] == b["scenario"]["traffic_profile"]
        and a["scenario"].get("adjustments") == b["scenario"].get("adjustments")
    )
    warnings = []
    if not same:
        warnings.append(
            "Los escenarios son distintos: la diferencia mezcla el cambio de arquitectura con el cambio de tráfico."
        )
    if a["engine_version"] != b["engine_version"]:
        warnings.append("Los reportes se hicieron con versiones distintas del motor.")
    same_version = a["version"]["number"] == b["version"]["number"]
    changes = (
        model_changes(model_a, model_b) if model_a is not None and model_b is not None and not same_version else []
    )
    components = sorted(set(sa["components"]) | set(sb["components"]))
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "kind": "comparison",
        "id": str(uuid.uuid4()),
        "created_at": _now(),
        "project": a["project"],
        "a": sa,
        "b": sb,
        "same_scenario": same,
        "delta": {
            "p95_ms": _delta(sa["p95_ms"], sb["p95_ms"]),
            "p99_ms": _delta(sa["p99_ms"], sb["p99_ms"]),
            "error_rate": _delta(sa["error_rate"], sb["error_rate"]),
            "throughput_rps": _delta(sa["throughput_rps"], sb["throughput_rps"]),
            "usd_month": _delta(sa["usd_month"], sb["usd_month"]),
            "components": {
                c: {
                    "a": sa["components"].get(c),
                    "b": sb["components"].get(c),
                }
                for c in components
            },
        },
        "changes": [{"path": ch.path, "a": ch.a, "b": ch.b} for ch in changes[:TOP_CHANGES]],
        "changes_total": len(changes),
        "warnings": warnings,
    }
    report["conclusion"] = _comparison_conclusion(report)
    return report


def _comparison_conclusion(r: dict[str, Any]) -> str:
    a, b, d = r["a"], r["b"], r["delta"]
    parts = [
        f"Reporte {a['report_id'][:8]} (v{a['version']}, {a['scenario']['label']}) contra "
        f"{b['report_id'][:8]} (v{b['version']}, {b['scenario']['label']})."
    ]
    if d["p95_ms"]["diff"] is not None:
        parts.append(f"p95: {es.num(d['p95_ms']['a'], 0)} → {es.num(d['p95_ms']['b'], 0)} ms.")
    parts.append(f"Errores: {es.pct(d['error_rate']['a'])} → {es.pct(d['error_rate']['b'])}.")
    if d["usd_month"]["diff"] is not None:
        sign = "+" if d["usd_month"]["diff"] >= 0 else "−"
        parts.append(
            f"Costo: {es.usd(d['usd_month']['a'])} → {es.usd(d['usd_month']['b'])}/mes "
            f"({sign}{es.usd(d['usd_month']['diff'])})."
        )
    if a["bottleneck"] != b["bottleneck"]:
        parts.append(f"El cuello de botella pasa de {a['bottleneck'] or 'ninguno'} a {b['bottleneck'] or 'ninguno'}.")
    if r["changes_total"]:
        parts.append(f"Entre las versiones cambian {r['changes_total']} valores del modelo.")
    parts += r["warnings"]
    return " ".join(parts)
