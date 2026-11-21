"""La arquitectura que propone la IA del usuario, para repos sin extractor determinista (JAJ-85, JAJ-86).

El extractor AST (``extract.py``) solo lee FastAPI. Para otro framework (Express, Django, Spring, Go...),
la IA que corre en la CLI del usuario (JAJ-54) lee su repo local y manda la arquitectura con la tool
``submit_architecture``. Este módulo la valida y la convierte en el mismo grafo intermedio que produce
el extractor, para que ``build_model.build_from_graph`` arme el modelo igual que siempre.

Reglas (ADR 0001):

* **La IA clasifica, no pone números.** El schema no tiene ningún campo numérico salvo la línea de la
  evidencia. Las formas (``shape``) son las del catálogo, y el costo de cada paso sale de ahí.
* **Todo trae evidencia:** ``archivo:línea`` y una justificación (``why``) en cada endpoint, paso y
  componente.
* **Procedencia a la vista:** cada endpoint, paso y componente queda con ``origin`` (``kind: "ia"``).
  Los tiempos de sus pasos bajan a ``ESTIMADO`` como máximo, y la CPU base del framework queda
  ``SUPUESTO`` (el catálogo la midió en FastAPI).
* **El código manda.** Al sumar la propuesta a un proyecto que ya tiene modelo, los endpoints y
  componentes que encontró el extractor o la IaC se quedan como están (``merge_into``).
"""

from __future__ import annotations

import copy
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ingest import build_model as bm
from app.ingest.iac import Findings

AI_SOURCE = "IA en la CLI del usuario"
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
    """Un paso de un endpoint: lo que hace el request además de la CPU propia del framework."""

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
        "límite ni índice, stage = add/insert antes del commit, commit = commit de la transacción, unknown = no "
        f"se sabe). cpu: {', '.join(CPU_SHAPES)}. Los demás tipos no llevan shape.",
    )
    entity: str | None = Field(None, max_length=80, description="Solo db: la tabla o el modelo (User, orders).")
    service: str | None = Field(
        None, max_length=80, description="Solo external: el servicio llamado (Stripe, SendGrid, S3, otra API)."
    )
    detail: str = Field(
        min_length=1, max_length=200, description="Lo que hace el código, por ejemplo prisma.order.findMany."
    )
    in_loop: bool = Field(False, description="true si se ejecuta una vez por cada elemento de una lista (N+1).")

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> AiEffect:
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
        return self


class AiEndpoint(_Evidence):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str = Field(pattern=r"^/[^\s]{0,300}$", description="La ruta completa, con el prefijo del router.")
    handler: str = Field(min_length=1, max_length=200, description="La función que atiende el request.")
    is_async: bool = Field(
        False, description="true si el handler no bloquea el proceso (async/await, event loop de Node)."
    )
    effects: list[AiEffect] = Field(default_factory=list, max_length=60, description="Los pasos, en orden.")


class AiComponent(_Evidence):
    """Una pieza del sistema que el diagrama debe mostrar: caché, cola, servicio externo, storage..."""

    name: str = Field(min_length=1, max_length=80, description="Nombre en el repo (redis, stripe, orders-queue).")
    role: Literal["db", "cache", "queue", "worker", "external", "storage", "search", "other"]
    technology: str | None = Field(None, max_length=80, description="Postgres, Redis, RabbitMQ, Stripe...")


class ArchitectureSubmission(_Strict):
    """Lo que manda la IA del usuario. Ningún número: los pone el catálogo."""

    repo: str = Field(min_length=1, max_length=120, description="Nombre del repo (owner/nombre o carpeta).")
    framework: str = Field(
        min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9 ._+-]*$", description="express, django, spring, gin..."
    )
    language: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9 ._+#-]*$")
    commit: str | None = Field(None, pattern=r"^[0-9a-f]{7,40}$", description="Commit analizado (git rev-parse HEAD).")
    endpoints: list[AiEndpoint] = Field(min_length=1, max_length=300)
    components: list[AiComponent] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _unique(self) -> ArchitectureSubmission:
        ids = [f"{e.method} {e.path}" for e in self.endpoints]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"endpoints repetidos: {', '.join(dup)}")
        names = [c.name.lower() for c in self.components]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ValueError(f"componentes repetidos: {', '.join(dup)}")
        return self


# ---------- de la propuesta al grafo intermedio de extract.py ----------


def _origin(sub: ArchitectureSubmission, ev: _Evidence, what: str) -> dict:
    return {
        "kind": "ia",
        "framework": sub.framework,
        "label": "ESTIMADO",
        "source": f"{what} por la {AI_SOURCE} ({sub.framework}), en {ev.at}",
        "why": ev.why,
    }


