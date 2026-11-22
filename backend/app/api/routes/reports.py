"""Reportes de simulación (JAJ-127): cada corrida deja su reporte guardado, y dos reportes se comparan sin
volver a simular. Ver ``app/reports``.

* ``POST /projects/{id}/versions/{n}/reports``: simula (con una semilla nueva si no viene) y guarda el reporte.
* ``GET /projects/{id}/reports``: la lista, del más nuevo al más viejo.
* ``GET /projects/{id}/reports/{rid}``: el reporte completo (``branchpoint.report/v1``).
* ``GET /projects/{id}/reports/{rid}/markdown``: el mismo reporte en Markdown.
* ``POST /projects/{id}/reports/compare``: compara dos reportes guardados y guarda la comparación.
* ``DELETE /projects/{id}/reports/{rid}``.

El PDF lo dibuja el navegador desde el reporte guardado (página de impresión del editor): sale siempre igual,
porque los datos están congelados.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.errors import INVALID_PARAMETERS, NOT_FOUND, ApiError
from app.api.routes.projects import _project, _version, _with_scenario_rate, get_store
from app.api.routes.runs import scenario_model
from app.api.run_cache import ENGINE_VERSION, cached_run, run_to_json
from app.api.schemas import RunParams
from app.api.store import INITIAL_SCENARIO, Project, ProjectStore, ReportSummary, Version
from app.costs import estimate_cost, failure_cost
from app.models.run import Run
from app.reports import build_comparison, build_report, to_markdown

router = APIRouter(prefix="/projects", tags=["reports"])


class ReportRequest(RunParams):
    """Como ``RunParams``, pero sin semilla elige una nueva: cada corrida es una simulación distinta."""

    seed: int | None = Field(None, ge=0, description="Sin valor, una semilla nueva (queda en el reporte).")


class CompareReportsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a: str = Field(description="Id del reporte A (el de referencia).")
    b: str = Field(description="Id del reporte B.")


def new_seed() -> int:
    return secrets.randbelow(2**31 - 1) + 1


def _es(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def scenario_source(store: ProjectStore, project_id: str, params: RunParams, custom_rps: bool) -> str:
    """De dónde sale la tasa de la corrida, para los supuestos del reporte (JAJ-152).

    El escenario es de la tabla del proyecto: lo definió el usuario (o lo aceptó desde el chat), salvo
    ``actual``, que nace con el proyecto. No se cita el catálogo, aunque el escenario se llame igual."""
    if custom_rps:
        return f"Tasa elegida para esta corrida: {_es(params.rps)} req/s"
    scenario = next((s for s in store.list_scenarios(project_id) if s.name == params.scenario), None)
    if scenario is None:  # no pasa: _with_scenario_rate ya lo validó
        return f"Escenario «{params.scenario}»: {_es(params.rps)} req/s"
    rate = (
        f"{_es(scenario.multiplier)} veces el pico del modelo ({_es(params.rps)} req/s)"
        if scenario.multiplier is not None
        else f"{_es(params.rps)} req/s fijas"
    )
    if scenario.traffic_step is not None:
        rate += ", con un salto de tráfico"
    who = (
        "Nace con el proyecto, con el tráfico de hoy del modelo"
        if scenario.name == INITIAL_SCENARIO
        else "Definido por el usuario"
    )
    return f"Escenario «{scenario.name}» del proyecto: {rate}. {who}"


def simulate_and_report(
    store: ProjectStore, project: Project, version: Version, params: RunParams, custom_rps: bool
) -> tuple[Run, dict[str, Any]]:
    """Simula la versión, arma el reporte y lo guarda. Lo usan la ruta del editor y la tool ``simulate`` del chat.

    ``params`` ya trae las req/s resueltas (``_with_scenario_rate``). ``custom_rps``: la tasa la eligió quien
    pidió la corrida (no sale de un escenario del proyecto)."""
    run, hit = cached_run(
        store, project.id, version.number, version.model, params, None if custom_rps else params.scenario
    )
    if hit and (saved := _same_run_report(store, project.id, version.number, params)) is not None:
        return run, saved  # JAJ-165: la misma corrida (ej. el agente simulando otra vez) no repite el reporte
    report = build_report(
        project={"id": project.id, "name": project.name},
        version={"number": version.number, "origin": version.origin, "note": version.note},
        model=version.model,
        run=run,
        run_dict=run_to_json(run),
        params=params.model_dump(mode="json"),
        custom_rps=custom_rps,
        cost=estimate_cost(version.model),
        # el costo de fallar con el negocio del escenario, como POST …/results (JAJ-131)
        failure=failure_cost(scenario_model(version.model, params)[0], run),
        engine_version=ENGINE_VERSION,
        scenario_source=scenario_source(store, project.id, params, custom_rps),
    )
    store.save_report(project.id, report)
    return run, report


def _same_run_report(store: ProjectStore, project_id: str, number: int, params: RunParams) -> dict[str, Any] | None:
    """El reporte ya guardado de esta versión con los mismos parámetros (escenario, semilla, tasa…)."""
    wanted = params.model_dump(mode="json")
    for summary in store.list_reports(project_id):
        if summary.kind != "run" or summary.version != number or summary.seed != params.seed:
            continue
        report = store.get_report(project_id, summary.id)
        if report is not None and report.get("params") == wanted:
            return report
    return None


def _report(store: ProjectStore, project_id: str, report_id: str) -> dict[str, Any]:
    report = store.get_report(project_id, report_id)
    if report is None:
        raise ApiError(404, NOT_FOUND, f"No existe el reporte '{report_id}' en este proyecto.", resource="report")
    return report


@router.post(
    "/{project_id}/versions/{number}/reports",
    status_code=201,
    summary="Simular una versión y guardar su reporte (JAJ-127)",
)
def create_report(
    project_id: str, number: int, req: ReportRequest, store: ProjectStore = Depends(get_store)
) -> dict[str, Any]:
    project = _project(store, project_id)
    version = _version(store, project, number)
    custom = req.rps is not None
    params = RunParams(**{**req.model_dump(), "seed": req.seed if req.seed is not None else new_seed()})
    params = _with_scenario_rate(store, project.id, version.model, params)
    return simulate_and_report(store, project, version, params, custom)[1]


@router.get("/{project_id}/reports", response_model=list[ReportSummary], summary="Los reportes del proyecto")
def list_reports(project_id: str, store: ProjectStore = Depends(get_store)) -> list[ReportSummary]:
    return store.list_reports(_project(store, project_id).id)


@router.get("/{project_id}/reports/{report_id}", summary="Un reporte completo (branchpoint.report/v1)")
def get_report(project_id: str, report_id: str, store: ProjectStore = Depends(get_store)) -> dict[str, Any]:
    return _report(store, _project(store, project_id).id, report_id)


@router.get(
    "/{project_id}/reports/{report_id}/markdown",
    response_class=PlainTextResponse,
    summary="El reporte en Markdown",
)
def report_markdown(project_id: str, report_id: str, store: ProjectStore = Depends(get_store)) -> PlainTextResponse:
    report = _report(store, _project(store, project_id).id, report_id)
    return PlainTextResponse(to_markdown(report), media_type="text/markdown; charset=utf-8")


@router.post("/{project_id}/reports/compare", status_code=201, summary="Comparar dos reportes guardados")
def compare_reports(
    project_id: str, req: CompareReportsRequest, store: ProjectStore = Depends(get_store)
) -> dict[str, Any]:
    project = _project(store, project_id)
    if req.a == req.b:
        raise ApiError(422, INVALID_PARAMETERS, "Elige dos reportes distintos para comparar.")
    a, b = _report(store, project.id, req.a), _report(store, project.id, req.b)
    if a["kind"] != "run" or b["kind"] != "run":
        raise ApiError(422, INVALID_PARAMETERS, "Solo se comparan reportes de corridas, no comparaciones.")
    va = store.get_version(project.id, a["version"]["number"])
    vb = store.get_version(project.id, b["version"]["number"])
    report = build_comparison(a, b, va.model if va else None, vb.model if vb else None)
    store.save_report(project.id, report)
    return report


@router.delete("/{project_id}/reports/{report_id}", status_code=204, summary="Borrar un reporte")
def delete_report(project_id: str, report_id: str, store: ProjectStore = Depends(get_store)) -> None:
    if not store.delete_report(_project(store, project_id).id, report_id):
        raise ApiError(404, NOT_FOUND, f"No existe el reporte '{report_id}' en este proyecto.", resource="report")
