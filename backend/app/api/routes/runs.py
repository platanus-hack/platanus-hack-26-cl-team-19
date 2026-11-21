"""``POST /runs``: simula un modelo bajo un escenario y devuelve el ``Run`` completo.

No guarda nada, porque el modelo no tiene versión: cada llamada simula de nuevo. Los runs de una
versión de un proyecto sí se guardan (``app/api/run_cache.py``, JAJ-75). Con 60 s simulados en
~200 ms, una respuesta completa alcanza para el MVP (el streaming es JAJ-20).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.errors import INVALID_MODEL, INVALID_PARAMETERS, RUN_TOO_LARGE, UNKNOWN_SCENARIO, ApiError
from app.api.schemas import MAX_SIMULATED_REQUESTS, RunParams, RunRequest
from app.engine import simulate
from app.models import load_model
from app.models.architecture import ArchitectureModel
from app.models.run import Run

router = APIRouter(tags=["runs"])


# `def` y no `async def`: la simulación usa CPU, así que FastAPI la corre en su pool de hilos y no
# bloquea las demás requests mientras simula.
@router.post("/runs", response_model=Run, summary="Simular un modelo bajo un escenario")
def create_run(req: RunRequest) -> Run:
    return run_model(req.model, req)


def run_model(raw: dict, req: RunParams) -> Run:
    """Valida el modelo y los parámetros y simula. Lo usan ``POST /runs`` y las rutas de proyectos."""
    model = load_or_422(raw)
    if req.rps is None and req.scenario not in model.scenarios:
        available = sorted(model.scenarios)
        raise ApiError(
            422,
            UNKNOWN_SCENARIO,
            f"El modelo no tiene el escenario '{req.scenario}'. "
            + (f"Hay: {', '.join(available)}." if available else "No tiene ninguno: manda rps."),
            available=available,
        )
    rate = req.rps if req.rps is not None else model.scenario(req.scenario).rps
    try:
        profile = req.build_profile()
    except ValueError as e:  # ej. un perfil con multiplicador 0 en todos los tramos
        raise ApiError(422, INVALID_PARAMETERS, str(e)) from e
    duration = profile.duration_s if profile else req.duration_s
    expected = rate * duration * (profile.mean if profile else 1.0)
    if expected > MAX_SIMULATED_REQUESTS:
        raise ApiError(
            422,
            RUN_TOO_LARGE,
            f"{rate:g} req/s durante {duration:g} s son {expected:,.0f} requests; "
            f"el máximo por llamada es {MAX_SIMULATED_REQUESTS:,}. Baja la duración o la tasa.",
            max_requests=MAX_SIMULATED_REQUESTS,
        )
    try:
        return simulate(
            model,
            req.scenario,
            seed=req.seed,
            duration_s=req.duration_s,
            rps=req.rps,
            arrivals=req.arrivals,
            client_timeout_s=req.client_timeout_s,
            cache_hit_ratio=req.cache_hit_ratio,
            cpu_credits=req.cpu_credits,
            traffic_profile=profile,
        )
    except ValueError as e:  # ej. un escenario con 0 req/s o vCPU en 0
        raise ApiError(422, INVALID_PARAMETERS, str(e)) from e


def load_or_422(raw: dict) -> ArchitectureModel:
    try:
        return load_model(raw)
    except KeyError as e:
        raise ApiError(422, INVALID_MODEL, f"Al modelo le falta el campo {e}.") from e
    except (ValueError, TypeError) as e:
        raise ApiError(422, INVALID_MODEL, f"El modelo no es válido: {e}") from e
