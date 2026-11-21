"""``POST /projects/{id}/chat``: el chat del agente en el editor (JAJ-67, modo secundario de JAJ-54).

Transmite el loop (``app/agent/loop.py``) como NDJSON: una línea JSON por evento (``text``,
``tool_call``, ``tool_result``, ``done``, ``error``), para que el editor muestre cada tool call y su
resultado a medida que ocurren.

**Credencial:** la API key del usuario o, en modo demo, la del equipo (``app/api/llm_access.py``). El
modo principal es MCP desde la CLI del usuario.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agent.loop import AnthropicLLM, run_agent
from app.agent.tools import AgentTools
from app.api.auth import User, current_user, owner_of
from app.api.errors import INVALID_PARAMETERS, NOT_FOUND, ApiError
from app.api.llm_access import resolve_llm

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
    llm = resolve_llm(
        request,
        owner,
        x_anthropic_api_key,
        bucket="chat-demo",
        cap=DEMO_MESSAGES_PER_DAY,
        what="mensajes del chat de demo",
        missing="Para usar el chat del editor manda tu API key de Anthropic (header X-Anthropic-Api-Key), o "
        "conecta tu CLI de IA por MCP (ver docs).",
    )
    tools = AgentTools(store, owner, limiter)
    messages = [m.model_dump() for m in req.messages]

    def events() -> Iterator[bytes]:
        for event in run_agent(tools, llm, project_id, messages):
            yield (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode()

    return StreamingResponse(events(), media_type="application/x-ndjson")


def default_llm_factory(api_key: str | None) -> AnthropicLLM:
    return AnthropicLLM(api_key)
