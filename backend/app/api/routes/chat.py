"""``POST /projects/{id}/chat``: el chat del agente en el editor (JAJ-67), el modo principal del agente (ADR 0001).

Transmite el loop (``app/agent/loop.py``) como NDJSON: una línea JSON por evento (``text``,
``tool_call``, ``tool_result``, ``done``, ``error``), para que el editor muestre cada tool call y su
resultado a medida que ocurren.

**Adjuntos (IA-7).** Un mensaje del usuario puede traer ``attachments`` (ids de ``/projects/{id}/attachments``,
hasta 5). En el último mensaje, cada imagen va al modelo como bloque de imagen y cada log como una línea con su
id: el log no se manda, lo leen las tools. Las imágenes de mensajes anteriores no se reenvían. El evento ``done``
trae ``evidence``: lo que falta respaldar en la última versión del proyecto (``pending_evidence``).

**Persistencia.** ``GET`` y ``PUT /projects/{id}/chat`` guardan la conversación del panel (una por proyecto), con
cada mensaje tal como se muestra: texto, tool calls y propuestas con su estado. La escribe el editor al terminar
cada turno y al aceptar o descartar una propuesta.

**Credencial.**
* **Del usuario:** su API key en ``X-Anthropic-Api-Key`` o ``X-OpenAI-Api-Key``, según el proveedor. Se usa solo en esta
  request: no se guarda, no se escribe en logs y no vuelve en la respuesta.
* **Con sesión:** se usa la clave elegida en Configuración o, si no hay, la key de Branchpoint del
  proveedor, con cuota diaria por usuario (``llm_key`` en ``app/api/routes/credentials.py``).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.chat_tools import ChatAgentTools
from app.agent.loop import IMAGE_MEDIA_TYPES, LLM, AnthropicLLM, image_block, run_agent
from app.agent.tools import pending_evidence
from app.api.auth import User, current_user, owner_of
from app.api.errors import INVALID_PARAMETERS, NOT_FOUND, UNAUTHORIZED, ApiError
from app.api.routes.credentials import ChatKeySource, Provider, llm_key
from app.storage.attachments import StorageError

router = APIRouter(prefix="/projects", tags=["agent"])


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)
    attachments: list[str] = Field(default_factory=list, max_length=5, description="Ids de adjuntos (solo usuario).")

    @model_validator(mode="after")
    def _only_user(self) -> ChatMessage:
        if self.attachments and self.role != "user":
            raise ValueError("solo los mensajes del usuario llevan adjuntos")
        return self


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider = "anthropic"
    expected_source: ChatKeySource | None = None
    version: int | None = Field(None, ge=1)
    scenario: str | None = Field(None, max_length=60)
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
    project = store.get(project_id, owner)
    if project is None:
        raise ApiError(404, NOT_FOUND, f"No existe el proyecto '{project_id}'.", resource="project")
    if req.messages[-1].role != "user":
        raise ApiError(422, INVALID_PARAMETERS, "El último mensaje tiene que ser del usuario.")
    base = req.version or len(project.versions)
    if project.version(base) is None:
        raise ApiError(404, NOT_FOUND, f"No existe la versión v{base}.", resource="version")
    storage = request.app.state.attachments
    if any(m.attachments for m in req.messages) and (user is None or storage is None):
        raise ApiError(401, UNAUTHORIZED, "Inicia sesión para mandar adjuntos al chat.")
    messages = with_attachments(req.messages, store, storage, project_id, owner)  # 422 antes de cobrar la cuota
    limiter = request.app.state.limiter
    header = x_openai_api_key if req.provider == "openai" else x_anthropic_api_key
    key = llm_key(request, user, req.provider, header, req.expected_source).key
    factory = request.app.state.openai_llm_factory if req.provider == "openai" else request.app.state.llm_factory
    llm: LLM = factory(key)
    tools = ChatAgentTools(
        store,
        owner,
        limiter,
        storage if user is not None else None,
        project_id=project_id,
        base_version=base,
        user_messages=[m.content for m in req.messages if m.role == "user"],  # para comprobar cada quote (JAJ-102)
    )

    def events() -> Iterator[bytes]:
        for event in run_agent(tools, llm, project_id, messages, editor_version=base, editor_scenario=req.scenario):
            if event["type"] == "done":
                event["evidence"] = _evidence(store, project_id, owner)
            yield (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode()

    return StreamingResponse(events(), media_type="application/x-ndjson")


MAX_SAVED_MESSAGES = 400
MAX_SAVED_BYTES = 2 * 1024 * 1024


class SavedChatMessage(BaseModel):
    """Un mensaje del panel. El backend no interpreta su forma: la define el editor."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, max_length=200)
    role: Literal["user", "agent", "tool", "chat-proposal", "proposal"]


