"""Operaciones tipadas sobre el modelo v1: con ellas, el agente propone versiones (JAJ-68).

Según el ADR 0001 (``docs/adr/0001-el-llm-opera-sobre-el-modelo-no-lo-extrae.md``), el LLM no edita el
JSON del modelo ni escribe números. Propone cambios de arquitectura solo con este conjunto cerrado
de operaciones. Cada una es una función pura ``modelo v1 → modelo v1``:

* ``scale_api(replicas, vcpu?)``: réplicas y vCPU de la API, y su costo mensual.
* ``change_db_plan(plan, provider?)``: un plan del catálogo, con sus vCPU, conexiones, procesador,
  créditos de CPU, pooler y precio.
* ``add_pooler(max_client_connections?)``: un pooler de conexiones (Supavisor en Supabase,
  PgBouncer en otros). La app se conecta al pooler y deja de chocar con ``max_connections``.
* ``add_cache(endpoint, hit_ratio, steps?)``: las consultas del endpoint pasan a ``on_miss`` de una
  caché (el formato que entiende el motor desde JAJ-14).
* ``move_to_queue(endpoint, step, workers, queue?, max_length?)``: un paso del endpoint pasa a los
  ``job_steps`` de una cola en ``deployment.queues``, y la request solo encola.

Reglas de los números:

* Los que vienen de un plan o de un paso típico salen del catálogo (``app/catalog``), con su fuente.
* Los que elige quien propone (réplicas, workers, tasa de aciertos) quedan ``SUPUESTO``. Si viene
  ``quote``, la fuente es la frase del usuario. Si no, quedan con ``needs_review`` para que la UI
  los resalte.
* Ningún número nuevo queda sin ``label``, ``source`` y ``date``.

Cada operación valida sus argumentos y lanza ``OperationError`` con un mensaje en español si no
aplica (endpoint o plan inexistente, pooler repetido...). ``apply_operations`` las aplica en orden
sobre una copia y valida que el resultado cargue con ``load_model``.
"""

from __future__ import annotations

import copy
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.catalog import (
    HOURS_MONTH,
    catalog,
    core_factor,
    cpu_credits,
    db_plan_source,
    db_plans,
    db_usd_month,
    from_catalog,
    num,
    today,
    weakest,
)
from app.models.architecture import load_model, value


class OperationError(ValueError):
    """Una operación que no aplica al modelo. ``index`` es su posición en la lista, si vino en una."""

    def __init__(self, message: str, index: int | None = None) -> None:
        super().__init__(message)
        self.index = index


def _chosen(value_: Any, unit: str, what: str, quote: str | None) -> dict[str, Any]:
    """Un número que elige quien propone el cambio: ``SUPUESTO``, con la frase del usuario si la hay."""
    if quote:
        return num(value_, unit, "SUPUESTO", f"Declarado por el usuario: «{quote}» ({what})")
    return num(value_, unit, "SUPUESTO", f"Propuesto sin dato del usuario: {what}", needs_review=True)


def _endpoint(raw: dict[str, Any], endpoint_id: str) -> dict[str, Any]:
    for e in raw["endpoints"]:
        if e["id"] == endpoint_id:
            return e
    raise OperationError(f"El modelo no tiene el endpoint '{endpoint_id}'.")


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str | None = Field(
        None, max_length=500, description="Frase del usuario que respalda los números de la operación, si la hay."
    )

    def apply(self, raw: dict[str, Any]) -> str:  # pragma: no cover - cada operación lo implementa
        """Aplica la operación sobre ``raw`` (ya es una copia) y devuelve qué cambió, en español."""
        raise NotImplementedError


