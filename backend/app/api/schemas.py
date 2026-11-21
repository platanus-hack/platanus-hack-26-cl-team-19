"""Lo que recibe la API. La respuesta de ``POST /runs`` es el ``Run`` de ``app.models.run``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Tope de requests simuladas por llamada (tasa × duración), para que una request no bloquee el
# servidor. CyberDay ×20 en 60 s son ~16.000; 300.000 tardan unos pocos segundos.
MAX_SIMULATED_REQUESTS = 300_000


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: dict[str, Any] = Field(
        description="Modelo branchpoint.model/v1 completo (la salida de build_model.py, JAJ-45)."
    )
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
