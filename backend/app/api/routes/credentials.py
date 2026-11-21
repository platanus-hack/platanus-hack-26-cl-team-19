"""Credenciales de IA por usuario. Las respuestas solo contienen proveedores configurados.

``llm_key`` elige la key de un turno de chat o de una extracción, en este orden: la del header, la
personal guardada en Supabase Vault (si el usuario la eligió) y la key de Branchpoint, con una cuota
diaria por usuario y por propósito (``BRANCHPOINT_TEAM_CHAT_LIMIT`` y ``BRANCHPOINT_TEAM_EXTRACT_LIMIT``).
"""

import os
from dataclasses import dataclass
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.api.auth import User, current_user
from app.api.errors import INVALID_PARAMETERS, UNAUTHORIZED, ApiError
from app.db.postgres_store import PostgresProjectStore

Provider = Literal["anthropic", "openai"]
ChatKeySource = Literal["team", "personal"]
Purpose = Literal["chat", "extract"]
KeySource = Literal["header", "personal", "team"]
TEAM_LIMITS: dict[str, tuple[str, int]] = {
    "chat": ("BRANCHPOINT_TEAM_CHAT_LIMIT", 30),  # mensajes de chat al día por usuario
    "extract": ("BRANCHPOINT_TEAM_EXTRACT_LIMIT", 5),  # repos analizados al día por usuario
}
TEAM_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
PROVIDER_NAMES = {"anthropic": "Anthropic", "openai": "OpenAI"}
router = APIRouter(prefix="/credentials", tags=["credentials"])


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    key: SecretStr = Field(min_length=1, max_length=1024)


def _owner(user: User | None) -> str:
    if user is None:
        raise ApiError(401, UNAUTHORIZED, "Inicia sesión para gestionar tus API keys.")
    return user.id


def _store(request: Request) -> PostgresProjectStore:
    store = request.app.state.store
    if not isinstance(store, PostgresProjectStore):
        raise ApiError(503, "credentials_unavailable", "Guardar API keys requiere Postgres y Supabase Vault.")
    return store


def _storage_error() -> ApiError:
    return ApiError(503, "credentials_unavailable", "No pudimos acceder al almacén de credenciales.")


@router.get("")
def list_credentials(request: Request, response: Response, user: User | None = Depends(current_user)) -> list[Provider]:
    owner = _owner(user)
    response.headers["Cache-Control"] = "no-store"
    try:
        return [p for p in _store(request).credential_providers(owner) if p in ("openai", "anthropic")]
    except psycopg.Error:
        raise _storage_error() from None


@router.put("/{provider}", status_code=204)
def save_credential(
    provider: Provider, body: CredentialInput, request: Request, user: User | None = Depends(current_user)
) -> Response:
    owner = _owner(user)
    key = body.key.get_secret_value().strip()
    if not key or not key.isascii() or any(not char.isprintable() or char.isspace() for char in key):
        raise ApiError(422, INVALID_PARAMETERS, "Ingresa una API key válida.")
    try:
        _store(request).save_credential(owner, provider, key)
    except psycopg.Error:
        raise _storage_error() from None
    return Response(status_code=204)


@router.delete("/{provider}", status_code=204)
def delete_credential(provider: Provider, request: Request, user: User | None = Depends(current_user)) -> Response:
    owner = _owner(user)
    try:
        _store(request).delete_credential(owner, provider)
    except psycopg.Error:
        raise _storage_error() from None
    return Response(status_code=204)


class ChatKeyInput(BaseModel):
    source: ChatKeySource


@dataclass(frozen=True)
class LlmKey:
    """La key elegida y de dónde salió. ``source == "team"`` es la de Branchpoint: lleva cuota y tope."""

    key: str
    source: KeySource

    def __repr__(self) -> str:  # nunca la key en un log o un traceback
        return f"LlmKey(source={self.source!r})"


def team_key(provider: Provider) -> str | None:
    """La key de Branchpoint del proveedor, o ``None`` si no está configurada en el entorno."""
    return os.environ.get(TEAM_KEY_ENV[provider], "").strip() or None