class ScaleApi(_Operation):
    """Cambia las réplicas (y opcionalmente los vCPU por réplica) de la API, y recalcula su costo."""

    op: Literal["scale_api"] = "scale_api"
    replicas: int = Field(ge=1, le=100, description="Réplicas de la API.")
    vcpu: float | None = Field(None, gt=0, le=64, description="vCPU por réplica. Sin él, quedan los actuales.")

    def apply(self, raw: dict[str, Any]) -> str:
        api = raw["deployment"]["api"]
        before = (value(api["replicas"], 1), value(api["vcpu"], 1))
        api["replicas"] = _chosen(self.replicas, "réplicas", "réplicas de la API", self.quote)
        if self.vcpu is not None:
            api["vcpu"] = _chosen(self.vcpu, "vCPU", "vCPU por réplica de la API", self.quote)
        price = catalog()["app_plans"].get(api.get("provider", "local"))
        if price is not None and api.get("memory_gb") is not None:
            mem = api["memory_gb"]
            usd = self.replicas * (value(api["vcpu"]) * price["usd_vcpu_hour"] + value(mem) * price["usd_gb_hour"])
            api["usd_month"] = num(
                round(usd * HOURS_MONTH, 2),
                "US$/mes",
                weakest(api["replicas"]["label"], api["vcpu"]["label"], mem["label"], "ESTIMADO"),
                f"{catalog()['app_plans']['_source']}. réplicas × (vCPU × US$/vCPU-hora + GB × US$/GB-hora) × "
                f"{HOURS_MONTH} h",
                derived=True,
            )
        after = (self.replicas, value(api["vcpu"]))
        return f"API: {before[0]} → {after[0]} réplicas" + (
            f", {before[1]:g} → {after[1]:g} vCPU por réplica" if self.vcpu is not None else ""
        )


class ChangeDbPlan(_Operation):
    """Cambia el plan de la DB por uno del catálogo, con todos sus números."""

    op: Literal["change_db_plan"] = "change_db_plan"
    plan: str = Field(description="Plan del catálogo, ej. 'small' en Supabase o 'db.m7g.large' en RDS.")
    provider: str | None = Field(None, description="supabase, rds_postgres o local. Sin él, el proveedor actual.")

    def apply(self, raw: dict[str, Any]) -> str:
        db = raw["deployment"]["db"]
        provider = self.provider or db.get("provider", "local")
        plans = db_plans(provider)
        if not plans:
            known = ", ".join(k for k, v in catalog()["db_plans"].items() if isinstance(v, dict) and k != "_sources")
            raise OperationError(f"No hay planes de DB para el proveedor '{provider}'. Hay: {known}.")
        if self.plan not in plans:
            raise OperationError(f"El catálogo no tiene el plan '{self.plan}' en {provider}. Hay: {', '.join(plans)}.")
        plan = plans[self.plan]
        before = f"{db.get('provider')} {db.get('plan')}"
        src = db_plan_source(provider, self.plan)
        db["provider"], db["plan"] = provider, self.plan
        db["vcpu"] = num(plan["vcpu"], "vCPU", plan["vcpu_label"], src)
        db["max_connections"] = num(plan["max_connections"], "conexiones", "ESTIMADO", src)
        db["usd_month"] = num(
            db_usd_month(provider, plan),
            "US$/mes",
            "ESTIMADO",
            f"{src}. Supabase: 25 + max(0, compute − 10); RDS: US$/hora × {HOURS_MONTH} (JAJ-11)",
        )
        db["cpu_core_factor"] = core_factor(plan, f"Plan {provider} {self.plan}")
        credits = cpu_credits(self.plan, db["vcpu"])
        if credits:
            db["cpu_credits"] = credits
        else:
            db.pop("cpu_credits", None)
        if "pooler_connections" in plan:
            db["pooler_connections"] = num(plan["pooler_connections"], "conexiones", "ESTIMADO", src)
        else:
            db.pop("pooler_connections", None)
        note = ""
        pooler = db.get("pooler")
        if pooler and pooler.get("kind") == "supavisor":
            if provider == "supabase":
                pooler["max_client_connections"] = db["pooler_connections"]
            else:
                db.pop("pooler")
                note = " (se quitó el pooler de Supabase, que no aplica al proveedor nuevo)"
        return (
            f"DB: {before} → {provider} {self.plan} ({plan['vcpu']:g} vCPU, {plan['max_connections']} conexiones){note}"
        )