class SavedChat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[SavedChatMessage] = Field(max_length=MAX_SAVED_MESSAGES)


def _owned_project(request: Request, project_id: str, user: User | None) -> Any:
    store = request.app.state.store
    if store.get(project_id, owner_of(user)) is None:
        raise ApiError(404, NOT_FOUND, f"No existe el proyecto '{project_id}'.", resource="project")
    return store


@router.get("/{project_id}/chat", response_model=SavedChat, summary="La conversación guardada del proyecto")
def get_chat(project_id: str, request: Request, user: User | None = Depends(current_user)) -> SavedChat:
    store = _owned_project(request, project_id, user)
    return SavedChat(messages=[SavedChatMessage.model_validate(m) for m in store.get_chat(project_id)])


@router.put("/{project_id}/chat", status_code=204, summary="Guardar la conversación del proyecto")
def save_chat(
    project_id: str, body: SavedChat, request: Request, user: User | None = Depends(current_user)
) -> Response:
    store = _owned_project(request, project_id, user)
    messages = [m.model_dump() for m in body.messages]
    if len(json.dumps(messages, ensure_ascii=False, default=str)) > MAX_SAVED_BYTES:
        raise ApiError(422, INVALID_PARAMETERS, "La conversación es demasiado larga para guardarla. Empieza una nueva.")
    store.save_chat(project_id, messages)
    return Response(status_code=204)


MAX_IMAGE_BYTES = 5 * 1024 * 1024


def with_attachments(
    messages: list[ChatMessage], store: Any, storage: Any, project_id: str, owner: str | None
) -> list[dict[str, Any]]:
    """La conversación para el modelo. Los adjuntos del último mensaje se validan (422 si no sirven): las
    imágenes van como bloques de imagen y los logs como una línea con su id. En los anteriores, una nota."""
    out: list[dict[str, Any]] = []
    for i, m in enumerate(messages):
        if not m.attachments:
            out.append({"role": m.role, "content": m.content})
            continue
        last = i == len(messages) - 1
        notes, images = [], []
        for aid in m.attachments:
            a = store.get_attachment(aid, owner) if owner else None
            usable = a is not None and a.project_id == project_id and a.status == "ready" and not a.expired()
            if not usable:
                if last:
                    raise ApiError(
                        422, INVALID_PARAMETERS, f"El adjunto '{aid}' no existe, venció o no terminó de subir."
                    )
                notes.append("[Adjunto que ya no está disponible]")
            elif a.kind == "log":
                notes.append(f"[Adjunto de log: {a.filename}, id {a.id}, {a.bytes} bytes]")
            elif not last:
                notes.append(f"[Imagen adjunta antes: {a.filename}]")
            elif a.media_type not in IMAGE_MEDIA_TYPES:
                raise ApiError(422, INVALID_PARAMETERS, f"'{a.filename}' no es una imagen que el modelo pueda ver.")
            else:
                try:
                    data = storage.download(a.storage_path, MAX_IMAGE_BYTES)
                except StorageError:
                    raise ApiError(
                        502, "attachments_storage_error", "No pudimos leer la imagen adjunta. Vuelve a subirla."
                    ) from None
                images.append(image_block(a.media_type, base64.b64encode(data).decode()))
                notes.append(f"[Imagen adjunta: {a.filename}]")
        text = "\n".join([m.content, *notes])
        content: Any = [*images, {"type": "text", "text": text}] if images else text
        out.append({"role": m.role, "content": content})
    return out


def _evidence(store: Any, project_id: str, owner: str | None) -> dict[str, Any] | None:
    """Lo que falta respaldar en la última versión, sin LLM. ``None`` si no se pudo leer el proyecto."""
    try:
        project = store.get(project_id, owner)
        version = store.get_version(project_id, len(project.versions)) if project else None
        return pending_evidence(version.model) if version and version.model else None
    except Exception:  # noqa: BLE001 - el chat ya respondió: la tarjeta de evidencia es un extra
        return None


def default_llm_factory(api_key: str | None, model: str | None = None) -> AnthropicLLM:
    return AnthropicLLM(api_key, model)
