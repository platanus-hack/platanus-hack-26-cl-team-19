"""Qué credencial de Claude usa el backend cuando corre la IA él mismo: el chat del editor y el análisis del
repo en la ingesta de GitHub (ADR 0002).

* **Del usuario:** su API key de Anthropic en el header ``X-Anthropic-Api-Key``. Se usa en esa request
  (o en el trabajo que lanza) y no se guarda, no se escribe en logs ni vuelve en la respuesta.
* **Demo:** sin header y con ``BRANCHPOINT_CHAT_DEMO=on``, la del equipo (el SDK la resuelve del entorno),
  con un tope por usuario y por día.
* **Sin ninguna de las dos:** 422 con instrucciones.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Request

from app.agent.tools import ToolError
from app.api.errors import INVALID_PARAMETERS, ApiError


def demo_on() -> bool:
    return os.environ.get("BRANCHPOINT_CHAT_DEMO", "").strip().lower() == "on"


def resolve_llm(
    request: Request, owner: str | None, api_key: str | None, *, bucket: str, cap: int, what: str, missing: str
) -> Any:
    """El LLM para esta request. ``bucket``, ``cap`` y ``what`` son el tope diario del modo demo."""
    key = (api_key or "").strip() or None
    if key is None:
        if not demo_on():
            raise ApiError(422, INVALID_PARAMETERS, missing)
        try:
            request.app.state.limiter.daily(f"{bucket}:{owner or 'anon'}", cap, what)
        except ToolError as e:
            raise ApiError(429, INVALID_PARAMETERS, str(e)) from None
    return request.app.state.llm_factory(key)
