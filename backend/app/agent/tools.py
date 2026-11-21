"""Las tools del agente (ADR 0001, JAJ-67), sobre los proyectos reales de un usuario.

Se implementan una vez y se exponen dos veces (ADR 0001):

* en el **loop del chat** del editor (``app/agent/loop.py``): el modo principal, con la cuota de Branchpoint o
  la key del usuario;
* por **MCP** (``app/agent/mcp.py``): la vía secundaria, para una CLI de IA.

Reglas, iguales en los dos modos:

* **Ningún número libre del LLM.** Los números del usuario (tráfico, metas, réplicas) entran con
  ``quote``, su frase, y cada número tiene que aparecer en ella. ``simulate`` y ``compare`` eligen
  un escenario del proyecto: no reciben req/s ni duración. Las decisiones de diseño de
  ``propose_version`` quedan ``SUPUESTO`` (JAJ-68).
* **Procedencia en cada resultado**, para que el agente la cite.
* **Errores con una sola forma:** ``{"error": "..."}``, con un mensaje que el LLM lee y corrige. Los
  argumentos desconocidos o mal tipados también se rechazan así.
* **Límites por usuario** (``Limiter``): llamadas por minuto y simulaciones por día.
* **La arquitectura de un repo** (ADR 0002) la manda la IA de la CLI, que lee el repo local, con
  ``submit_architecture``: clasifica con evidencia y el catálogo pone los números
  (``app/ingest/ai_graph.py``). Esa tool no se ofrece en el chat del editor, que no ve el repo.
* **Adjuntos del chat** (IA-7): con un ``AttachmentStorage``, el chat suma ``list_attachments``,
  ``read_log``, ``grep_log``, ``analyze_log`` y ``apply_log_traffic``. Los números de un log los saca
  ``app/agent/logs.py`` sin LLM y quedan ``OBSERVADO``. Por MCP no se publican: dependen de una sesión
  del editor.
"""

from __future__ import annotations

import copy
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.logs import analyze_log
from app.agent.ops import OpError, apply_ops, collect_assumptions, ops_json_schema
from app.api.errors import ApiError
from app.api.run_cache import cached_run
from app.api.schemas import MAX_SIMULATED_REQUESTS, RunParams
from app.api.store import Project, ProjectGoals, ProjectScenario, ProjectStore, Version
from app.catalog import load_catalog
from app.costs import cost_delta, estimate_cost, failure_cost
from app.costs.estimate import describe_missing
from app.ingest.ai_graph import ArchitectureSubmission, build_from_ai, replace_architecture
from app.models import load_model
from app.models.compare import run_delta
from app.models.run import Run
from app.storage.attachments import StorageError

SIM_SECONDS = 60.0  # duración por defecto; la elige el servidor, nunca el LLM
MIN_SIM_SECONDS = 5.0
DAILY_SUBMISSIONS = 30  # arquitecturas que la IA puede mandar por usuario y día
CLI_ONLY = frozenset({"submit_architecture"})  # tools que necesitan leer el repo local
ATTACHMENT_TOOLS = ("list_attachments", "read_log", "grep_log", "analyze_log", "apply_log_traffic")
MAX_LOG_BYTES = 10 * 1024 * 1024  # el tope de un adjunto de log (IA-6)
MAX_READ_LINES = 400
MAX_LINE_CHARS = 500
MAX_GREP_MATCHES = 100
DEFAULT_ERROR_RATE = 0.01  # piso de errores cuando el usuario no declaró uno (SUPUESTO, se avisa)
SECONDS_DAY = 86_400
SECONDS_MONTH = 30 * SECONDS_DAY
RANK = {"OBSERVADO": 0, "CALIBRADO": 1, "ESTIMADO": 2, "SUPUESTO": 3}


class ToolError(Exception):
    """Algo que el LLM tiene que leer y corregir."""


# ---------- límites por usuario ----------


@dataclass
class Limits:
    calls_per_minute: int = 60
    simulations_per_day: int = 300


