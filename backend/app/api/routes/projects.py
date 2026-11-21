"""Proyectos y versiones: abrir el editor con v1, guardar versiones, simularlas y compararlas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.agent import OpError, apply_ops
from app.api.errors import INVALID_OPERATIONS, INVALID_PARAMETERS, NOT_FOUND, ApiError
from app.api.routes.models import sample_or_404
from app.api.routes.runs import load_or_422, run_model
from app.api.schemas import (
    ApplyOpsRequest,
    CompareRequest,
    CompareResponse,
    CreateProjectRequest,
    CreateVersionRequest,
    OpsVersionDetail,
    ProjectDetail,
    Region,
    RunParams,
    VersionDetail,
    VersionSummary,
)
from app.api.store import Project, ProjectStore, Version
from app.costs import CostDelta, CostEstimate, FailureCost, cost_delta, estimate_cost, failure_cost
from app.models.compare import run_delta
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
    "/{project_id}/versions/{number}/ops",
    response_model=OpsVersionDetail,
    status_code=201,
    summary="Aplicar operaciones a una versión y guardar el resultado como versión nueva (origen agente)",
)
def apply_version_ops(
    project_id: str, number: int, req: ApplyOpsRequest, store: ProjectStore = Depends(get_store)
) -> OpsVersionDetail:
    base = _version(_project(store, project_id), number)
    try:
        result = apply_ops(base.model, req.ops)
    except OpError as e:
        raise ApiError(422, INVALID_OPERATIONS, str(e)) from None
    note = req.note or "; ".join(result.changes)
    version = store.add_version(project_id, result.model, "agente", number, note[:500])
    return OpsVersionDetail(
        **_summary(version).model_dump(), model=version.model, changes=result.changes, warnings=result.warnings
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
    params = RunParams(**req.model_dump(exclude={"a", "b", "region"}))
    run_a, run_b = run_model(va.model, params), run_model(vb.model, params)
    cost_a, cost_b = estimate_cost(va.model, req.region), estimate_cost(vb.model, req.region)
    delta = cost_delta(cost_a, cost_b)
    fa, fb = failure_cost(va.model, run_a), failure_cost(vb.model, run_b)  # JAJ-74
    return CompareResponse(
        a=_summary(va),
        b=_summary(vb),
        run_a=run_a,
        run_b=run_b,
        delta=run_delta(run_a, run_b, va.model, vb.model),
        cost_a=cost_a,
        cost_b=cost_b,
        cost_delta=delta,
        failure_a=fa,
        failure_b=fb,
        summary=compare_summary(va.number, vb.number, delta, fa, fb),
    )


def compare_summary(a: int, b: int, cost: CostDelta, fa: FailureCost | None, fb: FailureCost | None) -> str:
    """'v2 cuesta +US$57,66/mes y evita entre US$X y US$Y por hora en ventas en juego' (JAJ-74).

    La diferencia se calcula con cada cota (piso y techo) y se ordena de menor a mayor: cuando las dos
    versiones fallan mucho, sus techos se acercan a "si fallara todo" y esa diferencia queda cerca de 0.
    """
    sign = "+" if cost.diff >= 0 else "−"
    text = f"v{b} cuesta {sign}US${abs(cost.diff):,.2f}/mes respecto de v{a}"
    if fa is None or fb is None:
        return text + "."
    if fa.too_short or fb.too_short:
        return text + ". La simulación es muy corta para ver los timeouts: simula más tiempo para comparar las ventas."
    lo, hi = sorted(fa.lost_sales_per_hour[k]["value"] - fb.lost_sales_per_hour[k]["value"] for k in ("low", "high"))
    floor = " (al menos)" if fa.is_floor or fb.is_floor else ""
    if lo >= 0:
        return text + f" y evita entre US${lo:,.0f} y US${hi:,.0f} por hora en ventas en juego{floor}."
    if hi <= 0:
        return text + f" y suma entre US${-hi:,.0f} y US${-lo:,.0f} por hora en ventas en juego{floor}."
    return text + f"; las ventas en juego cambian entre US${lo:,.0f} y US${hi:,.0f} por hora{floor}."


@router.get(
    "/{project_id}/versions/{number}/costs",
    response_model=CostEstimate,
    summary="Costo mensual de una versión, por componente",
)
def version_costs(
    project_id: str, number: int, region: Region = "us-east-1", store: ProjectStore = Depends(get_store)
) -> CostEstimate:
    return estimate_cost(_version(_project(store, project_id), number).model, region)
