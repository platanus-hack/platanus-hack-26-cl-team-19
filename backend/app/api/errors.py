"""Errores de la API: todos responden ``{"error": {"code", "message", ...}}``.

``code`` es estable (sirve para que el frontend decida qué mostrar) y ``message`` está en español,
listo para mostrarle al usuario.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

INVALID_MODEL = "invalid_model"  # el modelo no es branchpoint.model/v1 o le faltan campos
UNKNOWN_SCENARIO = "unknown_scenario"  # el escenario no está en el modelo
INVALID_PARAMETERS = "invalid_parameters"  # parámetros fuera de rango o combinación inválida
RUN_TOO_LARGE = "run_too_large"  # la simulación pedida es demasiado grande para una request
NOT_FOUND = "not_found"  # el modelo de ejemplo, proyecto o versión no existe (trae ``resource``)
INVALID_OPERATIONS = "invalid_operations"  # una operación de propose_version no se puede aplicar (JAJ-68)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def error_body(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, **extra}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, **exc.extra), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()
        ]
        names = ", ".join(f["field"] or "body" for f in fields)
        return JSONResponse(
            error_body(INVALID_PARAMETERS, f"Revisa estos campos: {names}.", fields=fields),
            status_code=422,
        )