class AddPooler(_Operation):
    """Agrega un pooler de conexiones: Supavisor en Supabase (límite del catálogo) o PgBouncer en otros."""

    op: Literal["add_pooler"] = "add_pooler"
    max_client_connections: int | None = Field(
        None,
        ge=1,
        description="Conexiones de la app que acepta el pooler. En Supabase sale del catálogo; en otros es obligatorio.",
    )

    def apply(self, raw: dict[str, Any]) -> str:
        db = raw["deployment"]["db"]
        if "pooler" in db:
            raise OperationError("El modelo ya tiene un pooler de conexiones.")
        if db.get("provider") == "supabase" and self.max_client_connections is None:
            limit = db.get("pooler_connections")
            if limit is None:
                plan = db_plans("supabase").get(db.get("plan"), {})
                if "pooler_connections" not in plan:
                    raise OperationError(f"El catálogo no tiene el límite del pooler para Supabase {db.get('plan')}.")
                limit = num(
                    plan["pooler_connections"], "conexiones", "ESTIMADO", db_plan_source("supabase", db["plan"])
                )
            db["pooler"] = {"kind": "supavisor", "max_client_connections": copy.deepcopy(limit)}
        else:
            if self.max_client_connections is None:
                raise OperationError(
                    "Para un pooler fuera de Supabase (ej. PgBouncer) hay que indicar max_client_connections: "
                    "el catálogo no tiene ese límite."
                )
            kind = "supavisor" if db.get("provider") == "supabase" else "pgbouncer"
            limit = _chosen(self.max_client_connections, "conexiones", f"conexiones que acepta {kind}", self.quote)
            db["pooler"] = {"kind": kind, "max_client_connections": limit}
        p = db["pooler"]
        return f"Pooler {p['kind']}: la app se conecta al pooler, que acepta {value(p['max_client_connections'])} conexiones"


class AddCache(_Operation):
    """Pone las consultas de un endpoint detrás de una caché: solo se hacen cuando la caché falla."""

    op: Literal["add_cache"] = "add_cache"
    endpoint: str = Field(description="Id del endpoint, ej. 'GET /items/'.")
    hit_ratio: float = Field(ge=0, le=1, description="Fracción de las lecturas que encuentra el dato en la caché.")
    steps: list[int] | None = Field(
        None,
        description=(
            "Índices de los pasos de DB que pasan a on_miss. Sin él, las consultas del handler del endpoint "
            "(no las de sus dependencias, como la autenticación)."
        ),
    )

    def apply(self, raw: dict[str, Any]) -> str:
        ep = _endpoint(raw, self.endpoint)
        steps = ep["steps"]
        if any(s.get("resource") == "cache" and "on_miss" in s for s in steps):
            raise OperationError(f"{self.endpoint} ya tiene una caché con on_miss.")
        if self.steps is None:
            db = [i for i, s in enumerate(steps) if s.get("resource") == "db_connection"]
            handler = ep.get("handler")
            own = [i for i in db if handler and (steps[i].get("via") or [None])[0] == handler]
            chosen = own or db
        else:
            chosen = sorted(set(self.steps))
            bad = [i for i in chosen if not 0 <= i < len(steps) or steps[i].get("resource") != "db_connection"]
            if bad:
                raise OperationError(f"Los pasos {bad} de {self.endpoint} no existen o no son consultas a la DB.")
        if not chosen:
            raise OperationError(f"{self.endpoint} no tiene consultas a la DB que cachear.")
        cached = [steps[i] for i in chosen]
        cache_step = {
            "kind": "cache",
            "shape": "cache_aside",
            "detail": "Caché propuesta: GET; si falla, las consultas de on_miss y SET (JAJ-68)",
            "at": cached[0].get("at"),
            "resource": "cache",
            "time": from_catalog(catalog()["other_steps"]["cache"]),
            "hit_ratio": _chosen(
                self.hit_ratio, "fracción", f"tasa de aciertos de la caché en {self.endpoint}", self.quote
            ),
            "on_miss": cached,
            "proposed": True,
        }
        first = chosen[0]
        ep["steps"] = [s for i, s in enumerate(steps) if i not in chosen]
        ep["steps"].insert(first - sum(1 for i in chosen if i < first), cache_step)
        return (
            f"Caché en {self.endpoint}: {len(cached)} consulta(s) pasan a on_miss, con {self.hit_ratio:.0%} de aciertos"
        )