class Limiter:
    """Llamadas por minuto y simulaciones por día, por usuario. En memoria: alcanza para una instancia
    de la API; con varias, cada una cuenta lo suyo (se mueve a Postgres si hace falta)."""

    def __init__(self, limits: Limits | None = None, clock: Any = time.monotonic) -> None:
        self.limits = limits or Limits()
        self._clock = clock
        self._calls: dict[str, deque[float]] = {}
        self._sims: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def call(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            q = self._calls.setdefault(key, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.limits.calls_per_minute:
                raise ToolError(
                    f"Límite de {self.limits.calls_per_minute} llamadas por minuto alcanzado. Espera un momento."
                )
            q.append(now)

    def simulations(self, key: str, n: int) -> None:
        self.daily(f"sims:{key}", self.limits.simulations_per_day, "simulaciones", n)

    def daily(self, key: str, cap: int, what: str, n: int = 1) -> None:
        """Un contador diario por clave: ``ToolError`` si sumar ``n`` pasa ``cap``."""
        day = date.today().isoformat()
        with self._lock:
            used = self._sims.get((key, day), 0)
            if used + n > cap:
                raise ToolError(f"Límite de {cap} {what} por día alcanzado (llevas {used}). Vuelve mañana.")
            self._sims[(key, day)] = used + n


# ---------- argumentos de cada tool (extra=forbid: lo desconocido se rechaza) ----------


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListProjects(_Args):
    pass


class ProjectRef(_Args):
    project_id: str = Field(description="Id del proyecto (de list_projects).")


class VersionRef(ProjectRef):
    version: int | None = Field(None, ge=1, description="Número de versión (v1 = 1). Sin valor, la última.")


class SimulateArgs(VersionRef):
    scenario: str = Field("cyberday", description="Escenario del proyecto (de list_scenarios).")
    seed: int = Field(0, ge=0, le=1_000_000, description="Misma semilla = mismo resultado.")


class CompareArgs(ProjectRef):
    a: int = Field(ge=1, description="Versión base.")
    b: int = Field(ge=1, description="Versión a comparar contra la base.")
    scenario: str = Field("cyberday", description="Escenario del proyecto, el mismo para las dos.")
    seed: int = Field(0, ge=0, le=1_000_000)


class ProposeArgs(VersionRef):
    ops: list[dict[str, Any]] = Field(description="Operaciones de ops_schema, en orden.")
    note: str | None = Field(None, max_length=500, description="Qué cambia y por qué, para el historial.")


Unit = Literal["requests_per_second_peak", "requests_per_day", "orders_per_day", "users_per_month"]


class SetTrafficArgs(VersionRef):
    volume: float = Field(gt=0, description="El número que dijo el usuario (ej. 100000).")
    unit: Unit = Field(description="En qué viene volume.")
    peak_factor: float | None = Field(
        None,
        gt=0,
        le=1000,
        description="Multiplicador del pico del evento que dijo el usuario (ej. 20 en CyberDay ×20).",
    )
    scenario: str = Field("cyberday", pattern=r"^[a-z0-9_-]{1,60}$", description="Escenario del evento.")
    quote: str = Field(min_length=3, max_length=500, description="La frase textual del usuario con los números.")


class SetDeploymentArgs(VersionRef):
    field: Literal["api.replicas", "api.vcpu", "db.plan"]
    value: str = Field(description="El valor que dijo el usuario (ej. '3', '0.5', 'db.m7g.large').")
    quote: str = Field(min_length=3, max_length=500, description="La frase textual del usuario.")


class SubmitArchitectureArgs(ArchitectureSubmission):
    project_id: str | None = Field(
        None,
        description="Sin valor, crea un proyecto nuevo con esta arquitectura como v1. Con un project_id, guarda una "
        "versión nueva con esta arquitectura y conserva el despliegue, el tráfico y lo que dijo la IaC.",
    )
    name: str | None = Field(None, max_length=120, description="Nombre del proyecto nuevo. Por defecto, repo.")


class SetGoalsArgs(ProjectRef):
    slo_p95_ms: float | None = Field(None, gt=0, description="Meta de p95 en ms.")
    slo_error_rate: float | None = Field(None, ge=0, le=1, description="Meta de errores como fracción (1 % = 0.01).")
    budget_usd_month: float | None = Field(None, ge=0, description="Presupuesto mensual en US$.")
    quote: str = Field(min_length=3, max_length=500, description="La frase textual del usuario con las metas.")


class AttachmentRef(ProjectRef):
    attachment_id: str = Field(description="Id del adjunto (de list_attachments o del mensaje del usuario).")


class ReadLogArgs(AttachmentRef):
    start: int = Field(1, ge=1, description="Primera línea (1 = la primera del archivo).")
    lines: int = Field(200, ge=1, le=MAX_READ_LINES, description=f"Cuántas líneas, hasta {MAX_READ_LINES}.")


class GrepLogArgs(AttachmentRef):
    pattern: str = Field(min_length=1, max_length=200, description="Expresión regular (sintaxis de Python).")


class ApplyLogArgs(VersionRef):
    attachment_id: str = Field(description="Id del log del que sale el tráfico.")


# ---------- números dentro de la frase del usuario ----------

_NUM = re.compile(r"(\d[\d.,]*)\s*(k|mil|millones|millón|million|m)?\b", re.IGNORECASE)


def _numbers_in(quote: str) -> list[float]:
    """Los números de una frase en español o inglés: 100.000, 100,000, 1,5, 100k, 2 millones, 0.5, 300 ms."""
    out = []
    for raw, suffix in _NUM.findall(quote):
        raw = raw.rstrip(".,")
        candidates = set()
        for thousands, decimal in ((".", ","), (",", ".")):
            t = raw.replace(thousands, "").replace(decimal, ".")
            try:
                candidates.add(float(t))
            except ValueError:
                pass
        mult = {"k": 1e3, "mil": 1e3, "m": 1e6, "millones": 1e6, "millón": 1e6, "million": 1e6}.get(
            (suffix or "").lower(), 1
        )
        out += [c * mult for c in candidates]
    return out


def _require_in_quote(value: float, quote: str, what: str, *, also: tuple[float, ...] = ()) -> None:
    """``value`` (o una forma equivalente, como 1 % = 0.01) tiene que aparecer en la frase del usuario."""
    targets = (value, *also)
    for n in _numbers_in(quote):
        if any(abs(n - t) <= 1e-9 * max(1, abs(t)) for t in targets):
            return
    raise ToolError(
        f"{what} = {value:g} no aparece en quote ({quote!r}). Los números del usuario se copian de su frase: "
        "si no lo dijo, pregúntaselo en vez de suponerlo."
    )


# ---------- utilidades ----------


def _num(value: Any, unit: str, label: str, source: str, **extra: Any) -> dict[str, Any]:
    return {"value": value, "unit": unit, "label": label, "source": source, "date": date.today().isoformat(), **extra}


def _weakest(*labels: str) -> str:
    return max(labels, key=lambda lab: RANK.get(lab, 3))


def _provenance(model: dict[str, Any], run: Run) -> dict[str, Any]:
    supuestos = collect_assumptions(model)["total"]
    return {
        "label": "SUPUESTO" if supuestos else "ESTIMADO",
        "source": f"Motor de eventos discretos de Branchpoint: escenario {run.scenario}, semilla {run.seed}, "
        f"{run.rps:g} req/s, {run.duration_s:g} s simulados",
        "assumptions": supuestos,
    }


def _saturation_provenance(run: Run) -> dict[str, Any]:
    """De dónde sale "saturated" (JAJ-89): los umbrales los eligió el equipo. Viene en el propio Run, armado
    desde las constantes del motor, así no se desactualiza."""
    s = run.saturation
    return {"label": s.label, "source": s.source} if s is not None else {}


def _goal_check(
    goals: ProjectGoals, run: Run, monthly: float | None, missing: list[str] | None = None
) -> dict[str, Any] | None:
    """Si la versión cumple las metas del proyecto. ``missing``: componentes sin precio (JAJ-88), con los
    que el presupuesto no se puede evaluar."""
    if goals == ProjectGoals():
        return None
    out: dict[str, Any] = {}
    saturated = run.saturation is not None and run.saturation.saturated
    # JAJ-89: con el sistema saturado, error_rate no cuenta las requests que siguen en fila; para las
    # metas se usa el techo (si esas requests terminaran fallando), así una versión colapsada no cumple.
    error_rate = run.saturation.error_rate_if_unanswered_fail if saturated else run.error_rate
    # con qué tasa se juzgó, para que el agente pueda explicar un "no cumple" con 0 % de errores
    basis = (
        {
            "value": error_rate,
            "basis": "techo por saturación: error_rate más las requests sin respuesta al terminar (JAJ-89)",
            "error_rate": run.error_rate,
            # anidado: si va suelto, el label y el source del piso del 1 % (sin meta) lo pisarían
            "saturated_provenance": _saturation_provenance(run),
        }
        if saturated
        else {"value": error_rate, "basis": "error_rate"}
    )
    if goals.slo_p95_ms is not None:
        p95 = run.latency.p95_ms
        out["p95"] = {
            "goal_ms": goals.slo_p95_ms,
            "ok": p95 is not None and p95 <= goals.slo_p95_ms and not saturated,
        }
        if saturated:
            out["p95"]["basis"] = "no cumple por saturación: el p95 solo mide las requests que terminaron (JAJ-89)"
            out["p95"]["saturated_provenance"] = _saturation_provenance(run)
    if goals.slo_error_rate is not None:
        out["errors"] = {"goal": goals.slo_error_rate, "ok": error_rate <= goals.slo_error_rate, **basis}
    else:
        # El p95 solo mide las requests exitosas: una versión que rechaza casi todo puede tener un p95
        # bajísimo. Sin meta de errores del usuario, se exige un piso SUPUESTO y se dice.
        out["errors"] = {
            "goal": DEFAULT_ERROR_RATE,
            "ok": error_rate <= DEFAULT_ERROR_RATE,
            **basis,
            "label": "SUPUESTO",
            "source": f"Sin meta de errores del usuario se usa {DEFAULT_ERROR_RATE:.0%} como piso: el p95 solo mide "
            "las requests exitosas. Pregúntale al usuario cuántos errores acepta (set_goals slo_error_rate).",
        }
    if goals.budget_usd_month is not None and monthly is not None:
        if missing and monthly > goals.budget_usd_month:
            # JAJ-88: lo que falta solo puede sumar, así que si el parcial ya se pasa, no cumple
            out["budget"] = {
                "goal_usd_month": goals.budget_usd_month,
                "ok": False,
                "basis": f"no cumple: solo lo que tiene precio ya suma US${monthly:,.2f}/mes, y falta "
                f"{describe_missing(missing)}.",
            }
        elif missing:
            # JAJ-88: el total no incluye la API o la DB (en local o sin precio): no se puede decir que
            # cumple el presupuesto contando solo, por ejemplo, la caché
            out["budget"] = {
                "goal_usd_month": goals.budget_usd_month,
                "ok": None,
                "basis": f"no evaluable: el total (US${monthly:,.2f}/mes) no incluye {describe_missing(missing)}. "
                "Pregúntale al usuario dónde se desplegaría (set_deployment).",
            }
        else:
            out["budget"] = {"goal_usd_month": goals.budget_usd_month, "ok": monthly <= goals.budget_usd_month}
    checks = [v["ok"] for v in out.values() if isinstance(v, dict)]
    # None si nada falla pero algo no se pudo evaluar (el presupuesto sin precio, JAJ-88)
    out["meets_all"] = False if False in checks else (None if None in checks else True)
    return out


def _run_summary(run: Run, model: dict[str, Any]) -> dict[str, Any]:
    b = run.bottleneck
    return {
        "scenario": run.scenario,
        "rps": run.rps,
        "p95_ms": run.latency.p95_ms,
        "error_rate": round(run.error_rate, 4),
        "errors": run.errors,
        "throughput_rps": round(run.throughput_rps, 1),
        # JAJ-89: si quedaron requests sin respuesta, error_rate es un piso; el agente debe decirlo
        # (label y source del bloque son de "saturated"; los conteos salen del motor)
        "saturation": asdict(run.saturation) if run.saturation is not None else None,
        "bottleneck": {
            "resource": b.resource,
            "utilization": round(b.utilization, 3),
            "line": b.line,
            "endpoint": getattr(b, "endpoint", None),
            "message": b.message,
        },
        "warnings": run.warnings,
        "provenance": _provenance(model, run),
    }


def _version_label(v: Version) -> dict[str, Any]:
    return {"version": v.number, "origin": v.origin, "parent": v.parent, "note": v.note, "created_at": v.created_at}


# ---------- las tools ----------

TOOL_DESCRIPTIONS: dict[str, str] = {
    "list_projects": "Lista los proyectos del usuario con sus versiones. Empieza por aquí para obtener project_id.",
    "get_model": "Resumen de una versión: despliegue, tráfico, escenarios, endpoints con archivo:línea, metas y "
    "cuántos SUPUESTO tiene. No incluye el JSON completo.",
    "list_assumptions": "Los números SUPUESTO de una versión, con su fuente: lo que conviene preguntarle al usuario.",
    "list_scenarios": "Los escenarios del proyecto (pico_normal, cyberday...) y su tasa (× el pico o req/s fijas).",
    "simulate": "Simula una versión bajo un escenario del proyecto. Devuelve p95, errores, throughput, el cuello "
    "de botella con su archivo:línea, la procedencia y si cumple las metas (goals.meets_all: true, false, o null "
    "si nada falla pero algo no se pudo evaluar, como el presupuesto sin precio; dilo así). Si saturation.saturated "
    "es true, la tasa de error es un piso: dilo.",
    "compare": "Simula dos versiones con el mismo escenario y semilla. Devuelve el delta de p95, errores y costo "
    "mensual (sin los componentes de delta.usd_month_missing, que no tienen precio en alguna versión), las ventas "
    "en juego y si cada una cumple las metas (meets_all puede ser null: no evaluable).",
    "estimate_cost": "Costo mensual de una versión por componente, con la tabla de precios fechada. Si missing no "
    "está vacío, la API o la DB no tienen precio (en local o sin precios) y el total no las incluye: dilo, "
    "citando el primer aviso de warnings, y no presentes el total como el costo completo.",
    "ops_schema": "JSON Schema de las operaciones que acepta propose_version.",
    "propose_version": "Aplica operaciones de arquitectura (ops_schema) a una versión y guarda el resultado como "
    "versión nueva con origen agente. No simula: después usa compare.",
    "set_traffic": "Guarda el tráfico que dijo el usuario como versión nueva: calcula el pico en req/s con la "
    "fórmula de JAJ-45 y, con peak_factor, el escenario del evento. Los números tienen que estar en quote.",
    "set_deployment": "Cambia réplicas, vCPU o plan de DB con los valores que dijo el usuario (en quote), como "
    "versión nueva.",
    "set_goals": "Guarda las metas del proyecto (p95, errores, presupuesto) que dijo el usuario (en quote).",
    "list_attachments": "Los adjuntos vigentes del proyecto (imágenes y logs que subió el usuario), con id y tipo.",
    "read_log": f"Lee líneas de un log adjunto, numeradas, hasta {MAX_READ_LINES} por llamada y "
    f"{MAX_LINE_CHARS} caracteres por línea. Para ver el formato o un tramo; los números salen de analyze_log.",
    "grep_log": f"Busca una expresión regular en un log adjunto: hasta {MAX_GREP_MATCHES} líneas con su número.",
    "analyze_log": "Resume un log de acceso con código, sin LLM: pico y media de req/s, tasa de errores 5xx, p95 si "
    "el log trae duración, y el peso de cada endpoint del modelo. Todo OBSERVADO, con las líneas como fuente. "
    "Si no reconoce el formato, devuelve error con una muestra: lee con read_log y pregúntale al usuario.",
    "apply_log_traffic": "Crea una versión nueva con el tráfico observado en un log: el pico en req/s y el peso de "
    "cada endpoint que aparece en el log, todo OBSERVADO. Vuelve a analizar el log: no recibe números.",
    "submit_architecture": "Manda la arquitectura de un repo que leíste en local, de cualquier framework. Lista cada "
    "endpoint con sus pasos en orden (db, cache con on_miss, external, background, cpu), los trabajos de cola, los "
    "componentes (caché, colas, servicios externos, storage) y, si están escritos en el repo, los workers y el pool "
    "(observations). Todo con archivo:línea y why. No mandes tiempos, filas ni costos: el catálogo pone los números "
    "y todo queda ESTIMADO o SUPUESTO con procedencia IA.",
}


class AgentTools:
    """Las tools de un usuario. ``owner`` es su id (o ``None`` sin login); solo ve sus proyectos."""

    def __init__(
        self, store: ProjectStore, owner: str | None, limiter: Limiter | None = None, attachments: Any = None
    ) -> None:
        self.store = store
        self.owner = owner
        self.limiter = limiter or Limiter()
        self.attachments = attachments  # AttachmentStorage del chat (IA-7); None en MCP
        self._args = {
            "list_projects": ListProjects,
            "get_model": VersionRef,
            "list_assumptions": VersionRef,
            "list_scenarios": ProjectRef,
            "simulate": SimulateArgs,
            "compare": CompareArgs,
            "estimate_cost": VersionRef,
            "ops_schema": ListProjects,
            "propose_version": ProposeArgs,
            "set_traffic": SetTrafficArgs,
            "set_deployment": SetDeploymentArgs,
            "set_goals": SetGoalsArgs,
            "submit_architecture": SubmitArchitectureArgs,
        }
        if attachments is not None:
            self._args.update(
                list_attachments=ProjectRef,
                read_log=ReadLogArgs,
                grep_log=GrepLogArgs,
                analyze_log=AttachmentRef,
                apply_log_traffic=ApplyLogArgs,
            )

    # -- catálogo de tools (para MCP y para la API de Claude) --

    def schemas(self, *, cli: bool = True) -> list[dict[str, Any]]:
        """Las tools con su JSON Schema. ``cli=False`` (el chat del editor) deja fuera las que leen el repo."""
        return [
            {"name": name, "description": TOOL_DESCRIPTIONS[name], "input_schema": model.model_json_schema()}
            for name, model in self._args.items()
            if cli or name not in CLI_ONLY
        ]

    def validate(self, name: str, args: dict[str, Any] | None) -> BaseModel:
        if name not in self._args:
            raise ToolError(f"No existe la tool '{name}'. Hay: {', '.join(self._args)}.")
        try:
            return self._args[name].model_validate(args or {})
        except ValidationError as e:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'argumentos'}: {err['msg']}" for err in e.errors()
            )
            raise ToolError(f"Argumentos inválidos para {name}: {problems}") from None

    def call(self, name: str, args: dict[str, Any] | None = None) -> Any:
        """Ejecuta una tool. Nunca lanza: un error vuelve como ``{"error": ...}``."""
        try:
            parsed = self.validate(name, args)
            self.limiter.call(self.owner or "anon")
            return getattr(self, f"_{name}")(parsed)
        except ToolError as e:
            return {"error": str(e)}
        except ApiError as e:
            return {"error": e.message}
        except Exception as e:  # noqa: BLE001 - todo error llega al LLM con la misma forma
            return {"error": f"Error interno de Branchpoint ({type(e).__name__}): {e}"}

    # -- helpers --

    def _project(self, project_id: str) -> Project:
        project = self.store.get(project_id, self.owner)
        if project is None:
            raise ToolError(f"No existe el proyecto '{project_id}' (o no es tuyo). Usa list_projects.")
        return project

    def _version(self, project: Project, number: int | None) -> Version:
        n = number or len(project.versions)
        version = self.store.get_version(project.id, n) if project.version(n) else None
        if version is None or version.model is None:
            raise ToolError(f"El proyecto no tiene la versión v{n}. Tiene de v1 a v{len(project.versions)}.")
        return version

    def _params(self, project: Project, model: dict[str, Any], scenario: str, seed: int) -> RunParams:
        scenarios = {s.name: s for s in self.store.list_scenarios(project.id)}
        sc = scenarios.get(scenario)
        if sc is None:
            raise ToolError(f"El proyecto no tiene el escenario '{scenario}'. Hay: {', '.join(sorted(scenarios))}.")
        try:
            rate = sc.rate_for(model)
        except ValueError as e:
            raise ToolError(str(e)) from None
        # Con mucho tráfico, 60 s superan el tope de requests por llamada: el servidor acorta la duración
        # (con un piso de 5 s). La procedencia del resultado dice cuántos segundos se simularon.
        duration = max(MIN_SIM_SECONDS, min(SIM_SECONDS, 0.95 * MAX_SIMULATED_REQUESTS / rate))
        if rate * duration > MAX_SIMULATED_REQUESTS:
            raise ToolError(
                f"El escenario '{scenario}' pide {rate:,.0f} req/s: es más de lo que el motor simula en una llamada "
                f"({MAX_SIMULATED_REQUESTS:,} requests en {MIN_SIM_SECONDS:g} s). Revisa el tráfico declarado."
            )
        return RunParams(scenario=scenario, seed=seed, duration_s=round(duration, 1), rps=rate)

    def _run(self, project: Project, version: Version, scenario: str, seed: int) -> Run:
        params = self._params(project, version.model, scenario, seed)
        run, _ = cached_run(self.store, project.id, version.number, version.model, params, scenario)
        return run

    def _save(self, project: Project, base: Version, model: dict[str, Any], note: str) -> Version:
        model.pop("checks", None)  # las cotas de build_model eran del modelo original
        model["assumptions"] = collect_assumptions(model)
        try:
            load_model(model)
        except (ValueError, KeyError, TypeError) as e:
            raise ToolError(f"El modelo resultante no carga en el motor: {e}") from None
        return self.store.add_version(project.id, model, "agente", base.number, note[:500])

    # -- lectura --

    def _list_projects(self, _: ListProjects) -> dict[str, Any]:
        # un objeto y no una lista: MCP solo devuelve contenido estructurado para objetos
        return {
            "projects": [
                {
                    "project_id": p.id,
                    "name": p.name,
                    "versions": [_version_label(v) for v in p.versions],
                    "latest": len(p.versions),
                }
                for p in self.store.list(self.owner)
            ]
        }

    def _get_model(self, a: VersionRef) -> dict[str, Any]:
        project = self._project(a.project_id)
        version = self._version(project, a.version)
        m = version.model
        dep, traffic = m.get("deployment", {}), m.get("traffic", {})
        api, db = dep.get("api", {}), dep.get("db", {})

        def v(x: Any) -> Any:
            return x.get("value") if isinstance(x, dict) else x

        endpoints = sorted(m.get("endpoints", []), key=lambda e: -(v(e.get("weight")) or 0))
        return {
            **_version_label(version),
            "repo": m.get("repo", {}).get("path"),
            "deployment": {
                "api": {k: api.get(k) for k in ("provider", "replicas", "vcpu", "workers", "cpu_core_factor")},
                "db": {k: db.get(k) for k in ("provider", "plan", "vcpu", "max_connections", "cpu_core_factor")},
                "services": [
                    {k: s.get(k) for k in ("name", "role", "engine", "version", "at")} for s in dep.get("services", [])
                ],
            },
            "traffic": {"peak_rps": traffic.get("peak_rps"), "declared": traffic.get("declared")},
            "scenarios": self._list_scenarios(ProjectRef(project_id=project.id))["scenarios"],
            "endpoints": [
                {
                    "id": e.get("id"),
                    "at": e.get("at"),
                    "weight": round(v(e.get("weight")) or 0, 4),
                    "steps": [
                        {
                            "kind": s.get("kind"),
                            "shape": s.get("shape"),
                            "at": s.get("at"),
                            "repeat": v(s.get("repeat")),
                        }
                        for s in e.get("steps", [])
                    ],
                }
                for e in endpoints
            ],
            "goals": self.store.get_goals(project.id).__dict__,
            "assumptions": collect_assumptions(m)["total"],
        }

    def _list_assumptions(self, a: VersionRef) -> dict[str, Any]:
        version = self._version(self._project(a.project_id), a.version)
        found = collect_assumptions(version.model)
        return {"version": version.number, "total": found["total"], "by_source": found["by_source"][:40]}

    def _list_scenarios(self, a: ProjectRef) -> dict[str, Any]:
        self._project(a.project_id)
        return {
            "scenarios": [
                {"name": s.name, "multiplier": s.multiplier, "rps": s.rps, "description": s.description}
                for s in self.store.list_scenarios(a.project_id)
            ]
        }

    def _ops_schema(self, _: ListProjects) -> dict[str, Any]:
        return ops_json_schema()

    def _estimate_cost(self, a: VersionRef) -> dict[str, Any]:
        version = self._version(self._project(a.project_id), a.version)
        cost = estimate_cost(version.model)
        return {
            "version": version.number,
            "total": cost.total,
            "lines": [line.__dict__ if hasattr(line, "__dict__") else line for line in cost.lines],
            "unpriced": cost.unpriced,
            "warnings": cost.warnings,
        }

    # -- simular --

    def _simulate(self, a: SimulateArgs) -> dict[str, Any]:
        project = self._project(a.project_id)
        version = self._version(project, a.version)
        self.limiter.simulations(self.owner or "anon", 1)
        from app.api.routes.reports import simulate_and_report  # cada simulación deja su reporte (JAJ-127)

        params = self._params(project, version.model, a.scenario, a.seed)
        run, report = simulate_and_report(self.store, project, version, params, custom_rps=False)
        cost = estimate_cost(version.model)
        return {
            "version": version.number,
            "report_id": report["id"],
            **_run_summary(run, version.model),
            "goals": _goal_check(self.store.get_goals(project.id), run, cost.total["value"], cost.missing),
        }

    def _compare(self, a: CompareArgs) -> dict[str, Any]:
        from app.api.routes.projects import compare_summary  # el mismo texto que ve el editor

        project = self._project(a.project_id)
        va, vb = self._version(project, a.a), self._version(project, a.b)
        self.limiter.simulations(self.owner or "anon", 2)
        run_a, run_b = self._run(project, va, a.scenario, a.seed), self._run(project, vb, a.scenario, a.seed)
        cost_a, cost_b = estimate_cost(va.model), estimate_cost(vb.model)
        cdelta = cost_delta(cost_a, cost_b)
        fa, fb = failure_cost(va.model, run_a), failure_cost(vb.model, run_b)
        d = run_delta(run_a, run_b, va.model, vb.model)
        goals = self.store.get_goals(project.id)
        return {
            "a": {
                "version": va.number,
                **_run_summary(run_a, va.model),
                "usd_month": cost_a.total,
                "goals": _goal_check(goals, run_a, cost_a.total["value"], cost_a.missing),
            },
            "b": {
                "version": vb.number,
                **_run_summary(run_b, vb.model),
                "usd_month": cost_b.total,
                "goals": _goal_check(goals, run_b, cost_b.total["value"], cost_b.missing),
            },
            "delta": {
                "p95_ms": {"a": d.p95_ms.a, "b": d.p95_ms.b, "pct": d.p95_ms.pct},
                "error_rate": {"a": d.error_rate.a, "b": d.error_rate.b},
                "throughput_rps": {"a": d.throughput_rps.a, "b": d.throughput_rps.b},
                "usd_month": cdelta.diff,
                # JAJ-88: componentes sin precio en alguna versión; usd_month no los cuenta
                "usd_month_missing": cdelta.missing,
                "bottleneck_changed": d.bottleneck_changed,
            },
            "summary": compare_summary(va.number, vb.number, cdelta, fa, fb, run_a, run_b),
        }

    # -- escribir --

    def _propose_version(self, a: ProposeArgs) -> dict[str, Any]:
        project = self._project(a.project_id)
        base = self._version(project, a.version)
        try:
            result = apply_ops(base.model, a.ops)
        except OpError as e:
            raise ToolError(str(e)) from None
        version = self.store.add_version(
            project.id, result.model, "agente", base.number, (a.note or "; ".join(result.changes))[:500]
        )
        return {
            "version": version.number,
            "parent": base.number,
            "changes": result.changes,
            "warnings": result.warnings,
        }

    def _set_traffic(self, a: SetTrafficArgs) -> dict[str, Any]:
        project = self._project(a.project_id)
        base = self._version(project, a.version)
        _require_in_quote(a.volume, a.quote, "volume")
        if a.peak_factor is not None:
            _require_in_quote(a.peak_factor, a.quote, "peak_factor")
        m = copy.deepcopy(base.model)
        traffic = m.setdefault("traffic", {})
        catalog = load_catalog()["traffic"]
        quote_src = f"Declarado por el usuario: «{a.quote}»"
        volume = _num(a.volume, a.unit, "SUPUESTO", quote_src)
        k_hour = traffic.get("k_hour") or _num(
            catalog["k_hour"]["value"], "×", catalog["k_hour"]["label"], catalog["k_hour"]["source"]
        )
        parts = [volume]
        if a.unit == "requests_per_second_peak":
            peak, formula = a.volume, "req/s pico declaradas"
        elif a.unit == "requests_per_day":
            peak = a.volume / SECONDS_DAY * k_hour["value"]
            formula = "requests/día / 86.400 × K_hora"
            parts.append(k_hour)
        elif a.unit == "orders_per_day":
            conversion = (m.get("business") or {}).get("conversion")
            rps_session = traffic.get("requests_per_session")
            if not conversion or not rps_session:
                raise ToolError(
                    "El modelo no tiene business.conversion o traffic.requests_per_session para pasar pedidos a requests."
                )
            sessions = a.volume / conversion["value"]
            peak = sessions * rps_session["value"] / SECONDS_DAY * k_hour["value"]
            formula = "pedidos/día / conversión × requests/sesión / 86.400 × K_hora (JAJ-11)"
            parts += [conversion, rps_session, k_hour]
        else:  # users_per_month
            profile = traffic.get("profile") or {}
            spm, rps_session = profile.get("sessions_per_month"), traffic.get("requests_per_session")
            if not spm or not rps_session:
                raise ToolError(
                    "El modelo no tiene el perfil de uso (sesiones/mes y requests/sesión) para pasar usuarios a req/s."
                )
            peak = a.volume * spm * rps_session["value"] / SECONDS_MONTH * k_hour["value"]
            formula = "usuarios/mes × sesiones/mes × requests/sesión / segundos del mes × K_hora (JAJ-45)"
            parts += [rps_session, k_hour]
        label = _weakest(*(p.get("label", "SUPUESTO") for p in parts))
        traffic["declared"] = {"volume": volume, "quote": a.quote}
        traffic["peak_rps"] = _num(round(peak, 2), "req/s", label, f"{formula}. {quote_src}", derived=True)
        changes = [f"Tráfico: {a.volume:g} {a.unit} → pico de {peak:,.1f} req/s ({formula})"]
        if a.peak_factor is not None:
            mult = _num(a.peak_factor, "×", "SUPUESTO", quote_src)
            sc = traffic.setdefault("scenarios", {})
            sc[a.scenario] = {
                "multiplier": mult,
                "rps": _num(round(peak * a.peak_factor, 2), "req/s", label, "pico × multiplicador", derived=True),
            }
            self.store.upsert_scenario(project.id, ProjectScenario(a.scenario, a.peak_factor, None, a.quote))
            changes.append(f"Escenario {a.scenario}: ×{a.peak_factor:g} = {peak * a.peak_factor:,.1f} req/s")
        version = self._save(project, base, m, "; ".join(changes))
        return {"version": version.number, "parent": base.number, "changes": changes, "peak_rps": traffic["peak_rps"]}

    def _set_deployment(self, a: SetDeploymentArgs) -> dict[str, Any]:
        project = self._project(a.project_id)
        base = self._version(project, a.version)
        if a.field == "db.plan":
            if a.value.lower() not in a.quote.lower():
                raise ToolError(f"El plan '{a.value}' no aparece en quote ({a.quote!r}).")
            ops = [{"op": "change_db_plan", "plan": a.value}]
        else:
            try:
                number = float(a.value.replace(",", "."))
            except ValueError:
                raise ToolError(f"{a.field} tiene que ser un número (llegó {a.value!r}).") from None
            _require_in_quote(number, a.quote, a.field)
            api = base.model.get("deployment", {}).get("api", {})
            replicas = int(number) if a.field == "api.replicas" else int(api.get("replicas", {}).get("value", 1))
            op: dict[str, Any] = {"op": "scale_api", "replicas": replicas, "quote": a.quote}
            if a.field == "api.vcpu":
                op["vcpu"] = number
            ops = [op]
        try:
            result = apply_ops(base.model, ops)
        except OpError as e:
            raise ToolError(str(e)) from None
        version = self.store.add_version(
            project.id, result.model, "agente", base.number, "; ".join(result.changes)[:500]
        )
        return {
            "version": version.number,
            "parent": base.number,
            "changes": result.changes,
            "warnings": result.warnings,
        }

    def _submit_architecture(self, a: SubmitArchitectureArgs) -> dict[str, Any]:
        self.limiter.daily(self.owner or "anon", DAILY_SUBMISSIONS, "arquitecturas enviadas")
        sub = ArchitectureSubmission.model_validate(a.model_dump(exclude={"project_id", "name"}))
        note = f"Arquitectura propuesta por la IA del usuario ({sub.framework}, {sub.language})"
        if a.project_id is None:
            model = build_from_ai(sub)
            try:
                load_model(model)
            except (ValueError, KeyError, TypeError) as e:
                raise ToolError(f"La arquitectura no carga en el motor: {e}") from None
            project = self.store.create(a.name or sub.repo, model, None, owner=self.owner)
            version = self.store.get_version(project.id, 1)
        else:
            project = self._project(a.project_id)
            base = self._version(project, None)
            version = self._save(project, base, replace_architecture(base.model, sub), note)
        saved = version.model
        ai_eps = [ep for ep in saved["endpoints"] if ep.get("origin")]
        return {
            "project_id": project.id,
            "version": version.number,
            "endpoints": len(saved["endpoints"]),
            "endpoints_from_ai": len(ai_eps),
            "components_from_ai": sum(1 for s in saved["deployment"].get("services", []) if s.get("origin")),
            "assumptions": saved.get("assumptions", {}).get("total"),
            "provenance": {
                "label": "ESTIMADO",
                "source": f"{note}. Los tiempos salen del catálogo; la CPU base del framework y el despliegue "
                "quedan SUPUESTO hasta que el usuario los confirme.",
            },
            "next": "Pregúntale al usuario el tráfico (set_traffic) y el despliegue (set_deployment), y simula.",
        }

    def _set_goals(self, a: SetGoalsArgs) -> dict[str, Any]:
        project = self._project(a.project_id)
        if a.slo_p95_ms is None and a.slo_error_rate is None and a.budget_usd_month is None:
            raise ToolError("Manda al menos una meta: slo_p95_ms, slo_error_rate o budget_usd_month.")
        if a.slo_p95_ms is not None:
            _require_in_quote(a.slo_p95_ms, a.quote, "slo_p95_ms", also=(a.slo_p95_ms / 1000,))  # 300 ms o 0,3 s
        if a.slo_error_rate is not None:
            _require_in_quote(a.slo_error_rate, a.quote, "slo_error_rate", also=(a.slo_error_rate * 100,))  # 1 %
        if a.budget_usd_month is not None:
            _require_in_quote(a.budget_usd_month, a.quote, "budget_usd_month")
        current = self.store.get_goals(project.id)
        goals = replace(
            current,
            **{
                k: getattr(a, k)
                for k in ("slo_p95_ms", "slo_error_rate", "budget_usd_month")
                if getattr(a, k) is not None
            },
        )
        saved = self.store.set_goals(project.id, goals)
        return {"goals": saved.__dict__, "source": f"Declarado por el usuario: «{a.quote}»"}

    # -- adjuntos del chat (IA-7) --

    def _log(self, project_id: str, attachment_id: str) -> tuple[Any, bytes]:
        if self.attachments is None or self.owner is None:
            raise ToolError("Los adjuntos requieren sesión en el editor.")
        self._project(project_id)
        a = self.store.get_attachment(attachment_id, self.owner)
        if a is None or a.project_id != project_id or a.status != "ready" or a.expired():
            raise ToolError(f"No existe el adjunto '{attachment_id}' (o venció). Usa list_attachments.")
        if a.kind != "log":
            raise ToolError(f"'{a.filename}' es una imagen: no se lee como log. Ya la viste en el mensaje del usuario.")
        try:
            return a, self.attachments.download(a.storage_path, MAX_LOG_BYTES)
        except StorageError as e:
            raise ToolError(f"No pude leer el adjunto: {e}") from None

    def _list_attachments(self, a: ProjectRef) -> dict[str, Any]:
        if self.owner is None:
            raise ToolError("Los adjuntos requieren sesión en el editor.")
        self._project(a.project_id)
        return {
            "attachments": [
                {"id": x.id, "kind": x.kind, "filename": x.filename, "bytes": x.bytes}
                for x in self.store.list_attachments(a.project_id, self.owner)
            ]
        }

    def _read_log(self, a: ReadLogArgs) -> dict[str, Any]:
        att, data = self._log(a.project_id, a.attachment_id)
        out, total = [], 0
        for n, raw in enumerate(data.splitlines(), 1):
            total = n
            if a.start <= n < a.start + a.lines:
                out.append(f"{n}: {raw.decode('utf-8', errors='replace')[:MAX_LINE_CHARS]}")
        return {"filename": att.filename, "total_lines": total, "lines": out}

    def _grep_log(self, a: GrepLogArgs) -> dict[str, Any]:
        att, data = self._log(a.project_id, a.attachment_id)
        try:
            rx = re.compile(a.pattern)
        except re.error as e:
            raise ToolError(f"La expresión regular no es válida: {e}") from None
        hits = []
        for n, raw in enumerate(data.splitlines(), 1):
            line = raw.decode("utf-8", errors="replace")
            if rx.search(line):
                hits.append(f"{n}: {line[:MAX_LINE_CHARS]}")
                if len(hits) >= MAX_GREP_MATCHES:
                    break
        return {"filename": att.filename, "matches": hits, "truncated": len(hits) >= MAX_GREP_MATCHES}

    def _summarize_log(self, project: Project, model: dict[str, Any], attachment_id: str) -> tuple[Any, dict]:
        att, data = self._log(project.id, attachment_id)
        return att, analyze_log(data, att.filename, [e["id"] for e in model["endpoints"]])

    def _analyze_log(self, a: AttachmentRef) -> dict[str, Any]:
        project = self._project(a.project_id)
        _, summary = self._summarize_log(project, self._version(project, None).model, a.attachment_id)
        return summary

    def _apply_log_traffic(self, a: ApplyLogArgs) -> dict[str, Any]:
        project = self._project(a.project_id)
        base = self._version(project, a.version)
        att, summary = self._summarize_log(project, base.model, a.attachment_id)  # no confía en números del LLM
        if "error" in summary:
            raise ToolError(summary["error"])
        if "peak_rps" not in summary:
            raise ToolError(f"{summary.get('note', 'El log no trae la hora de cada request')} No cambié el tráfico.")
        m = copy.deepcopy(base.model)
        traffic = m.setdefault("traffic", {})
        peak = summary["peak_rps"]
        traffic["peak_rps"] = {**peak, "date": date.today().isoformat()}
        for sc in (traffic.get("scenarios") or {}).values():
            mult = (sc.get("multiplier") or {}).get("value")
            if mult:
                sc["rps"] = _num(
                    round(peak["value"] * mult, 2), "req/s", "OBSERVADO", "pico × multiplicador", derived=True
                )
        observed = {e["id"]: e["weight"] for e in summary["endpoints"]}
        weights = {e["id"]: observed.get(e["id"], value_of(e.get("weight"))) for e in m["endpoints"]}
        total = sum(w for w in weights.values() if w) or 1.0
        source = summary["source"]
        for e in m["endpoints"]:
            w = (weights[e["id"]] or 0.0) / total
            if e["id"] in observed:
                e["weight"] = _num(round(w, 4), "fracción", "OBSERVADO", f"{source}: requests del endpoint / requests")
            elif isinstance(e.get("weight"), dict):
                e["weight"] = {**e["weight"], "value": round(w, 4)}
        note = f"Tráfico observado en {att.filename}"
        version = self._save(project, base, m, note)
        changes = [f"Pico: {peak['value']:g} req/s ({source})", f"{len(observed)} endpoints con peso observado"]
        missing = [e["id"] for e in m["endpoints"] if e["id"] not in observed]
        return {
            "version": version.number,
            "parent": base.number,
            "note": note,
            "changes": changes,
            "peak_rps": traffic["peak_rps"],
            "endpoints_not_in_log": missing[:40],
        }


