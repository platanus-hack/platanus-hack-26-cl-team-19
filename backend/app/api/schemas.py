"""Lo que recibe y devuelve la API. La respuesta de ``POST /runs`` es el ``Run`` de ``app.models.run``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.costs import CostDelta, CostEstimate, FailureCost
from app.models.compare import RunDelta
from app.models.run import Run

# Tope de requests simuladas por llamada (tasa × duración), para que una request no bloquee el
# servidor. CyberDay ×20 en 60 s son ~16.000; 300.000 tardan unos pocos segundos.
MAX_SIMULATED_REQUESTS = 300_000


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


class ProjectDetail(BaseModel):
    id: str
    name: str
    sample: str | None
    created_at: str
    versions: list[VersionSummary]


Region = Literal["us-east-1", "sa-east-1"]  # regiones con precios de AWS en el snapshot de JAJ-11


class CompareRequest(RunParams):
    a: int = Field(ge=1, description="Versión base (ej. 1).")
    b: int = Field(ge=1, description="Versión a comparar contra la base.")
    region: Region = Field("us-east-1", description="Región de AWS para los costos (JAJ-72).")


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
    summary: str | None = Field(None, description="La comparación en una frase: costo extra y ventas que se evitan.")


class CostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: dict[str, Any] = Field(description="Modelo branchpoint.model/v1 completo.")
    region: Region = Field("us-east-1", description="Región de AWS donde corre la infraestructura.")