class MoveToQueue(_Operation):
    """Saca un paso de la request y lo pasa a un trabajo de una cola con workers asíncronos."""

    op: Literal["move_to_queue"] = "move_to_queue"
    endpoint: str = Field(description="Id del endpoint.")
    step: int = Field(ge=0, description="Índice del paso que pasa a la cola.")
    workers: int = Field(ge=1, le=1000, description="Trabajos en paralelo de la cola.")
    queue: str = Field("default", pattern=r"^[a-z][a-z0-9_-]{0,39}$", description="Nombre de la cola nueva.")
    max_length: int | None = Field(None, ge=1, description="Trabajos esperando como máximo. Sin él, sin límite.")

    def apply(self, raw: dict[str, Any]) -> str:
        ep = _endpoint(raw, self.endpoint)
        steps = ep["steps"]
        if not 0 <= self.step < len(steps):
            raise OperationError(f"{self.endpoint} tiene los pasos 0 a {len(steps) - 1}; no existe el {self.step}.")
        queues = raw["deployment"].setdefault("queues", {})
        if self.queue in queues:
            raise OperationError(f"Ya existe la cola '{self.queue}'. Usa otro nombre.")
        moved = steps[self.step]
        if moved.get("resource") in ("background", "cache"):
            raise OperationError(f"El paso {self.step} de {self.endpoint} es {moved['resource']}: no se puede encolar.")
        steps[self.step] = {
            "kind": "background",
            "detail": f"Encolar en '{self.queue}' (propuesta, JAJ-68)",
            "at": moved.get("at"),
            "resource": "background",
            "time": from_catalog(catalog()["other_steps"]["background"]),
            "queue": self.queue,
            "proposed": True,
        }
        # api_cpu_ms del endpoint incluye sus pasos de CPU: si el paso era de CPU, sale de la request
        if moved.get("resource") == "api_cpu" and isinstance(ep.get("api_cpu_ms"), dict):
            moved_ms = value(moved["time"], 0.0) * value(moved.get("repeat"), 1)
            old = ep["api_cpu_ms"]
            ep["api_cpu_ms"] = num(
                round(max(0.0, value(old, 0.0) - moved_ms), 4),
                old.get("unit", "ms"),
                old.get("label", "ESTIMADO"),
                f"{old.get('source', '')}. Sin el paso que pasó a la cola '{self.queue}' (JAJ-68)",
                derived=True,
            )
        q: dict[str, Any] = {
            "workers": _chosen(self.workers, "trabajos en paralelo", f"workers de la cola {self.queue}", self.quote),
            "job_steps": [moved],
        }
        if self.max_length is not None:
            q["max_length"] = _chosen(self.max_length, "trabajos", f"largo máximo de la cola {self.queue}", self.quote)
        queues[self.queue] = q
        return f"Cola '{self.queue}': el paso {self.step} de {self.endpoint} pasa a {self.workers} worker(s)"


Operation = Annotated[ScaleApi | ChangeDbPlan | AddPooler | AddCache | MoveToQueue, Field(discriminator="op")]
OPERATIONS = {o.model_fields["op"].default: o for o in (ScaleApi, ChangeDbPlan, AddPooler, AddCache, MoveToQueue)}
_operation_adapter: TypeAdapter[Operation] = TypeAdapter(Operation)


def parse_operation(data: dict[str, Any]) -> Operation:
    """Valida un dict como una operación (``{"op": "scale_api", "replicas": 3}``)."""
    return _operation_adapter.validate_python(data)


def apply_operations(raw: dict[str, Any], ops: list[Operation]) -> tuple[dict[str, Any], list[str]]:
    """Aplica las operaciones en orden sobre una copia del modelo y devuelve el modelo nuevo y qué cambió.

    El modelo nuevo guarda su historial en ``operations`` y marca ``checks`` como desactualizados (las
    cotas de build_model.py son de la versión anterior; el motor es el que vale). Si una operación no
    aplica, o el resultado no carga con ``load_model``, lanza ``OperationError``.
    """
    model = copy.deepcopy(raw)
    changes: list[str] = []
    for i, op in enumerate(ops):
        try:
            change = op.apply(model)
        except OperationError as e:
            raise OperationError(f"Operación {i + 1} ({op.op}): {e}", index=i) from e
        changes.append(change)
        model.setdefault("operations", []).append(
            {"op": op.op, "args": op.model_dump(exclude={"op"}, exclude_none=True), "change": change, "date": today()}
        )
    if ops and isinstance(model.get("checks"), dict):
        model["checks"]["stale"] = (
            "Calculados para el modelo antes de las operaciones (JAJ-68): usar el motor para esta versión."
        )
    try:
        load_model(model)
    except (KeyError, ValueError, TypeError) as e:
        raise OperationError(f"El modelo resultante no es válido: {e}") from e
    return model, changes