def value_of(x: Any) -> float | None:
    v = x.get("value") if isinstance(x, dict) else x
    return float(v) if isinstance(v, (int, float)) else None


# ---------- evidencia que falta (IA-7) ----------

_EVIDENCE_ASKS = {
    "traffic.peak_rps": ("log de acceso o captura de requests por segundo", ["log", "image"]),
    "endpoints[].weight": ("log de acceso con las rutas, para saber cuánto pesa cada endpoint", ["log"]),
    "steps.external.time": ("log o captura con la latencia de los servicios externos", ["log", "image"]),
    "steps.cache.hit_ratio": ("captura de las métricas de la caché (tasa de aciertos)", ["image", "log"]),
}


def _review(x: Any) -> bool:
    return isinstance(x, dict) and x.get("label") != "OBSERVADO" and bool(x.get("needs_review"))


def pending_evidence(model: dict[str, Any]) -> dict[str, Any]:
    """Qué evidencia falta, sin LLM: a lo más cuatro pedidos sobre los supuestos por revisar del modelo."""
    traffic = model.get("traffic") or {}
    peak = traffic.get("peak_rps")
    steps = [s for e in model.get("endpoints", []) for s in e.get("steps", [])]
    flags = {
        "traffic.peak_rps": peak is None or _review(peak),
        "endpoints[].weight": any(_review(e.get("weight")) for e in model.get("endpoints", [])),
        "steps.external.time": any(s.get("kind") == "external" and _review(s.get("time")) for s in steps),
        "steps.cache.hit_ratio": any(
            s.get("kind") == "cache" and "on_miss" in s and (s.get("hit_ratio") is None or _review(s["hit_ratio"]))
            for s in steps
        ),
    }
    pending = [
        {"field": field, "ask": ask, "accepts": accepts}
        for field, (ask, accepts) in _EVIDENCE_ASKS.items()
        if flags[field]
    ]
    return {"pending": pending, "total_assumptions": collect_assumptions(model)["total"]}
