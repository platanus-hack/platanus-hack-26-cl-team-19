"""Credenciales de IA por usuario. Las respuestas solo contienen proveedores configurados."""

import os
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.api.auth import User, current_user
from app.api.errors import INVALID_PARAMETERS, UNAUTHORIZED, ApiError
from app.db.postgres_store import PostgresProjectStore

Provider = Literal["anthropic", "openai"]
ChatKeySource = Literal["team", "personal"]
TEAM_CHAT_LIMIT = 30
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


def team_key(provider: Provider) -> str | None:
    return (os.environ.get("ANTHROPIC_API_KEY", "").strip() or None) if provider == "anthropic" else None


@router.get("/chat-settings")
def chat_settings(request: Request, response: Response, user: User | None = Depends(current_user)):
    owner = _owner(user)
    store = _store(request)
    limit = TEAM_CHAT_LIMIT
    response.headers["Cache-Control"] = "no-store"
    try:
        return {
            "personal": store.personal_chat_providers(owner),
            "team": [provider for provider in ("anthropic", "openai") if team_key(provider)],
            "remaining": max(0, limit - store.team_chat_used(owner)),
            "limit": limit,
        }
    except psycopg.Error:
        raise _storage_error() from None


@router.put("/chat-settings/{provider}", status_code=204)
def select_chat_key(
    provider: Provider, body: ChatKeyInput, request: Request, user: User | None = Depends(current_user)
) -> Response:
    owner = _owner(user)
    if provider == "openai" and body.source == "team":
        raise ApiError(422, INVALID_PARAMETERS, "OpenAI solo admite tu propia API key.")
    try:
        selected = _store(request).select_chat_key(owner, provider, body.source == "personal")
    except psycopg.Error:
        raise _storage_error() from None
    if not selected:
        raise ApiError(422, INVALID_PARAMETERS, "Guarda tu API key antes de seleccionarla.")
    return Response(status_code=204)


def chat_key(
    request: Request, user: User | None, provider: Provider, override: str | None, expected_source: ChatKeySource | None
) -> str:
    if override and override.strip():
        return override.strip()
    name = "OpenAI" if provider == "openai" else "Anthropic (X-Anthropic-Api-Key)"
    if user is None:
        raise ApiError(422, INVALID_PARAMETERS, f"Ingresa tu API key de {name} para enviar mensajes.")
    store = _store(request)
    try:
        personal = store.personal_chat_key(user.id, provider)
        source = "personal" if personal else "team"
        if expected_source and source != expected_source:
            raise ApiError(
                409, "chat_key_changed", "Cambió tu API key activa. Revisa la opción antes de volver a enviar."
            )
        if personal:
            return personal
        if provider == "openai":
            raise ApiError(422, INVALID_PARAMETERS, "Guarda tu API key de OpenAI en Configuración.")
        key = team_key(provider)
        if not key:
            raise ApiError(
                422,
                INVALID_PARAMETERS,
                f"Branchpoint no tiene una key de {name} configurada. Puedes elegir tu key en Configuración.",
            )
        limit = TEAM_CHAT_LIMIT
        if not store.charge_team_chat(user.id, limit):
            raise ApiError(
                429,
                "team_chat_quota",
                f"Usaste los {limit} mensajes diarios de Branchpoint. Puedes elegir tu API key en Configuración.",
            )
    except psycopg.Error:
        raise _storage_error() from None
    return key
