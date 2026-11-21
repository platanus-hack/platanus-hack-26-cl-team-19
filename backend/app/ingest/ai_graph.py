"""La arquitectura de un repo, propuesta por IA, para cualquier framework (JAJ-85, JAJ-86, ADR 0002).

Branchpoint no tiene extractores por framework. Una IA lee el repo y manda su arquitectura con el
schema de este módulo (``ArchitectureSubmission``). La IA puede ser de dos lados, y el schema es el mismo:

* **La CLI del usuario** (JAJ-54), con la tool MCP ``submit_architecture``: lee su repo local.
* **La ingesta de GitHub** (``app/ingest/analyzer.py``): Claude en el servidor lee el tarball.

Este módulo la valida y la convierte en el grafo intermedio (endpoints → efectos con forma y
``archivo:línea``) que ``build_model.build_from_graph`` transforma en ``branchpoint.model/v1``.

Reglas:

* **La IA clasifica; los números salen del catálogo.** Los pasos usan las formas (``shape``) del catálogo
  y su costo sale de ahí.
* **Los únicos números son configuración leída del código** (``observations``: workers, pool). El
  número tiene que estar escrito en la línea citada. En la ingesta, el servidor lo verifica y lo marca
  ``OBSERVADO``. Desde la CLI no puede verificarlo, así que queda ``ESTIMADO`` y por revisar.
* **Todo trae evidencia:** ``archivo:línea`` y una justificación (``why``) en cada endpoint, paso,
  componente y valor.
* **Procedencia a la vista:** cada endpoint, paso y componente queda con ``origin`` (``kind: "ia"``).
  Los tiempos de sus pasos son ``ESTIMADO`` como máximo.
* **La IaC manda.** Lo que dicen los archivos de despliegue (``iac.py``) gana sobre lo que propone la IA.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ingest import build_model as bm
from app.ingest.iac import Findings

Via = Literal["cli", "ingesta"]
AI_SOURCE: dict[str, str] = {"cli": "la IA en la CLI del usuario", "ingesta": "la IA de la ingesta de Branchpoint"}
DB_SHAPES = tuple(k for k in bm.CATALOG["db_shapes"] if not k.startswith("_"))
CPU_SHAPES = tuple(k for k in bm.CATALOG["cpu_steps"] if not k.startswith("_"))

_FILE = re.compile(r"^(?!/)(?!.*(^|/)\.\.(/|$))[^\0\n]{1,300}$")
_NO_PARENS = str.maketrans({"(": "[", ")": "]"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Evidence(_Strict):
    file: str = Field(description="Ruta relativa a la raíz del repo, por ejemplo src/routes/orders.ts.")
    line: int = Field(ge=1, le=1_000_000, description="Línea donde está lo que se describe.")
    why: str = Field(min_length=3, max_length=300, description="Por qué se clasificó así, en una frase.")

    @field_validator("file")
    @classmethod
    def _relative(cls, v: str) -> str:
        if not _FILE.match(v):
            raise ValueError("debe ser una ruta relativa a la raíz del repo, sin '..'")
        return v

    @property
    def at(self) -> str:
        return f"{self.file}:{self.line}"


class AiEffect(_Evidence):
    """Un paso de un request o de un trabajo en cola, además de la CPU propia del framework."""

    kind: Literal["db", "cache", "external", "background", "cpu"] = Field(
        description="db: consulta o escritura a la base de datos. cache: get/set a Redis u otra caché. "
        "external: llamada HTTP o SDK a otro servicio. background: encolar un trabajo. cpu: trabajo pesado "
        "de CPU en el request (hash de contraseña)."
    )
    op: Literal["read", "write"] | None = Field(None, description="Solo db: read o write.")
    shape: str | None = Field(
        None,
        description=f"db: {', '.join(DB_SHAPES)} (pk = por clave primaria, lookup = por un campo con índice, "
        "range = lista con límite, count = conteo con filtro, count_all = conteo de la tabla, scan = lista sin "
        "límite ni índice, stage = add/insert antes del commit, commit = escritura que confirma la transacción, "
        f"unknown = no se sabe). cpu: {', '.join(CPU_SHAPES)} (bcrypt va en password_hash_bcrypt). Los demás "
        "tipos no llevan shape.",
    )
    entity: str | None = Field(None, max_length=80, description="Solo db: la tabla o el modelo (User, orders).")
    service: str | None = Field(
        None, max_length=80, description="Solo external: el servicio llamado (Stripe, SendGrid, S3, otra API)."
    )
    queue: str | None = Field(None, max_length=80, description="Solo background: la cola, si el código la nombra.")
    task: str | None = Field(
        None, max_length=200, description="Solo background: el trabajo que se encola (como en jobs[].task)."
    )
    on_miss: list[AiEffect] | None = Field(
        None,
        max_length=10,
        description="Solo cache: si es una lectura de caché (cache-aside), las lecturas a la DB que se hacen "
        "cuando la clave no está, antes de guardarla. Solo pasos db con op read.",
    )
    detail: str = Field(
        min_length=1, max_length=200, description="Lo que hace el código, por ejemplo prisma.order.findMany."
    )
    in_loop: bool = Field(False, description="true si se ejecuta una vez por cada elemento de una lista (N+1).")

    @model_validator(mode="after")
    def _fields_match_kind(self) -> AiEffect:
        if self.kind == "db":
            if self.op is None:
                raise ValueError("un paso db necesita op (read o write)")
            if self.shape not in DB_SHAPES:
                raise ValueError(f"shape de db debe ser una de: {', '.join(DB_SHAPES)}")
        elif self.kind == "cpu":
            if self.shape not in CPU_SHAPES:
                raise ValueError(f"shape de cpu debe ser una de: {', '.join(CPU_SHAPES)}")
        elif self.shape is not None:
            raise ValueError(f"un paso {self.kind} no lleva shape")
        if self.kind != "db" and (self.op is not None or self.entity is not None):
            raise ValueError("op y entity son solo para pasos db")
        if self.kind == "external" and not self.service:
            raise ValueError("un paso external necesita service (el nombre del servicio llamado)")
        if self.kind != "external" and self.service is not None:
            raise ValueError("service es solo para pasos external")
        if self.kind != "background" and (self.queue is not None or self.task is not None):
            raise ValueError("queue y task son solo para pasos background")
        if self.on_miss is not None:
            if self.kind != "cache":
                raise ValueError("on_miss es solo para pasos cache")
            if not self.on_miss or any(q.kind != "db" or q.op != "read" for q in self.on_miss):
                raise ValueError("on_miss lleva solo pasos db con op read")
        return self


class AiEndpoint(_Evidence):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str = Field(pattern=r"^/[^\s]{0,300}$", description="La ruta completa, con el prefijo del router.")
    handler: str = Field(min_length=1, max_length=200, description="La función que atiende el request.")
    is_async: bool = Field(
        False,
        description="true si el handler no bloquea su proceso mientras espera I/O (async/await, event loop "
        "de Node). false si ocupa un hilo o proceso por request.",
    )
    effects: list[AiEffect] = Field(default_factory=list, max_length=60, description="Los pasos, en orden.")


class AiJob(_Evidence):
    """Un trabajo que corre un worker de cola (Celery, BullMQ, Sidekiq...), con sus pasos."""

    task: str = Field(min_length=1, max_length=200, description="El mismo task de los pasos background.")
    queue: str | None = Field(None, max_length=80, description="La cola que consume el worker.")
    effects: list[AiEffect] = Field(min_length=1, max_length=60)


class AiComponent(_Evidence):
    """Una pieza del sistema que el diagrama debe mostrar: caché, cola, servicio externo, storage..."""

    name: str = Field(min_length=1, max_length=80, description="Nombre en el repo (redis, stripe, orders-queue).")
    role: Literal["db", "cache", "queue", "worker", "external", "storage", "search", "other"]
    technology: str | None = Field(None, max_length=80, description="Postgres, Redis, RabbitMQ, Stripe...")


OBSERVABLE = {
    "api.workers": ("procesos", "procesos de la API por réplica (workers, cluster, PM2)"),
    "db.pool_size": ("conexiones", "conexiones fijas del pool por proceso"),
    "db.max_overflow": ("conexiones", "conexiones extra del pool por proceso"),
    "db.pool_timeout_s": ("s", "segundos de espera por una conexión del pool"),
}


class AiObservation(_Evidence):
    """Un valor de configuración escrito tal cual en el código o la config: lo lee la IA, no lo inventa."""

    field: Literal["api.workers", "db.pool_size", "db.max_overflow", "db.pool_timeout_s"]
    value: int = Field(ge=0, le=100_000, description="El número tal como está escrito en esa línea.")


class ArchitectureSubmission(_Strict):
    """Lo que manda la IA. Los números de los pasos los pone el catálogo; la IA solo cita configuración."""

    repo: str = Field(min_length=1, max_length=120, description="Nombre del repo (owner/nombre o carpeta).")
    framework: str = Field(
        min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9 ._+-]*$", description="express, django, spring, gin..."
    )
    language: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9 ._+#-]*$")
    commit: str | None = Field(None, pattern=r"^[0-9a-f]{7,40}$", description="Commit analizado (git rev-parse HEAD).")
    endpoints: list[AiEndpoint] = Field(min_length=1, max_length=300)
    jobs: list[AiJob] = Field(default_factory=list, max_length=50)
    components: list[AiComponent] = Field(default_factory=list, max_length=50)
    observations: list[AiObservation] = Field(
        default_factory=list,
        max_length=10,
        description="Configuración escrita en el repo: workers de la API y pool de conexiones a la DB. Solo si el "
        "número está literal en la línea citada; si no lo está, no lo mandes.",
    )

    @model_validator(mode="after")
    def _unique(self) -> ArchitectureSubmission:
        for what, keys in (
            ("endpoints", [f"{e.method} {e.path}" for e in self.endpoints]),
            ("componentes", [c.name.lower() for c in self.components]),
            ("jobs", [j.task for j in self.jobs]),
            ("observations", [o.field for o in self.observations]),
        ):
            dup = sorted({k for k in keys if keys.count(k) > 1})
            if dup:
                raise ValueError(f"{what} repetidos: {', '.join(dup)}")
        return self


# ---------- de la propuesta al grafo intermedio ----------


def _origin(sub: ArchitectureSubmission, ev: _Evidence, what: str, via: Via) -> dict:
    return {
        "kind": "ia",
        "via": via,
        "framework": sub.framework,
        "label": "ESTIMADO",
        "source": f"{what} por {AI_SOURCE[via]} ({sub.framework}), en {ev.at}",
        "why": ev.why,
    }


def _effects(sub: ArchitectureSubmission, handler: str, effects: list[AiEffect], via: Via) -> list[dict]:
    """Los efectos con la forma del grafo. Una caché con ``on_miss`` se expande como la ve el modelo: la
    lectura, las consultas en la rama de fallo y el set que guarda la clave."""
    out: list[dict] = []
    for e in effects:
        detail = e.detail.translate(_NO_PARENS)  # build_model lee la entidad entre paréntesis
        effect = {
            "kind": e.kind,
            "op": e.op or e.kind,
            "detail": detail,
            "shape": e.shape or "",
            "file": e.file,
            "line": e.line,
            "in_loop": e.in_loop,
            "branch": [],
            "via": [handler],
            "origin": _origin(sub, e, "Paso clasificado", via),
        }
        if e.kind == "db" and e.entity:
            effect["detail"] = f"{detail} ({e.entity.translate(_NO_PARENS)})"
        if e.kind == "external":
            effect.update(kind="http", detail=f"{e.service}: {detail}", service=e.service)
        if e.kind == "background":
            effect.update({k: v for k, v in (("task", e.task), ("queue", e.queue)) if v})
        out.append(effect)
        if e.on_miss:
            miss = [[e.at, "cache_miss"]]
            effect["cache_miss"] = [e.at, e.line]
            for query in _effects(sub, handler, e.on_miss, via):
                out.append({**query, "branch": miss})
            out.append({**effect, "op": "set", "branch": miss, "cache_miss": None})
            out[-1].pop("cache_miss")
    return out


def to_graph(sub: ArchitectureSubmission, via: Via) -> dict:
    """El grafo intermedio: lo que ``build_from_graph`` sabe convertir en modelo."""
    endpoints = [
        {
            "method": ep.method,
            "path": ep.path,
            "handler": ep.handler,
            "file": ep.file,
            "line": ep.line,
            "async": ep.is_async,
            "effects": _effects(sub, ep.handler, ep.effects, via),
            "risks": [],
            "origin": _origin(sub, ep, "Endpoint encontrado", via),
        }
        for ep in sub.endpoints
    ]
    graph = {
        "repo": sub.repo,
        "stats": {
            "endpoints": len(endpoints),
            "effects": sum(len(ep["effects"]) for ep in endpoints),
            "jobs": len(sub.jobs),
        },
        "endpoints": endpoints,
        "source": {
            "kind": "ia",
            "via": via,
            "framework": sub.framework,
            "language": sub.language,
            **({"commit": sub.commit} if sub.commit else {}),
        },
    }
    if sub.jobs:
        graph["jobs"] = {job.task: _effects(sub, job.task, job.effects, via) for job in sub.jobs}
    return graph


def _services(sub: ArchitectureSubmission, via: Via) -> list[dict]:
    return [
        {
            "name": c.name,
            "role": c.role,
            "at": c.at,
            **({"engine": c.technology} if c.technology else {}),
            "source_file": "ia",
            "origin": _origin(sub, c, "Componente encontrado", via),
        }
        for c in sub.components
    ]


def _line(root: Path, file: str, line: int) -> str | None:
    path = (root / file).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return None
    with path.open(encoding="utf-8", errors="replace") as f:
        for i, text in enumerate(f, start=1):
            if i == line:
                return text
    return None


def observed_values(sub: ArchitectureSubmission, root: Path | None) -> tuple[dict[str, dict], list[str]]:
    """Los valores de configuración que citó la IA, con su etiqueta. Con el repo a mano (ingesta), el
    número tiene que estar escrito en la línea citada: si está, es ``OBSERVADO``; si no, se descarta con
    un aviso. Sin el repo (CLI), quedan ``ESTIMADO`` y por revisar."""
    values: dict[str, dict] = {}
    warnings: list[str] = []
    for o in sub.observations:
        unit, what = OBSERVABLE[o.field]
        if root is None:
            values[o.field] = bm.num(
                o.value,
                unit,
                "ESTIMADO",
                f"{o.value} {what} en {o.at}, según la IA en la CLI (el servidor no vio el archivo)",
                at=o.at,
                needs_review=True,
            )
            continue
        text = _line(root, o.file, o.line)
        if text is None or not re.search(rf"(?<![\d.]){o.value}(?![\d.])", text):
            warnings.append(f"La IA citó {o.field}={o.value} en {o.at}, pero ese número no está en esa línea.")
            continue
        values[o.field] = bm.num(o.value, unit, "OBSERVADO", f"{o.value} {what} en {o.at}", at=o.at)
    return values, warnings


def build_from_ai(
    sub: ArchitectureSubmission,
    answers: dict | None = None,
    *,
    via: Via = "cli",
    iac: dict | None = None,
    root: Path | None = None,
) -> dict:
    """La v1 de un repo: el grafo de la IA, la IaC si se leyó (``iac``) y el catálogo.

    ``root`` es el repo en disco (ingesta): con él se verifican los valores que citó la IA."""
    iac = copy.deepcopy(iac) if iac is not None else Findings().to_dict()
    if not iac["files"]:
        iac["warnings"].append(
            "No hay archivos de despliegue leídos: el despliegue queda con valores por defecto por revisar."
        )
    seen_names = {s["name"].lower() for s in iac["services"]}
    iac["services"] += [s for s in _services(sub, via) if s["name"].lower() not in seen_names]  # la IaC manda
    observed, warnings = observed_values(sub, root)
    iac["warnings"] += warnings

    workers = iac["observed"].get("api.workers") or observed.get("api.workers")
    if workers is None:
        workers = {
            **bm.from_catalog(bm.CATALOG["api"]["workers_default"]),
            "label": "SUPUESTO",
            "needs_review": True,
            "source": f"Valor por defecto: ni la IaC ni el código dicen cuántos procesos levanta la API "
            f"({sub.framework}: workers, cluster, PM2...). Confírmalo con el usuario",
        }
    pool = bm.default_pool(
        f"El repo ({sub.framework}) no declara el pool de conexiones de su ORM o driver: se usa el de "
        "SQLAlchemy como valor de partida, por revisar",
        library="desconocida",
    )
    for key in ("pool_size", "max_overflow", "pool_timeout_s"):
        if f"db.{key}" in observed:
            pool[key] = observed[f"db.{key}"]
            pool["defined_at"] = pool["defined_at"] or observed[f"db.{key}"]["at"]
    return bm.build_from_graph(to_graph(sub, via), sub.repo, answers or {}, iac=iac, workers=workers, pool=pool)


def replace_architecture(model: dict, sub: ArchitectureSubmission) -> dict:
    """Una versión nueva de un proyecto con la arquitectura que mandó la CLI: cambian los endpoints, las
    colas y los componentes de la IA; se quedan el despliegue, el tráfico, el negocio y lo que dijo la IaC.

    Devuelve el modelo sin ``checks`` (el que guarda recalcula los supuestos)."""
    new = copy.deepcopy(model)
    fresh = build_from_ai(sub)
    new["endpoints"] = fresh["endpoints"]
    dep = new.setdefault("deployment", {})
    if "queues" in fresh["deployment"]:
        dep["queues"] = fresh["deployment"]["queues"]
    else:
        dep.pop("queues", None)
    from_iac = [s for s in dep.get("services", []) if not s.get("origin")]
    names = {s["name"].lower() for s in from_iac}
    dep["services"] = from_iac + [s for s in fresh["deployment"]["services"] if s["name"].lower() not in names]
    new["repo"] = {**new.get("repo", {}), "stats": fresh["repo"]["stats"], "source": fresh["repo"]["source"]}
    new.pop("checks", None)
    return new
