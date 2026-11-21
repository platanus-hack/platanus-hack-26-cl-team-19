"""``POST /projects/{id}/chat``: el chat del agente en el editor (JAJ-67, modo secundario de JAJ-54).

Transmite el loop (``app/agent/loop.py``) como NDJSON: una línea JSON por evento (``text``,
``tool_call``, ``tool_result``, ``done``, ``error``), para que el editor muestre cada tool call y su
resultado a medida que ocurren.

**Credencial.**
* **Del usuario:** su API key de Anthropic en el header ``X-Anthropic-Api-Key``. Se usa solo en esta
  request: no se guarda, no se escribe en logs y no vuelve en la respuesta.
* **Demo:** sin header y con ``BRANCHPOINT_CHAT_DEMO=on``, la del equipo (el SDK la resuelve del
  entorno), con un tope de mensajes por usuario y por día.
* **Sin ninguna de las dos:** 422 con instrucciones. El modo principal es MCP desde la CLI del usuario.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agent.loop import AnthropicLLM, run_agent
from app.agent.tools import AgentTools, ToolError
from app.api.auth import User, current_user, owner_of
from app.api.errors import INVALID_PARAMETERS, NOT_FOUND, ApiError

router = APIRouter(prefix="/projects", tags=["agent"])

DEMO_MESSAGES_PER_DAY = 30


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(
        min_length=1, max_length=40, description="La conversación, la última del usuario."
    )


def _demo_on() -> bool:
    return os.environ.get("BRANCHPOINT_CHAT_DEMO", "").strip().lower() == "on"


@router.post("/{project_id}/chat", summary="Chat con el agente: transmite cada tool call (NDJSON)")
def chat(
    project_id: str,
    req: ChatRequest,
    request: Request,
    user: User | None = Depends(current_user),
    x_anthropic_api_key: str | None = Header(default=None),
) -> StreamingResponse:
    owner = owner_of(user)
    store = request.app.state.store
    if store.get(project_id, owner) is None:
        raise ApiError(404, NOT_FOUND, f"No existe el proyecto '{project_id}'.", resource="project")
    if req.messages[-1].role != "user":
        raise ApiError(422, INVALID_PARAMETERS, "El último mensaje tiene que ser del usuario.")
    limiter = request.app.state.limiter
    key = (x_anthropic_api_key or "").strip() or None
    if key is None:
        if not _demo_on():
            raise ApiError(
                422,
                INVALID_PARAMETERS,
                "Para usar el chat del editor manda tu API key de Anthropic (header X-Anthropic-Api-Key), o "
                "conecta tu CLI de IA por MCP (ver docs).",
            )
        try:  # modo demo: tope de mensajes por usuario y día
            limiter.daily(f"chat-demo:{owner or 'anon'}", DEMO_MESSAGES_PER_DAY, "mensajes del chat de demo")
        except ToolError as e:
            raise ApiError(429, INVALID_PARAMETERS, str(e)) from None
    llm = request.app.state.llm_factory(key)
    tools = AgentTools(store, owner, limiter)
    messages = [m.model_dump() for m in req.messages]

    def events() -> Iterator[bytes]:
        for event in run_agent(tools, llm, project_id, messages):
            yield (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode()

    return StreamingResponse(events(), media_type="application/x-ndjson")


def default_llm_factory(api_key: str | None) -> AnthropicLLM:
    return AnthropicLLM(api_key)
