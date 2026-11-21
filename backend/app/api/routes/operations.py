"""``GET /operations``: las operaciones tipadas que acepta ``POST /projects/{id}/proposals`` (JAJ-68).

Devuelve cada operación con su descripción y el JSON Schema de sus argumentos. Sirve para que el
agente (JAJ-67) defina sus tools sin repetir los schemas, y para que el editor muestre qué cambios
se pueden proponer.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import OperationInfo
from app.models.operations import OPERATIONS

router = APIRouter(tags=["operations"])


@router.get("/operations", response_model=list[OperationInfo], summary="Operaciones para proponer versiones")
def list_operations() -> list[OperationInfo]:
    return [
        OperationInfo(op=name, description=(cls.__doc__ or "").strip(), arguments=cls.model_json_schema())
        for name, cls in OPERATIONS.items()
    ]
