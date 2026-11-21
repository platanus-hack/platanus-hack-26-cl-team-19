from fastapi import APIRouter

from app.models.run import RUN_SCHEMA

router = APIRouter(tags=["health"])


@router.get("/health", summary="Revisar que la API está arriba")
def health() -> dict[str, str]:
    return {"status": "ok", "run_schema": RUN_SCHEMA}
