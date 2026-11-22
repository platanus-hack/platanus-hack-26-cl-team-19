"""Costo mensual de una arquitectura ``branchpoint.model/v1``, por componente (JAJ-72).

Usa las fórmulas del spike de JAJ-11 (``spikes/jaj-11-costos/costs.py``) y sus precios fechados
(``app/costs/prices``), aplicadas a lo que dice el modelo en vez de a un escenario genérico:

| Componente | Fórmula | Cuándo aparece |
| -- | -- | -- |
| API (Fargate ARM) | réplicas × (vCPU × US$/vCPU-h + GB × US$/GB-h) × 730 h | ``deployment.api.provider`` es ``fargate`` |
| DB Supabase | 25 + max(0, compute − 10) + disco y egreso sobre lo incluido | ``deployment.db.provider`` es ``supabase`` |
| DB RDS PostgreSQL | US$/h × 730 + GB × US$/GB-mes de gp3 | ``deployment.db.provider`` es ``rds_postgres`` |
| DB Neon (Launch) | CU × 730 × US$/CU-h + disco + egreso sobre 500 GB | ``deployment.db.provider`` es ``neon`` |
| API en Fly o Render | réplicas × US$/mes del plan | ``deployment.api.provider`` es ``fly`` o ``render`` |
| Frontend | precio fijo del plan (Vercel, CloudFront) | hay ``deployment.frontend`` |
| Balanceador (ALB) | (US$/h + LCU × US$/LCU-h) × 730 | la API está en Fargate |
| Transferencia de la API | GB de respuestas sobre los 100 GB gratis, por tramos | hay tráfico mensual en el modelo |
| Caché (Valkey serverless) | GB × US$/GB-h × 730 + operaciones × US$/ECPU | algún endpoint tiene un paso de caché |

Cada línea trae su costo con procedencia (``label``, ``source``, ``date``), la fórmula y los
números que usó. La etiqueta es la más débil entre el precio (``ESTIMADO``: archivo oficial o
página del proveedor) y los datos del modelo (por ejemplo, los usuarios mensuales, que suelen
ser ``SUPUESTO``).

Lo que no tiene precio queda en ``unpriced``, con el motivo: por ejemplo, los workers de una cola,
porque el modelo no dice su tamaño. El frontend solo aparece si el modelo dice dónde se sirve (JAJ-143).

Si la API o la DB corren en local (US$0) o en un proveedor sin precios, quedan en ``missing`` con un
aviso, el primero de ``warnings`` (JAJ-88): el total no las incluye, así que no cambia con sus
réplicas ni su plan, y una comparación que dé "= Igual" no es un resultado.

Diferencia con el spike: ``por_tramos`` de ``costs.py`` cobra la transferencia desde el primer GB.
AWS regala los primeros 100 GB del mes (*"first 10 TB / month data transfer out beyond the global
free tier"*), así que aquí el primer tramo pagado empieza después de esos 100 GB.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from app.catalog import load_catalog
from app.costs.prices import aws_price, aws_tiers, manual_block
from app.models.architecture import value

COST_SCHEMA = "branchpoint.cost/v1"
HOURS_MONTH = 730  # AWS factura por hora; 730 h es el promedio de un mes (JAJ-11)
DEFAULT_REGION = "us-east-1"

LABELS = ("OBSERVADO", "CALIBRADO", "ESTIMADO", "SUPUESTO")
PRICE_LABEL = "ESTIMADO"  # precio de lista leído de una fuente oficial; el real puede tener descuentos

# Supuestos del spike de JAJ-11 (``Supuestos`` en costs.py). Todos SUPUESTO: los debe poner la empresa.
KB_PER_API_REQUEST = 50.0  # tamaño medio de una respuesta de la API
MB_DB_PER_USER = 1.0  # datos en la DB por usuario
MB_DB_EGRESS_PER_USER = 4.0  # egreso de Supabase por usuario al mes
RDS_MIN_STORAGE_GB = 20.0  # disco mínimo de RDS
ALB_NEW_CONNECTION_SHARE = 0.10  # fracción de requests que abren una conexión nueva
CACHE_BASE_GB = 1.0  # tamaño base de la caché, más 1 KB por usuario
SPIKE_SOURCE = "Supuesto del modelo de costos de Branchpoint"


def _num(v: float, unit: str, label: str, source: str, d: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"value": v, "unit": unit, "label": label, "source": source, "date": d or date.today().isoformat(), **extra}


def _weakest(*labels: str | None) -> str:
    return max((lab for lab in labels if lab in LABELS), key=LABELS.index, default=PRICE_LABEL)


def _label(x: Any) -> str | None:
    return x.get("label") if isinstance(x, dict) else None


@dataclass
class CostLine:
    id: str  # api, db, alb, transfer, cache
    label: str  # nombre para mostrar
    node: str | None  # nodo del grafo (POST /graph) al que corresponde, si hay uno
    usd_month: dict[str, Any]  # costo con procedencia
    formula: str
    inputs: dict[str, Any] = field(default_factory=dict)  # los números que usó la fórmula


@dataclass
class CostEstimate:
    model: str
    region: str
    total: dict[str, Any]  # US$/mes, con la etiqueta más débil de las líneas
    lines: list[CostLine]
    unpriced: list[str]  # componentes sin precio, con el motivo
    warnings: list[str]
    schema: str = COST_SCHEMA
    # JAJ-88: la API o la DB sin precio real (en local, que cuesta US$0, o un proveedor sin precios).
    # El total no las incluye, así que no cambia con sus réplicas ni con su plan: "= Igual" no es un resultado.
    missing: list[str] = field(default_factory=list)  # "api", "db"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _traffic(raw: dict[str, Any]) -> tuple[float | None, float | None, str | None]:
    """Usuarios mensuales y requests a la API al mes, y la etiqueta más débil de esos datos."""
    t = raw.get("traffic", {})
    mau, profile = t.get("mau"), t.get("profile")
    if not isinstance(mau, dict) or not isinstance(profile, dict):
        return None, None, None
    sessions, per_session = value(profile.get("sessions_per_month")), value(profile.get("requests_per_session"))
    if not sessions or not per_session or not value(mau):
        return value(mau), None, _label(mau)
    return value(mau), value(mau) * sessions * per_session, _weakest(_label(mau), _label(profile))


def _cache_ops_per_request(raw: dict[str, Any]) -> float:
    """Operaciones de caché por request, promediando endpoints por su peso: GET, y SET si falla."""
    total_weight = sum(value(e.get("weight"), 0.0) or 0.0 for e in raw["endpoints"]) or 1.0
    ops = 0.0
    for e in raw["endpoints"]:
        w = (value(e.get("weight"), 0.0) or 0.0) / total_weight
        for s in e.get("steps", []):
            if s.get("resource") != "cache":
                continue
            repeat = value(s.get("repeat"), 1) or 1
            miss = 1 - (value(s.get("hit_ratio"), 0.0) or 0.0) if "on_miss" in s else 0.0
            ops += w * repeat * (1 + miss)
    return ops


def _api_line(raw: dict[str, Any], region: str) -> CostLine | str:
    api = raw["deployment"]["api"]
    provider = api.get("provider", "local")
    if provider == "local":
        return CostLine(
            "api", "API (local)", "api", _num(0.0, "US$/mes", "OBSERVADO", "Corre en local: sin costo"), "0"
        )
    if provider in PLAN_PRICED_API:
        return _api_plan_line(api, provider)
    if provider != "fargate":
        return f"API en '{provider}': sin precios en el catálogo."
    vcpu_p, gb_p = (
        aws_price(region, "fargate_linux_arm", "vcpu_hour"),
        aws_price(region, "fargate_linux_arm", "gb_hour"),
    )
    replicas, vcpu = value(api["replicas"], 1), value(api["vcpu"], 1)
    mem = value(api.get("memory_gb"), 2)
    usd = replicas * (vcpu * vcpu_p.usd + mem * gb_p.usd) * HOURS_MONTH
    label = _weakest(PRICE_LABEL, _label(api.get("replicas")), _label(api.get("vcpu")), _label(api.get("memory_gb")))
    return CostLine(
        "api",
        "API (Fargate ARM)",
        "api",
        _num(round(usd, 2), "US$/mes", label, f"{vcpu_p.source}; {gb_p.source}", vcpu_p.date, derived=True),
        f"réplicas × (vCPU × US$/vCPU-h + GB × US$/GB-h) × {HOURS_MONTH} h",
        {"replicas": replicas, "vcpu": vcpu, "memory_gb": mem, "usd_vcpu_hour": vcpu_p.usd, "usd_gb_hour": gb_p.usd},
    )


def _db_line(raw: dict[str, Any], region: str, mau: float | None, mau_label: str | None) -> CostLine | str:
    db = raw["deployment"]["db"]
    provider, plan = db.get("provider", "local"), db.get("plan")
    if provider == "local":
        return CostLine("db", "DB (local)", "db", _num(0.0, "US$/mes", "OBSERVADO", "Corre en local: sin costo"), "0")
    gb_db = (mau or 0) * MB_DB_PER_USER / 1024
    if provider == "supabase":
        sb = manual_block("supabase")
        if plan not in sb["compute_month"]:
            return f"DB Supabase '{plan}': el plan no está en el catálogo de precios."
        compute = sb["compute_month"][plan]["usd"]
        base = sb["plans_month"]["pro"] + max(0, compute - sb["compute_credit_month"])
        disk = max(0.0, gb_db - sb["included"]["disk_gb"]) * sb["overage"]["disk_gb_month"]
        gb_egress = (mau or 0) * MB_DB_EGRESS_PER_USER / 1024
        egress = max(0.0, gb_egress - sb["included"]["egress_gb"]) * sb["overage"]["egress_gb"]
        label = _weakest(sb["provenance"], mau_label if mau else None)
        return CostLine(
            "db",
            f"DB (Supabase Pro, compute {plan})",
            "db",
            _num(
                round(base + disk + egress, 2),
                "US$/mes",
                label,
                f"{sb['source']}, leído el {sb['read_on']}. Disco y egreso: {MB_DB_PER_USER:g} MB y "
                f"{MB_DB_EGRESS_PER_USER:g} MB por usuario ({SPIKE_SOURCE})",
                sb["read_on"],
                derived=True,
            ),
            "25 + max(0, compute − 10) + max(0, GB_db − 8) × 0,125 + max(0, GB_egreso − 250) × 0,09",
            {"compute_usd": compute, "gb_db": round(gb_db, 2), "gb_egress": round(gb_egress, 2), "mau": mau},
        )
    if provider == "rds_postgres":
        try:
            hour = aws_price(region, "rds_postgres", "single_az_per_hour", plan)
        except KeyError:
            return f"DB RDS '{plan}': el plan no está en el catálogo de precios de AWS."
        gp3 = aws_price(region, "rds_postgres", "gp3_gb_month")
        gb = max(RDS_MIN_STORAGE_GB, gb_db)
        usd = hour.usd * HOURS_MONTH + gb * gp3.usd
        return CostLine(
            "db",
            f"DB (RDS PostgreSQL {plan}, Single-AZ)",
            "db",
            _num(
                round(usd, 2),
                "US$/mes",
                _weakest(PRICE_LABEL, mau_label if gb_db > RDS_MIN_STORAGE_GB else None),
                f"{hour.source}; {gp3.source}. Disco: max({RDS_MIN_STORAGE_GB:g} GB, {MB_DB_PER_USER:g} MB por usuario) "
                f"({SPIKE_SOURCE})",
                hour.date,
                derived=True,
            ),
            f"US$/h × {HOURS_MONTH} h + GB × US$/GB-mes (gp3)",
            {"usd_hour": hour.usd, "storage_gb": round(gb, 2), "usd_gb_month": gp3.usd},
        )
    if provider == "neon":
        return _neon_line(plan, gb_db, mau, mau_label)
    return f"DB en '{provider}': todavía sin precios en el catálogo."


def _neon_line(plan: str | None, gb_db: float, mau: float | None, mau_label: str | None) -> CostLine | str:
    """Neon (JAJ-143), con la fórmula de ``neon_mes`` del spike de JAJ-11 pero con el tamaño del plan:
    CU × horas × US$/CU-hora (sin escalar a cero, el peor caso) + disco + egreso sobre lo incluido."""
    nn = manual_block("neon")
    sizes = load_catalog()["db_plans"]["neon"]
    if plan not in sizes:
        return f"DB Neon '{plan}': el tamaño no está en el catálogo."
    cu = sizes[plan]["cu"]
    gb_egress = (mau or 0) * MB_DB_EGRESS_PER_USER / 1024
    compute = cu * HOURS_MONTH * nn["cu_hour"]["launch"]
    storage = gb_db * nn["storage_gb_month"]
    egress = max(0.0, gb_egress - nn["egress_included_gb"]) * nn["egress_gb"]
    return CostLine(
        "db",
        f"DB (Neon Launch, {plan})",
        "db",
        _num(
            round(compute + storage + egress, 2),
            "US$/mes",
            _weakest(nn["provenance"], mau_label if mau else None),
            f"{nn['source']}, leído el {nn['read_on']}. Disco y egreso: {MB_DB_PER_USER:g} MB y "
            f"{MB_DB_EGRESS_PER_USER:g} MB por usuario ({SPIKE_SOURCE})",
            nn["read_on"],
            derived=True,
        ),
        f"CU × {HOURS_MONTH} h × US$/CU-h + GB_db × US$/GB-mes + max(0, GB_egreso − 500) × US$/GB",
        {"cu": cu, "gb_db": round(gb_db, 2), "gb_egress": round(gb_egress, 2), "mau": mau},
    )


def _alb_line(region: str, requests_month: float, traffic_label: str | None) -> CostLine:
    hour, lcu_p = aws_price(region, "alb", "hour"), aws_price(region, "alb", "lcu_hour")
    gb_api = requests_month * KB_PER_API_REQUEST / 1024**2
    rps_avg = requests_month / (30 * 86_400)
    # LCU: la dimensión más alta entre conexiones nuevas (25/s por LCU) y bytes (1 GB/h por LCU)
    lcu = max(rps_avg * ALB_NEW_CONNECTION_SHARE / 25, gb_api / HOURS_MONTH)
    usd = (hour.usd + lcu * lcu_p.usd) * HOURS_MONTH
    return CostLine(
        "alb",
        "Balanceador (ALB)",
        "api",
        _num(
            round(usd, 2),
            "US$/mes",
            _weakest(PRICE_LABEL, traffic_label, "SUPUESTO"),
            f"{hour.source}; {lcu_p.source}. Se asume un ALB delante de la API en Fargate, con "
            f"{ALB_NEW_CONNECTION_SHARE:.0%} de conexiones nuevas ({SPIKE_SOURCE})",
            hour.date,
            derived=True,
        ),
        f"(US$/h + LCU × US$/LCU-h) × {HOURS_MONTH} h; LCU = max(req/s × 10 % / 25, GB/h)",
        {"lcu": round(lcu, 4), "requests_month": round(requests_month)},
    )


def _transfer_line(region: str, requests_month: float, traffic_label: str | None) -> CostLine:
    tiers, url, published = aws_tiers(region, "data_transfer_out_internet")
    gb = requests_month * KB_PER_API_REQUEST / 1024**2
    free = sum(t["to_gb"] - t["from_gb"] for t in tiers if t["usd_per_gb"] == 0 and t["to_gb"] is not None)
    billable = max(0.0, gb - free)
    usd = 0.0
    for t in (t for t in tiers if t["usd_per_gb"] > 0):
        top = float("inf") if t["to_gb"] is None else t["to_gb"]
        usd += max(0.0, min(billable, top) - t["from_gb"]) * t["usd_per_gb"]
    return CostLine(
        "transfer",
        "Transferencia de la API a internet",
        "api",
        _num(
            round(usd, 2),
            "US$/mes",
            _weakest(PRICE_LABEL, traffic_label, "SUPUESTO"),
            f"AWS Data Transfer ({url}). {KB_PER_API_REQUEST:g} KB por respuesta ({SPIKE_SOURCE})",
            published,
            derived=True,
        ),
        f"max(0, GB − {free:g} GB gratis) por tramos de US$/GB",
        {"gb_month": round(gb, 1), "free_gb": free, "requests_month": round(requests_month)},
    )


def _cache_line(
    raw: dict[str, Any], region: str, mau: float, requests_month: float, traffic_label: str | None
) -> CostLine:
    gb_p, ecpu_p = (
        aws_price(region, "elasticache_valkey", "serverless_gb_hour"),
        aws_price(region, "elasticache_valkey", "serverless_ecpu"),
    )
    gb = CACHE_BASE_GB + mau / 1024**2  # 1 GB base + 1 KB por usuario (JAJ-11)
    ops = requests_month * _cache_ops_per_request(raw)
    usd = gb * gb_p.usd * HOURS_MONTH + ops * ecpu_p.usd
    return CostLine(
        "cache",
        "Caché (ElastiCache Valkey serverless)",
        "cache",
        _num(
            round(usd, 2),
            "US$/mes",
            _weakest(PRICE_LABEL, traffic_label, "SUPUESTO"),
            f"{gb_p.source}; {ecpu_p.source}. {CACHE_BASE_GB:g} GB + 1 KB por usuario, 1 ECPU por operación "
            f"de hasta 1 KB ({SPIKE_SOURCE})",
            gb_p.date,
            derived=True,
        ),
        f"GB × US$/GB-h × {HOURS_MONTH} h + operaciones × US$/ECPU",
        {"gb": round(gb, 3), "operations_month": round(ops)},
    )


def _api_plan_line(api: dict[str, Any], provider: str) -> CostLine | str:
    """API en Fly o Render (JAJ-143): se paga un precio fijo por máquina del plan."""
    entry = load_catalog()["app_plans"][provider]
    plan = entry["plans"].get(api.get("plan") or "")
    if plan is None:
        return f"API en {provider}: el plan '{api.get('plan')}' no está en el catálogo."
    replicas = value(api["replicas"], 1)
    usd = replicas * plan["usd_month"]
    return CostLine(
        "api",
        f"API ({provider.capitalize()} {api['plan']})",
        "api",
        _num(
            round(usd, 2), "US$/mes", _weakest(PRICE_LABEL, _label(api.get("replicas"))), entry["_source"], derived=True
        ),
        "réplicas × US$/mes del plan",
        {"replicas": replicas, "plan": api["plan"], "usd_month_plan": plan["usd_month"]},
    )


def _frontend_line(raw: dict[str, Any]) -> CostLine | None:
    """El frontend (JAJ-143), si el modelo dice dónde se sirve. Su costo viene del perfil del plan."""
    front = raw["deployment"].get("frontend")
    if not front:
        return None
    usd = front["usd_month"]
    return CostLine(
        "frontend",
        f"Frontend ({front['provider']} {front['plan']})",
        None,
        {**usd, "derived": True},
        "precio fijo del plan",
        {"plan": front["plan"]},
    )


def estimate_cost(raw: dict[str, Any], region: str = DEFAULT_REGION) -> CostEstimate:
    """Costo mensual del modelo, por componente. ``region``: dónde corre la infraestructura de AWS."""
    mau, requests_month, traffic_label = _traffic(raw)
    lines: list[CostLine] = []
    unpriced: list[str] = []
    warnings: list[str] = []

    api_line, db_line = _api_line(raw, region), _db_line(raw, region, mau, traffic_label)
    for line in (api_line, db_line):
        (lines.append if isinstance(line, CostLine) else unpriced.append)(line)
    # JAJ-88: sin precio real = sin línea (proveedor sin precios) o en local (US$0). Sale de las mismas
    # funciones que calculan el precio, así un proveedor nuevo con precio deja de faltar solo.
    dep = raw["deployment"]
    missing = [
        c
        for c, line in (("api", api_line), ("db", db_line))
        if not isinstance(line, CostLine) or dep[c].get("provider", "local") == "local"
    ]

    on_fargate = raw["deployment"]["api"].get("provider") == "fargate"
    if requests_month:
        if on_fargate:
            lines.append(_alb_line(region, requests_month, traffic_label))
        lines.append(_transfer_line(region, requests_month, traffic_label))
    else:
        unpriced.append("Balanceador y transferencia: el modelo no trae usuarios mensuales ni perfil de uso.")

    # JAJ-140: las réplicas de lectura traen su costo de add_read_replica (catálogo × réplicas)
    replicas = raw["deployment"]["db"].get("read_replicas")
    if replicas and isinstance(replicas.get("usd_month"), dict):
        n = value(replicas.get("count"))
        lines.append(
            CostLine(
                "db_replica",
                f"Réplicas de lectura ({n} × {replicas.get('plan')})",
                "db_replica",
                replicas["usd_month"],
                "costo del plan por réplica × réplicas",
                {"count": n, "plan": replicas.get("plan")},
            )
        )

    has_cache = any(s.get("resource") == "cache" for e in raw["endpoints"] for s in e.get("steps", []))
    if has_cache:
        if requests_month and mau:
            lines.append(_cache_line(raw, region, mau, requests_month, traffic_label))
        else:
            unpriced.append("Caché: sin usuarios mensuales no se puede estimar su tamaño ni sus operaciones.")

    if (front := _frontend_line(raw)) is not None:
        lines.append(front)
    for name in raw["deployment"].get("queues", {}):
        unpriced.append(f"Workers de la cola '{name}': el modelo no dice en qué máquina corren.")

    if missing:
        warnings.insert(0, _missing_warning(raw, missing))  # primero: cambia cómo leer el total
    if raw["deployment"]["db"].get("pooler"):
        warnings.append("El pooler de la DB (Supavisor o PgBouncer) viene incluido en el plan: no suma costo.")
    if not raw["deployment"].get("frontend"):
        warnings.append("No incluye el frontend: el modelo no dice dónde se sirve (Vercel, CloudFront...).")

    total = sum(value(line.usd_month) for line in lines)
    total_num = _num(
        round(total, 2),
        "US$/mes",
        _weakest(*(_label(line.usd_month) for line in lines)),
        "Suma de los componentes con precio" + (f"; sin precio: {len(unpriced)}" if unpriced else ""),
        derived=True,
    )
    return CostEstimate(
        model=raw.get("repo", {}).get("path", "modelo"),
        region=region,
        total=total_num,
        lines=lines,
        unpriced=unpriced,
        warnings=warnings,
        missing=missing,
    )


# Proveedores con precio, para decirle al usuario qué elegir. Lo que falta se detecta de las líneas;
# tests/costs/test_missing.py comprueba que estos conjuntos coinciden con _api_line y _db_line.
PLAN_PRICED_API = {"fly", "render"}
PRICED_API = {"fargate"} | PLAN_PRICED_API
PRICED_DB = {"supabase", "rds_postgres", "neon"}
COMPONENT_NAMES = {"api": "la API", "db": "la DB"}
# líneas de costo que dependen de cada componente: el ALB solo existe con la API en Fargate
COMPONENT_LINES = {"api": {"api", "alb"}, "db": {"db"}}


def describe_missing(missing: list[str]) -> str:
    """'la API, que no tiene precio' o 'la API ni la DB, que no tienen precio' (JAJ-88)."""
    names = " ni ".join(COMPONENT_NAMES[c] for c in missing)
    return f"{names}, que no {'tienen' if len(missing) > 1 else 'tiene'} precio"


def _or_list(items: set[str]) -> str:
    ordered = sorted(items)
    return ordered[0] if len(ordered) == 1 else ", ".join(ordered[:-1]) + f" o {ordered[-1]}"


def _missing_warning(raw: dict[str, Any], missing: list[str]) -> str:
    dep = raw["deployment"]
    parts = [f"{COMPONENT_NAMES[c]} ({dep[c].get('provider', 'local')})" for c in missing]
    them = "las" if len(missing) > 1 else "la"
    where = {"api": f"la API en {_or_list(PRICED_API)}", "db": f"la DB en {_or_list(PRICED_DB)}"}
    return (
        f"Sin precio para {' ni '.join(parts)}: el total no {them} incluye y no cambia con sus réplicas ni con su "
        f"plan. Para comparar costos, indica dónde se desplegaría: {' y '.join(where[c] for c in missing)}."
    )


@dataclass
class CostDelta:
    """Diferencia de costo entre dos versiones.

    JAJ-88: ``a``, ``b``, ``diff``, ``pct`` y ``by_line`` cuentan solo los componentes con precio en
    las dos versiones. Si la API tiene precio solo en v2 (v1 en local), sumarla haría que todo el
    "+US$X" fuera la API de v2, presentado como una diferencia. Los totales completos de cada versión
    siguen en su ``CostEstimate``.
    """

    a: float
    b: float
    diff: float  # b − a
    pct: float | None  # (b − a) / a; None si a es 0
    by_line: dict[str, float]  # diferencia por componente (b − a), con 0 si falta en una
    # componentes sin precio en alguna de las dos versiones, y en cuál
    missing: list[str] = field(default_factory=list)
    missing_a: list[str] = field(default_factory=list)
    missing_b: list[str] = field(default_factory=list)


def cost_delta(a: CostEstimate, b: CostEstimate) -> CostDelta:
    missing = [c for c in ("api", "db") if c in a.missing or c in b.missing]
    skip = set().union(*(COMPONENT_LINES[c] for c in missing))
    la = {line.id: value(line.usd_month) for line in a.lines if line.id not in skip}
    lb = {line.id: value(line.usd_month) for line in b.lines if line.id not in skip}
    va, vb = round(sum(la.values()), 2), round(sum(lb.values()), 2)
    by_line = {k: round(lb.get(k, 0.0) - la.get(k, 0.0), 2) for k in sorted(set(la) | set(lb))}
    return CostDelta(
        va,
        vb,
        round(vb - va, 2),
        round((vb - va) / va, 4) if va else None,
        by_line,
        missing,
        list(a.missing),
        list(b.missing),
    )
