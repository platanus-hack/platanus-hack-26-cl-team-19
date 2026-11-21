"""Lo que recibe y devuelve la API. La respuesta de ``POST /runs`` es el ``Run`` de ``app.models.run``."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.costs import CostDelta, CostEstimate, FailureCost
from app.models.compare import RunDelta
from app.models.run import Run
from app.models.traffic import TrafficProfile, TrafficSegment, preset

# Tope de requests simuladas por llamada (tasa × duración, o tasa × duración × multiplicador medio
# con perfil), para que una request no bloquee el servidor. CyberDay ×20 en 60 s son ~16.000;
# 300.000 tardan unos pocos segundos.
MAX_SIMULATED_REQUESTS = 300_000


class TrafficSegmentIn(BaseModel):
    """Un tramo del perfil de tráfico: va linealmente de from_multiplier a to_multiplier × la tasa base."""

    model_config = ConfigDict(extra="forbid")

    duration_s: float = Field(gt=0, le=3600, description="Segundos que dura el tramo.")
    from_multiplier: float = Field(ge=0, le=100, description="Multiplicador de la tasa al inicio del tramo.")
    to_multiplier: float = Field(ge=0, le=100, description="Multiplicador de la tasa al final del tramo.")


class ScenarioBusiness(BaseModel):
    """Datos de negocio de un escenario (JAJ-131), para el costo de fallar de esa corrida (JAJ-74)."""

    model_config = ConfigDict(extra="forbid")

    conversion: float | None = Field(None, gt=0, le=1, description="Fracción de sesiones que compran. Ej. 0.03.")
    ticket_usd: float | None = Field(None, gt=0, description="Ticket promedio en US$. Ej. 40.")


class RunParams(BaseModel):
    """Cómo simular: escenario, semilla, duración y reemplazos. Sirve para cualquier modelo."""

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field("cyberday", description="Escenario del modelo (traffic.scenarios).")
    rps: float | None = Field(
        None, gt=0, description="Reemplaza las req/s del escenario. Con rps, el escenario es solo un nombre."
    )
    seed: int = Field(0, description="Misma semilla = mismo resultado.")
    duration_s: float = Field(60.0, gt=0, le=3600, description="Segundos simulados.")
    arrivals: Literal["poisson", "uniform"] = Field(
        "poisson", description="poisson: usuarios reales. uniform: tasa constante, como k6."
    )
    client_timeout_s: float | None = Field(
        30.0, gt=0, description="Timeout del cliente en segundos; null = sin timeout."
    )
    cache_hit_ratio: float | None = Field(
        None, ge=0, le=1, description="Reemplaza la tasa de aciertos de todas las cachés con on_miss."
    )
    cpu_credits: Literal["sustained", "burst"] = Field(
        "sustained",
        description=(
            "DB con créditos de CPU (db.t4g.*): sustained simula sus vCPU sostenidos (la base de créditos con "
            "carga sostenida); burst, todos sus vCPU (solo mientras duren los créditos o pagando el exceso)."
        ),
    )
    traffic_profile: list[TrafficSegmentIn] | Literal["pico"] | None = Field(
        None,
        description=(
            "Tasa que cambia en el tiempo (JAJ-71). 'pico': subida, meseta y bajada en duration_s. Una lista de "
            "tramos: la duración es la suma de los tramos y duration_s no se usa. Sin él, tasa constante."
        ),
    )
    # JAJ-131: reemplazos del escenario. Cambian la situación, no la arquitectura: solo esta corrida, sin
    # crear versión. Sin ellos se usan los del escenario del proyecto, si los tiene.
    endpoint_weights: dict[str, Annotated[float, Field(ge=0)]] | None = Field(
        None,
        description=(
            "Mezcla de endpoints: peso por id de endpoint (ej. {'POST /checkout': 3}). Los que no aparecen "
            "conservan su peso; se normaliza como siempre."
        ),
    )
    slowdowns: dict[str, Annotated[float, Field(gt=0, le=100)]] | None = Field(
        None,
        description=(
            "Dependencias más lentas: multiplicador del tiempo de los pasos de un nodo del grafo (POST /graph): "
            "db, cache, external o external:<servicio>. Ej. {'external:pagos': 10, 'db': 1.5}."
        ),
    )
    business: ScenarioBusiness | None = Field(
        None, description="Conversión y ticket promedio para el costo de fallar de esta corrida."
    )

    def override_args(self) -> dict[str, Any]:
        """Los reemplazos del escenario para ``apply_overrides`` (JAJ-131)."""
        return {
            "endpoint_weights": self.endpoint_weights,
            "slowdowns": self.slowdowns,
            "business": self.business.model_dump(exclude_none=True) if self.business else None,
        }

    def build_profile(self) -> TrafficProfile | None:
        if self.traffic_profile is None:
            return None
        if self.traffic_profile == "pico":
            return preset("pico", self.duration_s)
        return TrafficProfile(
            tuple(TrafficSegment(s.duration_s, s.from_multiplier, s.to_multiplier) for s in self.traffic_profile)
        )


class RunRequest(RunParams):
    model: dict[str, Any] = Field(
        description="Modelo branchpoint.model/v1 completo (la salida de build_model.py, JAJ-45)."
    )


class GraphRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: dict[str, Any] = Field(description="Modelo branchpoint.model/v1 completo.")


class ModelSummary(BaseModel):
    id: str = Field(description="Id del modelo de ejemplo, para GET /models/{id} y POST /projects.")
    name: str = Field(description="Repo del que salió el modelo.")
    extracted_at: str | None
    api_provider: str | None
    db_provider: str | None
    db_plan: str | None
    endpoints: int
    scenarios: dict[str, float] = Field(description="req/s de cada escenario.")
    mau: float | None = Field(description="Usuarios activos al mes declarados.")


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, description="Nombre para mostrar. Por defecto, el del repo.")
    sample: str | None = Field(None, description="Id de un modelo de ejemplo (GET /models).")
    model: dict[str, Any] | None = Field(None, description="O un modelo branchpoint.model/v1 propio.")


class CreateVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: dict[str, Any] = Field(description="El modelo editado, completo.")
    origin: Literal["repo", "manual", "agente"] = Field(
        "manual",
        description="repo: re-sincronizado desde una rama. manual: desde el diagrama. agente: propuesta aplicada.",
    )
    parent: int | None = Field(None, ge=1, description="Versión antecesora. Por defecto, la última.")
    note: str | None = Field(None, max_length=500, description="Qué cambió, para el historial.")


class ApplyOpsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ops: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=20,
        description=(
            "Operaciones en orden: scale_api, change_db_plan, add_pooler, add_cache, move_to_queue "
            "(ver app/agent/ops.py)."
        ),
    )
    note: str | None = Field(None, max_length=500, description="Por qué se propone. Por defecto, los cambios.")


class VersionSummary(BaseModel):
    number: int
    label: str = Field(description="v1, v2, ...")
    origin: Literal["repo", "manual", "agente"]
    parent: int | None
    note: str | None
    created_at: str


class VersionDetail(VersionSummary):
    model: dict[str, Any]


class OpsVersionDetail(VersionDetail):
    changes: list[str] = Field(description="Una línea por operación aplicada.")
    warnings: list[str] = Field(description="Lo que el agente debería decirle al usuario o preguntarle.")


class ProjectRepository(BaseModel):
    """Un repo del proyecto, como lo lee "Mis proyectos" (JAJ-92).

    Las claves siguen el tipo ``ProjectRepository`` del editor (``fullName`` en camelCase). ``id`` es
    el **id del proyecto** que abre ese repo: el editor lo usa para abrir el proyecto con
    ``GET /projects/{id}``. Hoy cada proyecto tiene un solo repo, así que es el mismo proyecto.
    """

    id: str = Field(description="Id del proyecto que abre este repo (hoy, el mismo proyecto).")
    full_name: str = Field(serialization_alias="fullName", description='"owner/nombre" en GitHub.')
    branch: str | None = Field(None, description="Rama analizada para la v1.")
    primary: bool = Field(True, description="El repo que simula el motor (IA-5). Va primero en la lista.")


class ProjectDetail(BaseModel):
    id: str
    name: str
    sample: str | None
    created_at: str
    versions: list[VersionSummary]
    repositories: list[ProjectRepository] | None = Field(
        None,
        description="Los repos de los que salió la v1, el principal primero (JAJ-92, IA-5). null si el proyecto "
        "salió de un ejemplo o de un modelo subido a mano: así el editor usa su fallback (el nombre del proyecto).",
    )


class ScenarioIn(BaseModel):
    """Body de ``PUT /projects/{id}/scenarios/{name}`` (JAJ-76): una de las dos tasas."""

    model_config = ConfigDict(extra="forbid")

    multiplier: float | None = Field(
        None, gt=0, le=1000, description="× el pico del modelo de cada versión (traffic.peak_rps). Ej. 20."
    )
    rps: float | None = Field(None, gt=0, description="O req/s fijas, iguales en todas las versiones.")
    description: str | None = Field(None, max_length=500, description="La situación en palabras del usuario.")
    # JAJ-131: los reemplazos que trae el escenario (los mismos campos de RunParams)
    endpoint_weights: dict[str, Annotated[float, Field(ge=0)]] | None = None
    slowdowns: dict[str, Annotated[float, Field(gt=0, le=100)]] | None = None
    business: ScenarioBusiness | None = None


class ScenarioOut(BaseModel):
    name: str
    multiplier: float | None
    rps: float | None
    description: str | None
    endpoint_weights: dict[str, float] | None = None
    slowdowns: dict[str, float] | None = None
    business: ScenarioBusiness | None = None


Region = Literal["us-east-1", "sa-east-1"]  # regiones con precios de AWS en el snapshot de JAJ-11


class CompareRequest(RunParams):
    a: int = Field(ge=1, description="Versión base (ej. 1).")
    b: int = Field(ge=1, description="Versión a comparar contra la base.")
    region: Region = Field("us-east-1", description="Región de AWS para los costos (JAJ-72).")


class VersionResultsRequest(RunParams):
    """Body de ``POST /projects/{id}/versions/{n}/results`` (JAJ-128): los de ``runs`` más la región."""

    region: Region = Field("us-east-1", description="Región de AWS para los costos (JAJ-72).")


class VersionResults(BaseModel):
    """Todo lo que hace falta para leer el resultado de una versión, en una llamada (JAJ-128): la
    simulación, el costo mensual con su desglose y el costo de fallar."""

    version: VersionSummary
    run: Run
    # costo mensual en US$ (las unidades vienen en cada número), por componente, con región, fuente y
    # procedencia. ``cost.missing`` dice qué componentes no tienen precio: el total es parcial (JAJ-88)
    cost: CostEstimate
    # ventas en juego por hora según la tasa de error del Run (JAJ-74); None sin datos de negocio
    failure: FailureCost | None = None
    failure_missing: list[str] = Field(
        default_factory=list, description="Si failure es null, los datos que le faltan al modelo para calcularlo."
    )
    summary: str = Field(description="El resultado en una o dos frases, para mostrar tal cual.")


class CompareResponse(BaseModel):
    a: VersionSummary
    b: VersionSummary
    run_a: Run
    run_b: Run
    delta: RunDelta
    # JAJ-72: costo mensual de cada versión y la diferencia, por componente
    cost_a: CostEstimate
    cost_b: CostEstimate
    cost_delta: CostDelta
    # JAJ-74: ventas en juego por hora de cada versión, según su tasa de error (None si el modelo
    # no trae conversión, ticket o requests por sesión)
    failure_a: FailureCost | None = None
    failure_b: FailureCost | None = None
    # JAJ-128: si failure_x es None, qué datos de negocio le faltan a ese modelo (ej. business.conversion)
    failure_missing_a: list[str] = Field(default_factory=list)
    failure_missing_b: list[str] = Field(default_factory=list)
    summary: str | None = Field(None, description="La comparación en una frase: costo extra y ventas que se evitan.")


class CostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: dict[str, Any] = Field(description="Modelo branchpoint.model/v1 completo.")
    region: Region = Field("us-east-1", description="Región de AWS donde corre la infraestructura.")
