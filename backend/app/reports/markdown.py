"""El reporte en Markdown (JAJ-127): para pegarlo en Slack, GitHub o un documento. Sale de la foto guardada."""

from __future__ import annotations

from typing import Any

_STATUS = {"overloaded": "🔴 Sobrecargado", "idle": "🟡 Holgado", "ok": "🟢 OK"}


def _ms(v: float | None) -> str:
    return "—" if v is None else f"{v:,.0f} ms"


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.1%}"


def _usd(v: float | None) -> str:
    return "—" if v is None else f"US${v:,.2f}"


def _label(n: dict[str, Any] | None) -> str:
    return f" `{n['label']}`" if n and n.get("label") else ""


def _run(r: dict[str, Any]) -> str:
    res, sc, b = r["results"], r["scenario"], r["bottleneck"]
    lat = res["latency"]
    out = [
        f"# Reporte de simulación · {r['project']['name']} v{r['version']['number']}",
        "",
        f"**Escenario:** {sc['label']} · {sc['rps']:g} req/s · {sc['duration_s']:g} s · semilla {sc['seed']}  ",
        f"**Fecha:** {r['created_at']} · **Reporte:** `{r['id'][:8]}` · **Motor:** `{r['engine_version']}`",
        "",
        f"> {r['conclusion']}",
        "",
        "## Resultados",
        "",
        "| Métrica | Valor |",
        "| -- | -- |",
        f"| p50 / p95 / p99 | {_ms(lat['p50_ms'])} / {_ms(lat['p95_ms'])} / {_ms(lat['p99_ms'])} |",
        f"| Throughput | {res['throughput_rps']:g} req/s |",
        f"| Errores | {_pct(res['error_rate'])} ({res['requests'] - res['ok'] - res['in_flight']:,} de {res['requests']:,}) |",
        f"| Sin respuesta al terminar | {res['in_flight']:,} |",
        "",
        f"Procedencia: `{res['provenance']['label']}`. {res['provenance']['source']}.",
        "",
        "## Cuello de botella",
        "",
    ]
    if b.get("resource"):
        out.append(f"**{b.get('label') or b['resource']}** al {b['utilization']:.0%}. {b.get('message') or ''}")
        if b.get("line"):
            out.append(
                f"\nLínea que más lo ocupa: `{b['line']}`"
                + (f" ({b['line_share']:.0%})" if b.get("line_share") else "")
            )
        if b.get("endpoint"):
            out.append(f"\nEndpoint que más lo ocupa: `{b['endpoint']}`")
    else:
        out.append(b.get("message") or "Sin cuello de botella.")
    out += [
        "",
        "## Componentes",
        "",
        "| Componente | Estado | Uso prom. / pico | Costo/mes | Satura cerca de |",
        "| -- | -- | -- | -- | -- |",
    ]
    for c in r["components"]:
        sat = c["saturates_at_rps"]
        margin = (
            f"{sat['value']:,.0f} req/s ({c['headroom_x']:g}×)"
            if sat
            else "ya saturado"
            if c["status"] == "overloaded"
            else "—"
        )
        out.append(
            f"| {c['label']} | {_STATUS[c['status']]} | {_pct(c['utilization'])} / {_pct(c['peak_utilization'])} | "
            f"{_usd(c['usd_month']) if c['priced'] else 'sin precio'} | {margin} |"
        )
    t = r["thresholds"]
    out += [
        "",
        f"Umbrales: sobrecargado ≥ {t['overloaded']['value']:.0%} de uso promedio; holgado < {t['idle']['value']:.0%} "
        f"en el pico (`{t['idle']['label']}`). El margen es una aproximación lineal (`ESTIMADO`).",
        "",
        "## Costos",
        "",
    ]
    costs = r["costs"]
    if costs["lines"]:
        out += ["| Línea | US$/mes | Etiqueta |", "| -- | -- | -- |"]
        out += [
            f"| {line['label']} | {_usd(line['usd_month'].get('value'))} |{_label(line['usd_month'])} |"
            for line in costs["lines"]
        ]
    out.append(
        f"\n**Total:** {_usd((costs['total'] or {}).get('value'))}{_label(costs['total'])} · región {costs['region']}"
    )
    out += [f"- {w}" for w in costs["warnings"]]
    if r.get("failure_cost"):
        out += ["", "## Costo de fallar", "", r["failure_cost"]["message"]]
    a = r["assumptions"]
    out += ["", "## Supuestos", "", f"{a['total']} números del modelo son `SUPUESTO`. Los principales:", ""]
    out += [f"- {s['source']} ({s['count']})" for s in a["by_source"]]
    if r["warnings"]:
        out += ["", "## Avisos del motor", ""] + [f"- {w}" for w in r["warnings"]]
    return "\n".join(out) + "\n"


def _comparison(r: dict[str, Any]) -> str:
    a, b, d = r["a"], r["b"], r["delta"]

    def row(name: str, key: str, fmt) -> str:
        x = d[key]
        return f"| {name} | {fmt(x['a'])} | {fmt(x['b'])} | {fmt(x['diff']) if x['diff'] is not None else '—'} |"

    out = [
        f"# Comparación de reportes · {r['project']['name']}",
        "",
        f"**A:** `{a['report_id'][:8]}` · v{a['version']} · {a['scenario']['label']}  ",
        f"**B:** `{b['report_id'][:8]}` · v{b['version']} · {b['scenario']['label']}",
        "",
        f"> {r['conclusion']}",
        "",
        "| Métrica | A | B | Diferencia |",
        "| -- | -- | -- | -- |",
        row("p95", "p95_ms", _ms),
        row("p99", "p99_ms", _ms),
        row("Errores", "error_rate", _pct),
        row("Throughput (req/s)", "throughput_rps", lambda v: "—" if v is None else f"{v:g}"),
        row("Costo/mes", "usd_month", _usd),
        "",
        "## Componentes",
        "",
        "| Componente | A | B |",
        "| -- | -- | -- |",
    ]
    for sides in d["components"].values():
        cell = lambda s: "—" if not s else f"{_STATUS[s['status']]} ({_pct(s['utilization'])})"  # noqa: E731
        name = (sides["a"] or sides["b"])["label"]
        out.append(f"| {name} | {cell(sides['a'])} | {cell(sides['b'])} |")
    if r["changes"]:
        out += ["", f"## Qué cambió en el modelo ({r['changes_total']})", ""]
        out += [f"- `{c['path']}`: {c['a']} → {c['b']}" for c in r["changes"]]
    if r["warnings"]:
        out += ["", "## Avisos", ""] + [f"- {w}" for w in r["warnings"]]
    return "\n".join(out) + "\n"


def to_markdown(report: dict[str, Any]) -> str:
    return _comparison(report) if report["kind"] == "comparison" else _run(report)
