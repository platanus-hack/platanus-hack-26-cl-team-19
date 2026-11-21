"""``POST /costs``: costo mensual de un modelo, por componente y con la procedencia de cada precio (JAJ-72).

Para una versión guardada está ``GET /projects/{id}/versions/{n}/costs``, y ``POST /projects/{id}/compare``
trae el costo de las dos versiones y la diferencia.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.runs import load_or_422
from app.api.schemas import CostRequest
from app.costs import CostEstimate, estimate_cost

router = APIRouter(tags=["costs"])


@router.post("/costs", response_model=CostEstimate, summary="Costo mensual de un modelo, por componente")
def create_cost(req: CostRequest) -> CostEstimate:
    load_or_422(req.model)  # mismo error claro que POST /runs si el modelo no es v1
    return estimate_cost(req.model, req.region)
