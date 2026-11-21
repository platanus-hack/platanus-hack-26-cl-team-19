"""Adjuntos del chat (IA-6, JAJ-115): imágenes y logs que el usuario sube para el agente.

El flujo, sin que el archivo pase por el backend:

1. ``POST /projects/{id}/attachments`` con ``{filename, media_type, bytes}``: valida y devuelve una URL
   firmada (``upload_url``) y el ``content_type`` con el que subirlo.
2. El navegador hace ``PUT upload_url`` con el archivo.
3. ``POST /projects/{id}/attachments/{aid}/complete``: el backend confirma en Storage que el tamaño y el
   tipo calzan con lo declarado y lo marca listo.

Todas piden sesión (401) y que el proyecto sea del usuario (404). Los adjuntos vencen a las
``BRANCHPOINT_ATTACHMENT_TTL_HOURS`` horas (24 por defecto). Sin cron: cada ``POST`` y ``GET`` borra
antes los vencidos de ese usuario.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import User, current_user
from app.api.errors import INVALID_PARAMETERS, NOT_FOUND, UNAUTHORIZED, ApiError
from app.api.store import Attachment, AttachmentKind
from app.storage.attachments import StorageError

router = APIRouter(prefix="/projects", tags=["attachments"])

IMAGE_TYPES = {"image/png": 5, "image/jpeg": 5, "image/webp": 5, "image/gif": 5}  # MB
LOG_TYPES = {"text/plain", "text/csv", "application/json", "application/x-ndjson"}
LOG_EXTENSIONS = {".log": "text/plain", ".txt": "text/plain", ".csv": "text/csv", ".json": "application/json"}
LOG_EXTENSIONS[".ndjson"] = LOG_EXTENSIONS[".jsonl"] = "application/x-ndjson"
UNKNOWN_TYPES = {"", "application/octet-stream", "text/x-log"}  # lo que manda un navegador por un .log
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_LOG_BYTES = 10 * 1024 * 1024
MAX_ACTIVE = 20  # adjuntos vigentes por proyecto
DEFAULT_TTL_HOURS = 24


class AttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(default="", max_length=127)
    bytes: int = Field(gt=0)


class AttachmentOut(BaseModel):
    id: str
    kind: AttachmentKind
    filename: str
    bytes: int | None
    created_at: datetime
    expires_at: datetime


class UploadOut(BaseModel):
    id: str
    kind: AttachmentKind
    upload_url: str
    content_type: str = Field(description="El Content-Type con el que el navegador sube el archivo.")
    expires_at: datetime


def ttl() -> timedelta:
    try:
        hours = float(os.environ.get("BRANCHPOINT_ATTACHMENT_TTL_HOURS", "").strip() or DEFAULT_TTL_HOURS)
    except ValueError:
        hours = DEFAULT_TTL_HOURS
    return timedelta(hours=max(hours, 0.01))


def classify(filename: str, media_type: str) -> tuple[AttachmentKind, str, int]:
    """``(kind, media_type normalizado, tamaño máximo)`` o 422 si el tipo no se acepta."""
    base = media_type.split(";")[0].strip().lower()
    if base in IMAGE_TYPES:
        return "image", base, MAX_IMAGE_BYTES
    ext = os.path.splitext(filename.lower())[1]
    if base in LOG_TYPES:
        return "log", base, MAX_LOG_BYTES
    if base in UNKNOWN_TYPES and ext in LOG_EXTENSIONS:
        return "log", LOG_EXTENSIONS[ext], MAX_LOG_BYTES
    raise ApiError(
        422,
        INVALID_PARAMETERS,
        "Solo se aceptan imágenes PNG, JPEG, WebP o GIF y logs .log, .txt, .csv, .json o .ndjson.",
    )


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(filename: str) -> str:
    """El último tramo del nombre, sin separadores ni caracteres raros: nunca sale de la carpeta del adjunto."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE.sub("_", name).strip("._") or "archivo"
    stem, ext = os.path.splitext(name)
    return (stem[:80] or "archivo") + ext[:12]


def _owner(user: User | None) -> str:
    if user is None:
        raise ApiError(401, UNAUTHORIZED, "Inicia sesión para adjuntar archivos.")
    return user.id


def _setup(request: Request, project_id: str, user: User | None) -> tuple[Any, Any, str]:
    owner = _owner(user)
    store = request.app.state.store
    if store.get(project_id, owner) is None:
        raise ApiError(404, NOT_FOUND, f"No existe el proyecto '{project_id}'.", resource="project")
    storage = request.app.state.attachments
    if storage is None:
        raise ApiError(503, "attachments_unavailable", "Los adjuntos requieren Supabase Storage configurado.")
    return store, storage, owner


def _storage_error() -> ApiError:
    return ApiError(502, "attachments_storage_error", "No pudimos comunicarnos con el almacenamiento de archivos.")


