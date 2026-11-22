"""Operaciones tipadas que cambian la arquitectura de un modelo ``branchpoint.model/v1`` (JAJ-68).

Es el vocabulario con que el agente propone versiones (ADR 0001): el LLM nunca edita el JSON del
modelo, solo pide una lista de operaciones. ``apply_ops`` las valida, las aplica en orden sobre una
copia y verifica que el resultado cargue en el motor.

De dónde sale cada número nuevo:

* **Del catálogo** (planes de DB, precios, tiempos de caché y de encolar): con su etiqueta y fuente.
* **Decisiones de diseño** (réplicas, vCPU, workers de una cola): las puede elegir el agente. Quedan
  ``SUPUESTO`` con la fuente "Propuesta del agente" y ``needs_review``. Si las dijo el usuario, van
  con ``quote`` (su frase) como fuente.
* **Datos del mundo** (la tasa de aciertos de una caché): solo con ``quote``. Sin el dato del
  usuario la caché se simula con 0 % de aciertos, el peor caso, y la operación lo advierte.

Todo error es un ``OpError`` con un mensaje pensado para que el LLM lo lea y corrija.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.catalog import load_catalog
from app.models.architecture import RESOURCE_API_CPU, RESOURCE_DB_CONNECTION, load_model, value

HOURS_MONTH = 730
RANK = {"OBSERVADO": 0, "CALIBRADO": 1, "ESTIMADO": 2, "SUPUESTO": 3}
NOT_CACHEABLE_SHAPES = {"commit", "stage"}  # escrituras: no se cachean


class OpError(ValueError):
    """La operación no se puede aplicar. El mensaje explica por qué y qué valores sí existen."""


# ---------- operaciones ----------
class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScaleApi(_Op):
    """Cambia las réplicas de la API y, si se da, los vCPU por réplica. Recalcula el costo."""

    op: Literal["scale_api"]
    replicas: int = Field(ge=1, le=50, description="Réplicas de la API.")
    vcpu: float | None = Field(None, gt=0, le=16, description="vCPU por réplica. Sin valor, se mantiene.")
    quote: str | None = Field(None, max_length=500, description="La frase del usuario, si él pidió estos números.")


class ChangeDbPlan(_Op):
    """Cambia el plan de la DB por uno del catálogo: vCPU, conexiones, procesador y costo."""

    op: Literal["change_db_plan"]
    plan: str = Field(description="Plan del catálogo, por ejemplo 'small' (Supabase) o 'db.m7g.large' (RDS).")
    provider: str | None = Field(None, description="supabase, rds_postgres o local. Sin valor, el actual.")


class AddPooler(_Op):
    """Pone un pooler en modo transacción (Supavisor de Supabase) entre la app y la DB."""

    op: Literal["add_pooler"]


class AddCache(_Op):
    """Pone una caché (Redis) delante de las lecturas de un endpoint GET: si acierta, no consulta la DB."""

    op: Literal["add_cache"]
    endpoint: str = Field(description="Id del endpoint, por ejemplo 'GET /items/'.")
    at: list[str] | None = Field(
        None, description="archivo:línea de las lecturas a cachear. Sin valor, todas las lecturas del endpoint."
    )
    hit_ratio: float | None = Field(
        None, ge=0, le=1, description="Fracción de aciertos. Solo con quote: es un dato del usuario."
    )
    quote: str | None = Field(None, max_length=500, description="La frase del usuario que respalda hit_ratio.")


class MoveToQueue(_Op):
    """Saca un paso de la request y lo pasa a una cola nueva con workers asíncronos (Celery, RQ, arq)."""

    op: Literal["move_to_queue"]
    endpoint: str = Field(description="Id del endpoint, por ejemplo 'POST /password-recovery/{email}'.")
    at: str = Field(description="archivo:línea del paso que se encola.")
    queue: str = Field(pattern=r"^[a-z0-9_-]{1,40}$", description="Nombre de la cola nueva, por ejemplo 'emails'.")
    workers: int = Field(ge=1, le=100, description="Trabajos en paralelo de la cola.")
    quote: str | None = Field(None, max_length=500, description="La frase del usuario, si él pidió los workers.")


class RemoveCache(_Op):
    """Quita la caché de un endpoint: las lecturas que estaban en on_miss vuelven a hacerse siempre."""

    op: Literal["remove_cache"]
    endpoint: str = Field(description="Id del endpoint con caché, por ejemplo 'GET /items/'.")


class RemovePooler(_Op):
    """Quita el pooler: la app vuelve a abrir conexiones directo contra Postgres, con el límite del plan."""

    op: Literal["remove_pooler"]


class MoveToSync(_Op):
    """Inversa de move_to_queue: el trabajo encolado vuelve a hacerse dentro de la request."""

    op: Literal["move_to_sync"]
    endpoint: str = Field(description="Id del endpoint que encola, por ejemplo 'POST /password-recovery/{email}'.")
    step: str = Field(description="archivo:línea del paso que encola (el paso 'background').")


class ScaleWorkers(_Op):
    """Cambia los workers (trabajos en paralelo) de una cola que ya existe."""

    op: Literal["scale_workers"]
    queue: str = Field(description="Nombre de la cola, por ejemplo 'emails'.")
    workers: int = Field(ge=1, le=100, description="Trabajos en paralelo de la cola.")
    quote: str | None = Field(None, max_length=500, description="La frase del usuario, si él pidió los workers.")


class AddReadReplica(_Op):
    """Agrega réplicas de lectura de la DB: las lecturas van a las réplicas y las escrituras a la primaria.

    Supone que la app separa lecturas y escrituras (SUPUESTO). No simula el retraso de replicación.
    """

    op: Literal["add_read_replica"]
    count: int = Field(ge=1, le=5, description="Réplicas de lectura. Si ya hay, se reemplaza el número.")
    plan: str | None = Field(None, description="Plan de cada réplica, del catálogo. Sin valor, el de la primaria.")
    quote: str | None = Field(None, max_length=500, description="La frase del usuario, si él pidió estos números.")


class RemoveReadReplica(_Op):
    """Quita las réplicas de lectura: todas las consultas vuelven a la primaria."""

    op: Literal["remove_read_replica"]


Op = Annotated[
    ScaleApi
    | ChangeDbPlan
    | AddPooler
    | AddCache
    | MoveToQueue
    | RemoveCache
    | RemovePooler
    | MoveToSync
    | ScaleWorkers
    | AddReadReplica
    | RemoveReadReplica,
    Field(discriminator="op"),
]
_OPS = TypeAdapter(list[Op])


@dataclass(frozen=True)
class OpsResult:
    model: dict[str, Any]
    changes: list[str]  # una línea por operación, para la nota de la versión y para el agente
    warnings: list[str]  # lo que el agente debería decirle al usuario o preguntarle


def ops_json_schema() -> dict[str, Any]:
    """JSON Schema de la lista de operaciones, para la definición de la tool del agente (JAJ-67)."""
    return _OPS.json_schema()


def parse_ops(raw: list[Any]) -> list[Op]:
    try:
        return _OPS.validate_python(raw)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
        raise OpError(f"Operaciones inválidas: {problems}") from None


def apply_ops(model: dict[str, Any], ops: list[Any]) -> OpsResult:
    """Aplica las operaciones en orden sobre una copia del modelo. No modifica ``model``."""
    parsed = parse_ops(list(ops))
    if not parsed:
        raise OpError("No hay operaciones que aplicar.")
    m = copy.deepcopy(model)
    # ``steps`` es opcional en el modelo (un endpoint sin pasos no consulta nada); las operaciones lo
    # recorren, así que se completa con [] en la copia (antes, add_cache respondía 500, JAJ-101)
    for e in m.get("endpoints", []):
        e.setdefault("steps", [])
    catalog = load_catalog()
    changes: list[str] = []
    warnings: list[str] = []
    for i, op in enumerate(parsed, 1):
        try:
            changes.append(_APPLY[type(op)](m, op, catalog, warnings))
        except OpError as e:
            raise OpError(f"Operación {i} ({op.op}): {e}") from None
    # Las cotas analíticas de build_model.py son de la versión original: ya no corresponden.
    m.pop("checks", None)
    m["assumptions"] = collect_assumptions(m)
    try:
        load_model(m)
    except (ValueError, KeyError, TypeError) as e:
        raise OpError(f"El modelo resultante no carga en el motor: {e}") from None
    return OpsResult(m, changes, warnings)


# ---------- números con procedencia ----------
def _num(v: Any, unit: str, label: str, source: str, **extra: Any) -> dict[str, Any]:
    return {"value": v, "unit": unit, "label": label, "source": source, "date": date.today().isoformat(), **extra}


def _design(v: Any, unit: str, what: str, quote: str | None) -> dict[str, Any]:
    """Decisión de diseño: la pudo pedir el usuario (quote) o proponer el agente."""
    if quote:
        return _num(v, unit, "SUPUESTO", f"Declarado por el usuario: «{quote}»")
    return _num(v, unit, "SUPUESTO", f"Propuesta del agente: {what}", needs_review=True)


def _weakest(*labels: str) -> str:
    return max(labels, key=lambda lab: RANK[lab])


def _core_factor(catalog: dict[str, Any], plan: dict[str, Any], where: str) -> dict[str, Any]:
    """Igual que ``core_factor`` de build_model.py: cuánto más lento es 1 vCPU del plan."""
    proc = plan.get("processor", "local")
    f = catalog["cpu_core_factor"][proc]
    label = _weakest(f["label"], plan.get("processor_label", f["label"]))
    out = _num(
        f["value"],
        "×",
        label,
        f"{where}: procesador {proc}. {f['source']}. {catalog['cpu_core_factor']['_doc']}",
        processor=proc,
    )
    if label == "SUPUESTO":
        out["needs_review"] = True
    return out


# ---------- scale_api ----------
def _scale_api(m: dict[str, Any], op: ScaleApi, catalog: dict[str, Any], warnings: list[str]) -> str:
    api = m["deployment"]["api"]
    provider = api.get("provider", "local")
    price = catalog["app_plans"].get(provider)
    if price is None or provider.startswith("_"):
        known = ", ".join(k for k in catalog["app_plans"] if not k.startswith("_"))
        raise OpError(f"La API está en '{provider}', que no está en el catálogo de precios. Hay: {known}.")
    before = f"{value(api['replicas'])} × {value(api['vcpu'])} vCPU"
    api["replicas"] = _design(op.replicas, "réplicas", f"{op.replicas} réplicas de la API", op.quote)
    if op.vcpu is not None:
        api["vcpu"] = _design(op.vcpu, "vCPU", f"{op.vcpu:g} vCPU por réplica", op.quote)
    vcpu, mem = float(value(api["vcpu"])), float(value(api.get("memory_gb"), 2))
    usd = op.replicas * (vcpu * price["usd_vcpu_hour"] + mem * price["usd_gb_hour"]) * HOURS_MONTH
    api["usd_month"] = _num(
        round(usd, 2),
        "US$/mes",
        "ESTIMADO",
        f"{catalog['app_plans']['_source']}. réplicas × (vCPU × US$/vCPU-h + GB × US$/GB-h) × {HOURS_MONTH} h",
    )
    return f"API: {before} → {op.replicas} × {vcpu:g} vCPU (US${usd:,.2f}/mes)"


# ---------- change_db_plan ----------
def _change_db_plan(m: dict[str, Any], op: ChangeDbPlan, catalog: dict[str, Any], warnings: list[str]) -> str:
    db = m["deployment"]["db"]
    plans = catalog["db_plans"]
    providers = [k for k, v in plans.items() if isinstance(v, dict) and not k.startswith("_")]
    provider = op.provider or db.get("provider", "local")
    if provider not in providers:
        raise OpError(f"El proveedor '{provider}' no está en el catálogo. Hay: {', '.join(providers)}.")
    plan = plans[provider].get(op.plan)
    if plan is None:
        raise OpError(f"{provider} no tiene el plan '{op.plan}' en el catálogo. Hay: {', '.join(plans[provider])}.")
    before = f"{db.get('provider')} {db.get('plan')}"
    src = f"{plans['_sources'][provider]}. Plan {provider} {op.plan} propuesto por el agente"
    if provider == "supabase":
        usd = plans["supabase_base_usd_month"] + max(
            0, plan["compute_usd_month"] - plans["supabase_compute_credit_usd_month"]
        )
        formula = "Supabase: 25 + max(0, compute − 10)"
    else:
        usd = plan["usd_hour"] * HOURS_MONTH
        formula = f"US$/hora × {HOURS_MONTH}"
    db.update(
        provider=provider,
        plan=op.plan,
        vcpu=_num(plan["vcpu"], "vCPU", plan["vcpu_label"], src),
        max_connections=_num(plan["max_connections"], "conexiones", "ESTIMADO", src),
        usd_month=_num(round(usd, 2), "US$/mes", "ESTIMADO", f"{src}. {formula} (JAJ-11)"),
        cpu_core_factor=_core_factor(catalog, plan, f"Plan {provider} {op.plan}"),
    )
    base = catalog["burstable_baseline_per_vcpu"].get(op.plan)
    if base is not None:
        per_vcpu = {**base}
        sustained = round(plan["vcpu"] * base["value"], 3)
        db["cpu_credits"] = {
            "baseline_per_vcpu": per_vcpu,
            "sustained_vcpu": _num(
                sustained,
                "vCPU",
                _weakest(plan["vcpu_label"], base["label"]),
                f"vCPU × base por vCPU: lo que rinde {op.plan} con carga sostenida",
                derived=True,
            ),
        }
        warnings.append(
            f"{op.plan} tiene créditos de CPU: con carga sostenida rinde {sustained:g} vCPU, no {plan['vcpu']}."
        )
    else:
        db.pop("cpu_credits", None)
    if "pooler_connections" in plan:
        db["pooler_connections"] = _num(plan["pooler_connections"], "conexiones", "ESTIMADO", src)
        if "pooler" in db:
            db["pooler"]["client_connections"] = copy.deepcopy(db["pooler_connections"])
    else:
        db.pop("pooler_connections", None)
        if db.pop("pooler", None) is not None:
            warnings.append(f"{provider} {op.plan} no tiene pooler en el catálogo: la versión queda sin pooler.")
    return f"DB: {before} → {provider} {op.plan} ({plan['vcpu']} vCPU, {plan['max_connections']} conexiones)"


# ---------- add_pooler ----------
def _add_pooler(m: dict[str, Any], op: AddPooler, catalog: dict[str, Any], warnings: list[str]) -> str:
    db = m["deployment"]["db"]
    if "pooler" in db:
        raise OpError("La DB ya tiene pooler.")
    clients = db.get("pooler_connections")
    if clients is None:
        raise OpError(
            f"El plan {db.get('provider')} {db.get('plan')} no tiene pooler en el catálogo. "
            "En el MVP solo Supabase lo trae (Supavisor); para usarlo, cambia el plan con change_db_plan."
        )
    db["pooler"] = {"kind": "supavisor", "mode": "transaction", "client_connections": copy.deepcopy(clients)}
    return (
        f"DB: pooler en modo transacción ({value(clients)} conexiones de clientes sobre "
        f"{value(db['max_connections'])} de Postgres)"
    )


# ---------- add_cache ----------
def _endpoint(m: dict[str, Any], endpoint_id: str) -> dict[str, Any]:
    for e in m["endpoints"]:
        if e["id"] == endpoint_id:
            return e
    raise OpError(f"No existe el endpoint '{endpoint_id}'. Hay: {', '.join(e['id'] for e in m['endpoints'])}.")


def _add_cache(m: dict[str, Any], op: AddCache, catalog: dict[str, Any], warnings: list[str]) -> str:
    ep = _endpoint(m, op.endpoint)
    if ep.get("method", op.endpoint.split(" ", 1)[0]) != "GET":
        raise OpError(f"'{op.endpoint}' no es GET: solo se cachean lecturas.")
    if op.hit_ratio is not None and not op.quote:
        raise OpError(
            "hit_ratio es un dato del usuario: mándalo con quote (su frase). "
            "Si no lo sabe, omite hit_ratio y se simula el peor caso (0 % de aciertos)."
        )
    steps = ep["steps"]
    reads = [
        i
        for i, s in enumerate(steps)
        if s.get("resource") == RESOURCE_DB_CONNECTION and s.get("shape") not in NOT_CACHEABLE_SHAPES
    ]
    if op.at is not None:
        by_at = {steps[i].get("at"): i for i in reversed(reads)}
        missing = [a for a in op.at if a not in by_at]
        if missing:
            found = ", ".join(steps[i].get("at", "?") for i in reads) or "ninguna"
            raise OpError(f"'{op.endpoint}' no tiene lecturas en {', '.join(missing)}. Tiene: {found}.")
        reads = sorted({by_at[a] for a in op.at})
    if not reads:
        raise OpError(f"'{op.endpoint}' no tiene lecturas de la DB que cachear.")
    cache_step: dict[str, Any] = {
        "kind": "cache",
        "resource": "cache",
        "detail": "Redis GET; si falla, consulta la DB y hace SET",
        "at": steps[reads[0]].get("at"),
        "time": copy.deepcopy(catalog["other_steps"]["cache"]),
        "on_miss": [steps[i] for i in reads],
        "proposed": True,
        # dónde estaba cada lectura: remove_cache las devuelve a su lugar exacto
        "restore_positions": list(reads),
    }
    if op.hit_ratio is not None:
        cache_step["hit_ratio"] = _num(op.hit_ratio, "fracción", "SUPUESTO", f"Declarado por el usuario: «{op.quote}»")
        ratio = f"{op.hit_ratio:.0%} de aciertos"
    else:
        ratio = "sin tasa de aciertos"
        warnings.append(
            f"La caché de '{op.endpoint}' no tiene tasa de aciertos: se simula con 0 % (el peor caso). "
            "Pregúntale al usuario qué fracción de estas lecturas se repite."
        )
    cached = set(reads)
    keep = [s for i, s in enumerate(steps) if i not in cached]
    keep.insert(reads[0], cache_step)  # donde estaba la primera lectura: ninguna lectura cacheada va antes
    ep["steps"] = keep
    warnings.append("El costo de Redis no está en el modelo todavía.")
    return f"Caché en {op.endpoint}: {len(reads)} lectura(s) pasan a on_miss ({ratio})"


# ---------- move_to_queue ----------
def _move_to_queue(m: dict[str, Any], op: MoveToQueue, catalog: dict[str, Any], warnings: list[str]) -> str:
    ep = _endpoint(m, op.endpoint)
    steps = ep["steps"]
    idx = next((i for i, s in enumerate(steps) if s.get("at") == op.at), None)
    if idx is None:
        found = ", ".join(s.get("at", "?") for s in steps) or "ninguno"
        raise OpError(f"'{op.endpoint}' no tiene un paso en {op.at}. Tiene: {found}.")
    queues = m["deployment"].setdefault("queues", {})
    if op.queue in queues:
        raise OpError(f"Ya existe la cola '{op.queue}'. Usa otro nombre.")
    moved = steps[idx]
    steps[idx] = {
        "kind": "background",
        "resource": "background",
        "detail": f"encola {moved.get('detail') or moved.get('kind')} en '{op.queue}'",
        "at": moved.get("at"),
        "time": copy.deepcopy(catalog["other_steps"]["background"]),
        "queue": op.queue,
        "proposed": True,
    }
    if isinstance(ep.get("api_cpu_ms"), dict):
        steps[idx]["restore_api_cpu_ms"] = copy.deepcopy(ep["api_cpu_ms"])  # para move_to_sync
    queues[op.queue] = {
        "workers": _design(op.workers, "workers", f"{op.workers} workers para la cola {op.queue}", op.quote),
        "job_steps": [moved],
    }
    # api_cpu_ms incluye los pasos de CPU del endpoint: si el paso movido era CPU, ya no es de la request.
    if moved.get("resource") == RESOURCE_API_CPU and isinstance(ep.get("api_cpu_ms"), dict):
        cpu = float(value(moved.get("time"), 0.0)) * max(1, int(value(moved.get("repeat"), 1)))
        ep["api_cpu_ms"] = {
            **ep["api_cpu_ms"],
            "value": round(max(0.0, float(value(ep["api_cpu_ms"])) - cpu), 3),
            "source": f"{ep['api_cpu_ms']['source']}. Sin el paso de {moved.get('at')}, que pasó a la cola {op.queue}",
        }
    warnings.append(
        f"La cola '{op.queue}' no tiene largo máximo: crece sin límite. El costo de sus workers no está en el modelo."
    )
    return f"Cola '{op.queue}' con {op.workers} workers: {op.endpoint} encola el paso de {op.at}"


# ---------- remove_cache ----------
def _remove_cache(m: dict[str, Any], op: RemoveCache, catalog: dict[str, Any], warnings: list[str]) -> str:
    ep = _endpoint(m, op.endpoint)
    steps = ep["steps"]
    caches = [i for i, s in enumerate(steps) if s.get("resource") == "cache"]
    if not caches:
        with_cache = [e["id"] for e in m["endpoints"] if any(s.get("resource") == "cache" for s in e["steps"])]
        raise OpError(
            f"El endpoint '{op.endpoint}' no tiene caché. Tienen caché: {', '.join(with_cache) or 'ninguno'}."
        )
    blind = [steps[i].get("at", "?") for i in caches if "on_miss" not in steps[i]]
    if blind:
        raise OpError(
            f"La caché de '{op.endpoint}' en {', '.join(blind)} no guarda qué se hace cuando falla (on_miss): "
            "no se puede saber qué lecturas vuelven a la DB. Branchpoint no la quita para no adivinar."
        )
    restored = 0
    for i in reversed(caches):  # de atrás hacia adelante: los índices de las anteriores no cambian
        cache = steps.pop(i)
        on_miss = cache.get("on_miss") or []
        positions = cache.get("restore_positions")
        restored += len(on_miss)
        if positions and len(positions) == len(on_miss):
            for pos, step in sorted(zip(positions, on_miss, strict=True)):  # la caché de add_cache: lugar exacto
                steps.insert(pos, step)
        else:  # la caché venía del repo: sus lecturas quedan donde estaba ella
            steps[i:i] = on_miss
    return f"Sin caché en {op.endpoint}: {restored} lectura(s) vuelven a la DB en cada request"


# ---------- remove_pooler ----------
def _remove_pooler(m: dict[str, Any], op: RemovePooler, catalog: dict[str, Any], warnings: list[str]) -> str:
    db = m["deployment"]["db"]
    if "pooler" not in db:
        raise OpError("El proyecto no tiene pooler.")
    db.pop("pooler")
    conns = db.get("max_connections")
    label = conns.get("label") if isinstance(conns, dict) else "SUPUESTO"
    return (
        f"DB: sin pooler; la app abre conexiones directo contra Postgres (máximo {value(conns)} del plan "
        f"{db.get('provider')} {db.get('plan')}, {label})"
    )


# ---------- move_to_sync ----------
def _queue_of(m: dict[str, Any], step: dict[str, Any]) -> str | None:
    queues = m["deployment"].get("queues") or {}
    name = step.get("queue")
    if name is None and step.get("infer_queue", True) and len(queues) == 1:
        name = next(iter(queues))
    return name if name in queues else None


def _move_to_sync(m: dict[str, Any], op: MoveToSync, catalog: dict[str, Any], warnings: list[str]) -> str:
    ep = _endpoint(m, op.endpoint)
    steps = ep["steps"]
    idx = next((i for i, s in enumerate(steps) if s.get("at") == op.step and s.get("resource") == "background"), None)
    if idx is None:
        found = ", ".join(s.get("at", "?") for s in steps if s.get("resource") == "background") or "ninguno"
        raise OpError(f"'{op.endpoint}' no encola nada en {op.step}. Pasos que encolan: {found}.")
    bg = steps[idx]
    name = _queue_of(m, bg)
    if name is None:
        raise OpError(f"El paso de {op.step} no está en una cola del modelo: no se sabe qué trabajo hace.")
    queue = m["deployment"]["queues"][name]
    job = queue.get("job_steps") or []
    if not job:
        raise OpError(
            f"La cola '{name}' no guarda los pasos de su trabajo (job_steps): no se puede saber qué vuelve a la "
            "request. Branchpoint no lo adivina."
        )
    steps[idx : idx + 1] = copy.deepcopy(job)
    if "restore_api_cpu_ms" in bg:
        ep["api_cpu_ms"] = bg["restore_api_cpu_ms"]
    elif isinstance(ep.get("api_cpu_ms"), dict):  # la cola venía del repo: su CPU vuelve a la request
        cpu = sum(
            float(value(s.get("time"), 0.0)) * max(1, int(value(s.get("repeat"), 1)))
            for s in job
            if s.get("resource") == RESOURCE_API_CPU
        )
        if cpu:
            ep["api_cpu_ms"] = {
                **ep["api_cpu_ms"],
                "value": round(float(value(ep["api_cpu_ms"])) + cpu, 3),
                "source": f"{ep['api_cpu_ms']['source']}. Con el trabajo de la cola {name} de vuelta en la request",
            }
    still_used = any(
        s.get("resource") == "background" and _queue_of(m, s) == name for e in m["endpoints"] for s in e["steps"]
    )
    if still_used:
        return f"{op.endpoint} hace en la request el trabajo de {op.step}; la cola '{name}' sigue para otros endpoints"
    del m["deployment"]["queues"][name]
    if not m["deployment"]["queues"]:
        m["deployment"].pop("queues")
    return f"{op.endpoint} hace en la request el trabajo de {op.step}; la cola '{name}' y sus workers se quitan"


# ---------- scale_workers ----------
def _scale_workers(m: dict[str, Any], op: ScaleWorkers, catalog: dict[str, Any], warnings: list[str]) -> str:
    queues = m["deployment"].get("queues") or {}
    if op.queue not in queues:
        raise OpError(f"No existe la cola '{op.queue}'. Hay: {', '.join(queues) or 'ninguna'}.")
    before = value(queues[op.queue].get("workers"), 1)
    queues[op.queue]["workers"] = _design(
        op.workers, "workers", f"{op.workers} workers para la cola {op.queue}", op.quote
    )
    return f"Cola '{op.queue}': {before} → {op.workers} workers"


# ---------- réplicas de lectura (JAJ-140) ----------
def _add_read_replica(m: dict[str, Any], op: AddReadReplica, catalog: dict[str, Any], warnings: list[str]) -> str:
    db = m["deployment"]["db"]
    plans = catalog["db_plans"]
    provider = db.get("provider", "local")
    if provider not in plans or provider.startswith("_") or not isinstance(plans[provider], dict):
        known = ", ".join(k for k, v in plans.items() if isinstance(v, dict) and not k.startswith("_"))
        raise OpError(f"La DB está en '{provider}', que no está en el catálogo. Hay: {known}.")
    name = op.plan or db.get("plan")
    plan = plans[provider].get(name) if name else None
    if plan is None:
        raise OpError(f"{provider} no tiene el plan '{name}' en el catálogo. Hay: {', '.join(plans[provider])}.")
    src = f"{plans['_sources'][provider]}. Réplica {provider} {name}"
    if provider == "supabase":
        per, formula = plan["compute_usd_month"], "Supabase: compute del plan por réplica"
    else:
        per, formula = plan["usd_hour"] * HOURS_MONTH, f"US$/hora × {HOURS_MONTH} por réplica"
    before = (db.get("read_replicas") or {}).get("count")
    db["read_replicas"] = {
        "count": _design(op.count, "réplicas", f"{op.count} réplica(s) de lectura", op.quote),
        "plan": name,
        "vcpu": _num(plan["vcpu"], "vCPU", plan["vcpu_label"], src),
        "max_connections": _num(plan["max_connections"], "conexiones", "ESTIMADO", src),
        "cpu_core_factor": _core_factor(catalog, plan, f"Réplica {provider} {name}"),
        "usd_month": _num(round(per * op.count, 2), "US$/mes", "ESTIMADO", f"{src}. {formula} × réplicas"),
        "routing": _num(
            "reads_to_replicas",
            "",
            "SUPUESTO",
            "Propuesta del agente: la app envía las lecturas a la réplica y las escrituras a la primaria",
            needs_review=True,
        ),
    }
    base = catalog["burstable_baseline_per_vcpu"].get(name)
    if base is not None:  # créditos de CPU, como la primaria en change_db_plan
        sustained = round(plan["vcpu"] * base["value"], 3)
        db["read_replicas"]["cpu_credits"] = {
            "baseline_per_vcpu": {**base},
            "sustained_vcpu": _num(
                sustained,
                "vCPU",
                _weakest(plan["vcpu_label"], base["label"]),
                f"vCPU × base por vCPU: lo que rinde {name} con carga sostenida",
                derived=True,
            ),
        }
    warnings.append(
        "Las réplicas suponen que la app envía las lecturas a la réplica (hoy el código usa una sola DB). "
        "No se simula el retraso de replicación."
    )
    was = f"{value(before)} → " if before else ""
    return f"DB: réplicas de lectura {was}{op.count} × {provider} {name} (US${per * op.count:,.2f}/mes)"


def _remove_read_replica(m: dict[str, Any], op: RemoveReadReplica, catalog: dict[str, Any], warnings: list[str]) -> str:
    db = m["deployment"]["db"]
    replicas = db.pop("read_replicas", None)
    if replicas is None:
        raise OpError("La DB no tiene réplicas de lectura.")
    return f"DB: sin réplicas de lectura ({value(replicas.get('count'))} menos); todo vuelve a la primaria"


_APPLY = {
    ScaleApi: _scale_api,
    AddReadReplica: _add_read_replica,
    RemoveReadReplica: _remove_read_replica,
    ChangeDbPlan: _change_db_plan,
    AddPooler: _add_pooler,
    AddCache: _add_cache,
    MoveToQueue: _move_to_queue,
    RemoveCache: _remove_cache,
    RemovePooler: _remove_pooler,
    MoveToSync: _move_to_sync,
    ScaleWorkers: _scale_workers,
}


# ---------- supuestos ----------
def collect_assumptions(model: dict[str, Any]) -> dict[str, Any]:
    """Igual que en build_model.py: los ``SUPUESTO`` de origen, agrupados por fuente."""
    found = _walk_assumptions({k: v for k, v in model.items() if k not in ("checks", "assumptions")})
    by_source: dict[str, dict[str, Any]] = {}
    for a in found:
        g = by_source.setdefault(
            a["source"],
            {"source": a["source"], "count": 0, "needs_review": a["needs_review"], "example_path": a["path"]},
        )
        g["count"] += 1
    return {"total": len(found), "by_source": sorted(by_source.values(), key=lambda g: -g["count"]), "items": found}


def _walk_assumptions(node: Any, path: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("label") == "SUPUESTO" and "value" in node and not node.get("derived"):
            out.append(
                {
                    "path": path,
                    "value": node["value"],
                    "unit": node["unit"],
                    "source": node["source"],
                    "needs_review": node.get("needs_review", False),
                }
            )
        for k, v in node.items():
            out += _walk_assumptions(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _walk_assumptions(v, f"{path}[{i}]")
    return out
