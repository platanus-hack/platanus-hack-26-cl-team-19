"""Modelos de ejemplo (``GET /models``) y el grafo del diagrama (``POST /graph``)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.errors import NOT_FOUND, ApiError
from app.api.routes.runs import load_or_422
from app.api.schemas import GraphRequest, ModelSummary
from app.models.graph import Graph, build_graph, model_summary
from app.samples import load_sample, sample_ids

router = APIRouter(tags=["models"])


def sample_or_404(sample_id: str) -> dict[str, Any]:
    raw = load_sample(sample_id)
    if raw is None:
        raise ApiError(
            404,
            NOT_FOUND,
            f"No hay un modelo de ejemplo '{sample_id}'. Hay: {', '.join(sample_ids())}.",
            resource="model",
            available=sample_ids(),
        )
    return raw


@router.get("/models", response_model=list[ModelSummary], summary="Listar los modelos de ejemplo")
def list_models() -> list[ModelSummary]:
    out = []
    for sample_id in sample_ids():
        raw = sample_or_404(sample_id)
        out.append(ModelSummary(id=sample_id, **model_summary(raw, load_or_422(raw))))
    return out


@router.get("/models/{sample_id}", summary="Un modelo de ejemplo completo (branchpoint.model/v1)")
def get_model(sample_id: str) -> dict[str, Any]:
    return sample_or_404(sample_id)


@router.post("/graph", response_model=Graph, summary="Grafo del diagrama (nodos y aristas) de un modelo")
def graph(req: GraphRequest) -> Graph:
    return build_graph(load_or_422(req.model), req.model)