def team_limit(purpose: Purpose) -> int:
    name, default = TEAM_LIMITS[purpose]
    try:
        return max(0, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def _always_personal() -> tuple[str, ...]:
    """Sin key de OpenAI de Branchpoint, la key personal de OpenAI se usa con solo estar guardada."""
    return () if team_key("openai") else ("openai",)


@router.get("/chat-settings")
def chat_settings(request: Request, response: Response, user: User | None = Depends(current_user)):
    owner = _owner(user)
    store = _store(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        used = store.team_used(owner)
        chat_limit, extract_limit = team_limit("chat"), team_limit("extract")
        return {
            "personal": store.personal_chat_providers(owner, _always_personal()),
            "team": [provider for provider in ("anthropic", "openai") if team_key(provider)],
            "remaining": max(0, chat_limit - used["messages"]),
            "limit": chat_limit,
            "extract": {"remaining": max(0, extract_limit - used["extractions"]), "limit": extract_limit},
        }
    except psycopg.Error:
        raise _storage_error() from None


@router.put("/chat-settings/{provider}", status_code=204)
def select_chat_key(
    provider: Provider, body: ChatKeyInput, request: Request, user: User | None = Depends(current_user)
) -> Response:
    owner = _owner(user)
    if body.source == "team" and not team_key(provider):
        raise ApiError(
            422, INVALID_PARAMETERS, f"Branchpoint no tiene una key de {PROVIDER_NAMES[provider]}: usa la tuya."
        )
    try:
        selected = _store(request).select_chat_key(owner, provider, body.source == "personal")
    except psycopg.Error:
        raise _storage_error() from None
    if not selected:
        raise ApiError(422, INVALID_PARAMETERS, "Guarda tu API key antes de seleccionarla.")
    return Response(status_code=204)


_QUOTA_MESSAGES = {
    "chat": ("team_chat_quota", "Usaste los {limit} mensajes diarios de Branchpoint."),
    "extract": ("team_extract_quota", "Usaste los {limit} análisis de repos diarios de Branchpoint."),
}
_ASK = {"chat": "enviar mensajes", "extract": "analizar el repo"}


def llm_key(
    request: Request,
    user: User | None,
    provider: Provider,
    override: str | None,
    expected_source: ChatKeySource | None,
    purpose: Purpose = "chat",
    units: int = 1,
) -> LlmKey:
    """Elige la key: header, key personal seleccionada o key de Branchpoint con cuota.

    Con la de Branchpoint descuenta ``units`` usos de la cuota de ``purpose`` (los descuenta todos o
    ninguno). Sin cuota: 429 ``team_chat_quota`` o ``team_extract_quota``."""
    if override and override.strip():
        return LlmKey(override.strip(), "header")
    name = PROVIDER_NAMES[provider]
    header = "X-OpenAI-Api-Key" if provider == "openai" else "X-Anthropic-Api-Key"
    if user is None:
        raise ApiError(422, INVALID_PARAMETERS, f"Ingresa tu API key de {name} ({header}) para {_ASK[purpose]}.")
    store = _store(request)
    try:
        require_selected = provider not in _always_personal()
        personal = store.personal_chat_key(user.id, provider, require_selected)
        source = "personal" if personal else "team"
        if expected_source and source != expected_source:
            raise ApiError(
                409, "chat_key_changed", "Cambió tu API key activa. Revisa la opción antes de volver a enviar."
            )
        if personal:
            return LlmKey(personal, "personal")
        key = team_key(provider)
        if not key:
            raise ApiError(
                422,
                INVALID_PARAMETERS,
                f"Branchpoint no tiene una key de {name} configurada. Guarda tu API key en Configuración.",
            )
        limit = team_limit(purpose)
        if not store.charge_team(user.id, purpose, limit, units):
            code, message = _QUOTA_MESSAGES[purpose]
            raise ApiError(
                429, code, message.format(limit=limit) + " Guarda tu propia API key en Configuración para seguir."
            )
    except psycopg.Error:
        raise _storage_error() from None
    return LlmKey(key, "team")
