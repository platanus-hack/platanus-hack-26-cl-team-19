"""Proyectos y versiones: abrir el editor con v1, guardar versiones, simularlas y compararlas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.errors import INVALID_OPERATION, INVALID_PARAMETERS, NOT_FOUND, ApiError
from app.api.routes.models import sample_or_404
from app.api.routes.runs import load_or_422, run_model
from app.api.schemas import (
    CompareRequest,
    CompareResponse,
    CreateProjectRequest,
    CreateVersionRequest,
    ProjectDetail,
    ProposalRequest,
    ProposalResponse,
    RunParams,
    VersionDetail,
    VersionSummary,
)
from app.api.store import Project, ProjectStore, Version
from app.models.compare import run_delta
from app.models.operations import OperationError, apply_operations
from app.models.run import Run

router = APIRouter(prefix="/projects", tags=["projects"])


def get_store(request: Request) -> ProjectStore:
    return request.app.state.store


def _summary(v: Version) -> VersionSummary:
    return VersionSummary(
        number=v.number, label=f"v{v.number}", origin=v.origin, parent=v.parent, note=v.note, created_at=v.created_at
    )


def _detail(p: Project) -> ProjectDetail:
    return ProjectDetail(
        id=p.id, name=p.name, sample=p.sample, created_at=p.created_at, versions=[_summary(v) for v in p.versions]
    )


def _project(store: ProjectStore, project_id: str) -> Project:
    project = store.get(project_id)
    if project is None:
        raise ApiError(404, NOT_FOUND, f"No existe el proyecto '{project_id}'.", resource="project")
    return project


def _version(project: Project, number: int) -> Version:
    version = project.version(number)
    if version is None:
        raise ApiError(
            404,
            NOT_FOUND,
            f"El proyecto no tiene la versión v{number}. Tiene de v1 a v{len(project.versions)}.",
            resource="version",
        )
    return version


@router.post("", response_model=ProjectDetail, status_code=201, summary="Crear un proyecto (queda con v1)")
def create_project(req: CreateProjectRequest, store: ProjectStore = Depends(get_store)) -> ProjectDetail:
    if (req.sample is None) == (req.model is None):
        raise ApiError(422, INVALID_PARAMETERS, "Manda sample (un modelo de ejemplo) o model, uno de los dos.")
    raw = sample_or_404(req.sample) if req.sample is not None else req.model
    model = load_or_422(raw)
    return _detail(store.create(req.name or model.name, raw, req.sample))


@router.get("", response_model=list[ProjectDetail], summary="Listar los proyectos")
def list_projects(store: ProjectStore = Depends(get_store)) -> list[ProjectDetail]:
    return [_detail(p) for p in store.list()]


@router.get("/{project_id}", response_model=ProjectDetail, summary="Un proyecto y su historial de versiones")
def get_project(project_id: str, store: ProjectStore = Depends(get_store)) -> ProjectDetail:
    return _detail(_project(store, project_id))


@router.post(
    "/{project_id}/versions",
    response_model=VersionDetail,
    status_code=201,
    summary="Guardar un modelo editado como versión nueva",
)
def create_version(
    project_id: str, req: CreateVersionRequest, store: ProjectStore = Depends(get_store)
) -> VersionDetail:
    project = _project(store, project_id)
    parent = req.parent if req.parent is not None else len(project.versions)
    _version(project, parent)
    load_or_422(req.model)
    version = store.add_version(project_id, req.model, req.origin, parent, req.note)
    return VersionDetail(**_summary(version).model_dump(), model=version.model)


@router.post(
    "/{project_id}/proposals",
    response_model=ProposalResponse,
    status_code=201,
    summary="Aplicar operaciones tipadas y guardar el resultado como versión del agente",
)
def create_proposal(
    project_id: str, req: ProposalRequest, store: ProjectStore = Depends(get_store)
) -> ProposalResponse:
    """``propose_version`` del ADR 0001 (JAJ-68): las operaciones se aplican en orden sobre la versión
    ``parent`` (por defecto, la última) y el resultado queda como versión nueva con origen ``agente``."""
    project = _project(store, project_id)
    parent = req.parent if req.parent is not None else len(project.versions)
    base = _version(project, parent)
    try:
        model, changes = apply_operations(base.model, list(req.ops))
    except OperationError as e:
        raise ApiError(422, INVALID_OPERATION, str(e), index=e.index) from e
    note = req.note or "; ".join(changes)
    version = store.add_version(project_id, model, "agente", parent, note)
    return ProposalResponse(
        version=VersionDetail(**_summary(version).model_dump(), model=version.model), changes=changes
    )


@router.get("/{project_id}/versions/{number}", response_model=VersionDetail, summary="Una versión con su modelo")
def get_version(project_id: str, number: int, store: ProjectStore = Depends(get_store)) -> VersionDetail:
    version = _version(_project(store, project_id), number)
    return VersionDetail(**_summary(version).model_dump(), model=version.model)


@router.post("/{project_id}/versions/{number}/runs", response_model=Run, summary="Simular una versión")
def run_version(project_id: str, number: int, req: RunParams, store: ProjectStore = Depends(get_store)) -> Run:
    return run_model(_version(_project(store, project_id), number).model, req)


@router.post(
    "/{project_id}/compare",
    response_model=CompareResponse,
    summary="Simular dos versiones con el mismo escenario y semilla y comparar",
)
def compare(project_id: str, req: CompareRequest, store: ProjectStore = Depends(get_store)) -> CompareResponse:
    project = _project(store, project_id)
    va, vb = _version(project, req.a), _version(project, req.b)
    params = RunParams(**req.model_dump(exclude={"a", "b"}))
    run_a, run_b = run_model(va.model, params), run_model(vb.model, params)
    return CompareResponse(
        a=_summary(va), b=_summary(vb), run_a=run_a, run_b=run_b, delta=run_delta(run_a, run_b, va.model, vb.model)
    )