def purge_expired(store: Any, storage: Any, owner: str | None, limit: int = 100) -> int:
    """Borra objeto y fila de los adjuntos vencidos de ``owner`` (o de todos con ``None``). Devuelve cuántos."""
    gone = store.expired_attachments(owner, limit)
    if not gone:
        return 0
    storage.delete([a.storage_path for a in gone])
    for a in gone:
        store.delete_attachment(a.id, a.owner)
    return len(gone)


def _find(store: Any, project_id: str, attachment_id: str, owner: str) -> Attachment:
    a = store.get_attachment(attachment_id, owner)
    if a is None or a.project_id != project_id or a.expired():
        raise ApiError(404, NOT_FOUND, f"No existe el adjunto '{attachment_id}'.", resource="attachment")
    return a


def _out(a: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=a.id, kind=a.kind, filename=a.filename, bytes=a.bytes, created_at=a.created_at, expires_at=a.expires_at
    )


@router.post("/{project_id}/attachments", status_code=201, response_model=UploadOut, summary="Pedir URL de subida")
def create_attachment(
    project_id: str, body: AttachmentInput, request: Request, user: User | None = Depends(current_user)
) -> UploadOut:
    store, storage, owner = _setup(request, project_id, user)
    kind, media_type, max_bytes = classify(body.filename, body.media_type)
    if body.bytes > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise ApiError(422, INVALID_PARAMETERS, f"El archivo pasa el límite de {mb} MB para {kind_name(kind)}.")
    try:
        purge_expired(store, storage, owner)
        if len(store.list_attachments(project_id, owner, include_pending=True)) >= MAX_ACTIVE:
            raise ApiError(
                422, INVALID_PARAMETERS, f"El proyecto ya tiene {MAX_ACTIVE} adjuntos vigentes. Borra alguno."
            )
        aid = str(uuid.uuid4())
        path = f"{owner}/{project_id}/{aid}/{safe_filename(body.filename)}"
        upload_url = storage.signed_upload(path)
    except StorageError:
        raise _storage_error() from None
    now = datetime.now(UTC)
    a = store.create_attachment(
        Attachment(
            id=aid,
            owner=owner,
            project_id=project_id,
            kind=kind,
            filename=body.filename[:255],
            media_type=media_type,
            bytes=body.bytes,
            storage_path=path,
            status="pending",
            created_at=now,
            expires_at=now + ttl(),
        )
    )
    return UploadOut(id=a.id, kind=a.kind, upload_url=upload_url, content_type=media_type, expires_at=a.expires_at)


def kind_name(kind: AttachmentKind) -> str:
    return "imágenes" if kind == "image" else "logs"


@router.post("/{project_id}/attachments/{attachment_id}/complete", status_code=204, summary="Confirmar subida")
def complete_attachment(
    project_id: str, attachment_id: str, request: Request, user: User | None = Depends(current_user)
) -> Response:
    store, storage, owner = _setup(request, project_id, user)
    a = _find(store, project_id, attachment_id, owner)
    if a.status == "ready":
        return Response(status_code=204)
    try:
        info = storage.head(a.storage_path)
        if info is None:
            raise ApiError(422, INVALID_PARAMETERS, "No encontramos el archivo subido. Vuelve a subirlo.")
        size, media_type = info
        if size != a.bytes or media_type.split(";")[0].strip().lower() != a.media_type:
            storage.delete([a.storage_path])
            store.delete_attachment(a.id, owner)
            raise ApiError(
                422, INVALID_PARAMETERS, "El archivo subido no calza con el declarado (tamaño o tipo). Súbelo de nuevo."
            )
    except StorageError:
        raise _storage_error() from None
    store.mark_attachment_ready(a.id, owner, size)
    return Response(status_code=204)


@router.get("/{project_id}/attachments", response_model=list[AttachmentOut], summary="Adjuntos vigentes")
def list_attachments(
    project_id: str, request: Request, user: User | None = Depends(current_user)
) -> list[AttachmentOut]:
    store, storage, owner = _setup(request, project_id, user)
    try:
        purge_expired(store, storage, owner)
    except StorageError:
        raise _storage_error() from None
    return [_out(a) for a in store.list_attachments(project_id, owner)]


@router.delete("/{project_id}/attachments/{attachment_id}", status_code=204, summary="Borrar adjunto")
def delete_attachment(
    project_id: str, attachment_id: str, request: Request, user: User | None = Depends(current_user)
) -> Response:
    store, storage, owner = _setup(request, project_id, user)
    a = _find(store, project_id, attachment_id, owner)
    try:
        storage.delete([a.storage_path])
    except StorageError:
        raise _storage_error() from None
    store.delete_attachment(a.id, owner)
    return Response(status_code=204)
