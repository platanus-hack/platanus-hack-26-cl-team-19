"""App de FastAPI. Para levantarla en desarrollo (desde ``backend/``):

  uvicorn app.api.main:app --reload

La documentación interactiva queda en http://localhost:8000/docs.

``BRANCHPOINT_CORS_ORIGINS`` (separados por coma) define desde qué orígenes puede llamarla el
navegador. Por defecto, el Nuxt de desarrollo en el puerto 3000.

Con ``DATABASE_URL`` los proyectos y versiones se guardan en Postgres (JAJ-56). Sin ella, quedan en
memoria y se pierden al reiniciar. Para leerla de ``backend/.env``:

  uvicorn app.api.main:app --reload --env-file .env

Con ``SUPABASE_URL``, las rutas de proyectos piden el token de sesión de Supabase y cada usuario ve
solo sus proyectos (JAJ-78, ver ``app/api/auth.py``). ``BRANCHPOINT_AUTH=off`` lo apaga en local.

En ``/mcp`` está el servidor MCP del agente (JAJ-67, ``app/agent/mcp.py``): la CLI de IA del usuario
(por ejemplo Claude Code) se conecta ahí y usa las tools con la misma sesión que el editor.

Con las variables ``GITHUB_APP_*``, ``/github/*`` conecta repos con la GitHub App y los analiza como v1
(JAJ-57, ver ``app/api/routes/github.py``). Sin ellas, esas rutas responden 503.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.mcp import build_mcp, mcp_asgi_app
from app.agent.openai_llm import OpenAILLM
from app.agent.tools import Limiter
from app.api.auth import SupabaseAuth, auth_from_env
from app.api.errors import install_error_handlers
from app.api.routes import attachments, chat, costs, credentials, github, health, models, projects, reports, runs
from app.api.run_cache import RUN_CACHE_HEADER
from app.api.store import InMemoryProjectStore, ProjectStore
from app.github import GitHubApp, GitHubAppConfig
from app.github.ingestion import IngestionJobs
from app.storage.attachments import attachment_storage_from_env

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


def store_from_env() -> ProjectStore:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return InMemoryProjectStore()
    from app.db.postgres_store import PostgresProjectStore  # psycopg solo hace falta con DATABASE_URL

    return PostgresProjectStore.from_url(database_url)


_FROM_ENV: Any = object()  # create_app(auth=...) sin pasar: se lee del entorno


def create_app(
    cors_origins: list[str] | None = None,
    store: ProjectStore | None = None,
    auth: SupabaseAuth | None = _FROM_ENV,
    github_app: GitHubApp | None = _FROM_ENV,
    attachment_storage: Any = _FROM_ENV,
) -> FastAPI:
    """``auth=None`` corre sin login (los tests de las rutas, y ``BRANCHPOINT_AUTH=off``).
    ``github_app=None`` deja ``/github/*`` sin configurar (503). ``attachment_storage=None`` deja los
    adjuntos del chat sin configurar (503); del entorno sale con ``SUPABASE_URL`` y ``SUPABASE_SECRET_KEY``."""
    if auth is _FROM_ENV:
        auth = auth_from_env()
    if github_app is _FROM_ENV:
        config = GitHubAppConfig.from_env()
        github_app = GitHubApp(config) if config else None
    if attachment_storage is _FROM_ENV:
        attachment_storage = attachment_storage_from_env()
    if cors_origins is None:
        env = os.environ.get("BRANCHPOINT_CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        cors_origins = [o.strip() for o in env.split(",") if o.strip()]
    owns_store = store is None
    store = store if store is not None else store_from_env()

    limiter = Limiter()  # llamadas por minuto y simulaciones por día, por usuario (MCP y chat)
    mcp_server = build_mcp(store, auth, limiter)
    mcp_app = mcp_asgi_app(mcp_server, auth)  # crea también el session manager de MCP

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            yield
        if owns_store and hasattr(store, "close"):
            store.close()  # cierra el pool de conexiones a Postgres

    app = FastAPI(
        lifespan=lifespan,
        title="Branchpoint API",
        version="0.1.0",
        description="Simula un modelo de arquitectura (branchpoint.model/v1) y devuelve el Run (branchpoint.run/v1).",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],  # PUT: escenarios del proyecto (JAJ-76)
        # Authorization: el token de sesión (JAJ-78); X-Anthropic-Api-Key: la key del usuario para el chat (JAJ-67)
        allow_headers=["Content-Type", "Authorization", "X-Anthropic-Api-Key", "X-OpenAI-Api-Key"],
        expose_headers=[RUN_CACHE_HEADER],  # para que el editor sepa si el run venía guardado (JAJ-75)
    )
    install_error_handlers(app)
    app.state.store = store
    app.state.auth = auth
    app.state.github = github_app
    app.state.ingestions = IngestionJobs()  # ingestas en curso (JAJ-57)
    app.state.limiter = limiter
    app.state.attachments = attachment_storage  # adjuntos del chat en Supabase Storage (IA-6)
    app.state.openai_llm_factory = OpenAILLM
    app.state.llm_factory = chat.default_llm_factory  # los tests lo reemplazan por un LLM falso
    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(models.router)
    app.include_router(projects.router)
    app.include_router(costs.router)
    app.include_router(github.router)
    app.include_router(chat.router)
    app.include_router(credentials.router)
    app.include_router(attachments.router)
    app.include_router(reports.router)  # JAJ-127

    app.mount("/", mcp_app)  # /mcp: el servidor MCP del agente (al final: las rutas de arriba tienen prioridad)
    return app


app = create_app()
