"""App de FastAPI. Para levantarla en desarrollo (desde ``backend/``):

  uvicorn app.api.main:app --reload

La documentación interactiva queda en http://localhost:8000/docs.

``BRANCHPOINT_CORS_ORIGINS`` (separados por coma) define desde qué orígenes puede llamarla el
navegador. Por defecto, el Nuxt de desarrollo en el puerto 3000.

Con ``DATABASE_URL`` los proyectos y versiones se guardan en Postgres (JAJ-56). Sin ella, quedan en
memoria y se pierden al reiniciar. Para leerla de ``backend/.env``:

  uvicorn app.api.main:app --reload --env-file .env
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.routes import costs, health, models, projects, runs
from app.api.run_cache import RUN_CACHE_HEADER
from app.api.store import InMemoryProjectStore, ProjectStore

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


def store_from_env() -> ProjectStore:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return InMemoryProjectStore()
    from app.db.postgres_store import PostgresProjectStore  # psycopg solo hace falta con DATABASE_URL

    return PostgresProjectStore.from_url(database_url)


def create_app(cors_origins: list[str] | None = None, store: ProjectStore | None = None) -> FastAPI:
    if cors_origins is None:
        env = os.environ.get("BRANCHPOINT_CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        cors_origins = [o.strip() for o in env.split(",") if o.strip()]
    owns_store = store is None
    store = store if store is not None else store_from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=[RUN_CACHE_HEADER],  # para que el editor sepa si el run venía guardado (JAJ-75)
    )
    install_error_handlers(app)
    app.state.store = store
    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(models.router)
    app.include_router(projects.router)
    app.include_router(costs.router)
    return app


app = create_app()