def _effect(sub: ArchitectureSubmission, ep: AiEndpoint, e: AiEffect) -> dict:
    detail = e.detail.translate(_NO_PARENS)  # build_model lee la entidad entre paréntesis
    out = {
        "kind": e.kind,
        "op": e.op or e.kind,
        "detail": detail,
        "shape": e.shape or "",
        "file": e.file,
        "line": e.line,
        "in_loop": e.in_loop,
        "branch": [],
        "via": [ep.handler],
        "origin": _origin(sub, e, "Paso clasificado"),
    }
    if e.kind == "db" and e.entity:
        out["detail"] = f"{detail} ({e.entity.translate(_NO_PARENS)})"
    if e.kind == "external":
        out["kind"] = "http"
        out["detail"] = f"{e.service}: {detail}"
        out["service"] = e.service
    return out


def to_graph(sub: ArchitectureSubmission) -> dict:
    """El grafo con la forma de ``extract.run``: lo que ``build_from_graph`` sabe convertir en modelo."""
    endpoints = [
        {
            "method": ep.method,
            "path": ep.path,
            "handler": ep.handler,
            "file": ep.file,
            "line": ep.line,
            "async": ep.is_async,
            "effects": [_effect(sub, ep, e) for e in ep.effects],
            "risks": [],
            "origin": _origin(sub, ep, "Endpoint encontrado"),
        }
        for ep in sub.endpoints
    ]
    return {
        "repo": sub.repo,
        "stats": {"endpoints": len(endpoints), "effects": sum(len(ep["effects"]) for ep in endpoints)},
        "endpoints": endpoints,
        "source": {
            "kind": "ia",
            "framework": sub.framework,
            "language": sub.language,
            **({"commit": sub.commit} if sub.commit else {}),
        },
    }


def _services(sub: ArchitectureSubmission) -> list[dict]:
    return [
        {
            "name": c.name,
            "role": c.role,
            "at": c.at,
            **({"engine": c.technology} if c.technology else {}),
            "source_file": "ia",
            "origin": _origin(sub, c, "Componente encontrado"),
        }
        for c in sub.components
    ]


def build_from_ai(sub: ArchitectureSubmission, answers: dict | None = None) -> dict:
    """La v1 de un repo sin extractor: el grafo de la IA, sin IaC leída y con el despliegue por defecto."""
    iac = Findings().to_dict()
    iac["services"] = _services(sub)
    iac["warnings"].append(
        "La arquitectura la propuso la IA del usuario: el servidor no leyó los archivos de despliegue."
    )
    workers = bm.from_catalog(bm.CATALOG["api"]["workers_default"])
    workers = {**workers, "label": "SUPUESTO", "needs_review": True}
    pool = bm.default_pool(f"La IA del usuario describió el repo ({sub.framework}): no se leyó la config del pool")
    return bm.build_from_graph(to_graph(sub), sub.repo, answers or {}, iac=iac, workers=workers, pool=pool)


def merge_into(model: dict, sub: ArchitectureSubmission) -> tuple[dict, dict]:
    """Suma la propuesta a un modelo existente. Lo que vino del extractor o de la IaC manda: la IA solo
    agrega endpoints y componentes que no estaban, y reemplaza lo que había propuesto antes.

    Devuelve el modelo nuevo (sin ``checks``; el que guarda recalcula los supuestos) y lo que se ignoró."""
    new = copy.deepcopy(model)
    fresh = build_from_ai(sub)
    from_code = [ep for ep in new.get("endpoints", []) if not ep.get("origin")]
    code_ids = {ep["id"] for ep in from_code}
    ai = [ep for ep in fresh["endpoints"] if ep["id"] not in code_ids]
    ignored_eps = [ep["id"] for ep in fresh["endpoints"] if ep["id"] in code_ids]
    new["endpoints"] = from_code + ai
    bm.endpoint_weights(new["endpoints"], {})

    dep = new.setdefault("deployment", {})
    code_services = [s for s in dep.get("services", []) if not s.get("origin")]
    code_names = {s["name"].lower() for s in code_services}
    ai_services = [s for s in fresh["deployment"]["services"] if s["name"].lower() not in code_names]
    ignored_components = [s["name"] for s in fresh["deployment"]["services"] if s["name"].lower() in code_names]
    dep["services"] = code_services + ai_services
    new.pop("checks", None)
    return new, {"endpoints": ignored_eps, "components": ignored_components}
