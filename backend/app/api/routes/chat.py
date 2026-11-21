"""``POST /projects/{id}/chat``: el chat del agente en el editor (JAJ-67, modo secundario de JAJ-54).

Transmite el loop (``app/agent/loop.py``) como NDJSON: una línea JSON por evento (``text``,
``tool_call``, ``tool_result``, ``done``, ``error``), para que el editor muestre cada tool call y su
resultado a medida que ocurren.

**Credencial.**
* **Del usuario:** su API key en ``X-Anthropic-Api-Key`` o ``X-OpenAI-Api-Key``, según el proveedor. Se usa solo en esta
  request: no se guarda, no se escribe en logs y no vuelve en la respuesta.
* **Con sesión:** se usa la clave elegida en Configuración o, si no hay, la key de Branchpoint del
  proveedor, con cuota diaria por usuario (``llm_key`` en ``app/api/routes/credentials.py``).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agent.loop import LLM, AnthropicLLM, run_agent
from app.agent.tools import AgentTools
from app.api.auth import User, current_user, owner_of
from app.api.errors import INVALID_PARAMETERS, NOT_FOUND, ApiError
from app.api.routes.credentials import ChatKeySource, Provider, llm_key

router = APIRouter(prefix="/projects", tags=["agent"])


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider = "anthropic"
    expected_source: ChatKeySource | None = None
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
    x_openai_api_key: str | None = Header(default=None),
) -> StreamingResponse:
    owner = owner_of(user)
    store = request.app.state.store
    if store.get(project_id, owner) is None:
        raise ApiError(404, NOT_FOUND, f"No existe el proyecto '{project_id}'.", resource="project")
    if req.messages[-1].role != "user":
        raise ApiError(422, INVALID_PARAMETERS, "El último mensaje tiene que ser del usuario.")
    limiter = request.app.state.limiter
    header = x_openai_api_key if req.provider == "openai" else x_anthropic_api_key
    key = llm_key(request, user, req.provider, header, req.expected_source).key
    factory = request.app.state.openai_llm_factory if req.provider == "openai" else request.app.state.llm_factory
    llm: LLM = factory(key)
    tools = AgentTools(store, owner, limiter)
    messages = [m.model_dump() for m in req.messages]

    def events() -> Iterator[bytes]:
        for event in run_agent(tools, llm, project_id, messages):
            yield (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode()

    return StreamingResponse(events(), media_type="application/x-ndjson")


def default_llm_factory(api_key: str | None, model: str | None = None) -> AnthropicLLM:
    return AnthropicLLM(api_key, model)
