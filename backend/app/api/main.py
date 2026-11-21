"""App de FastAPI. Para levantarla en desarrollo (desde ``backend/``):

  uvicorn app.api.main:app --reload

La documentación interactiva queda en http://localhost:8000/docs.

``BRANCHPOINT_CORS_ORIGINS`` (separados por coma) define desde qué orígenes puede llamarla el
navegador. Por defecto, el Nuxt de desarrollo en el puerto 3000.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.routes import health, runs

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


def create_app(cors_origins: list[str] | None = None) -> FastAPI:
    if cors_origins is None:
        env = os.environ.get("BRANCHPOINT_CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        cors_origins = [o.strip() for o in env.split(",") if o.strip()]
    app = FastAPI(
        title="Branchpoint API",
        version="0.1.0",
        description="Simula un modelo de arquitectura (branchpoint.model/v1) y devuelve el Run (branchpoint.run/v1).",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(runs.router)
    return app


app = create_app()
