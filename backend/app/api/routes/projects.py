"""Proyectos y versiones: abrir el editor con v1, guardar versiones, simularlas y compararlas.

Los escenarios son del proyecto (JAJ-76): se cargan de ``traffic.scenarios`` de la v1 al crearlo, se
editan con ``PUT /projects/{id}/scenarios/{name}`` y sirven para simular cualquier versión.

Todas las rutas piden sesión cuando la API tiene login (JAJ-78, ``get_store``).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request, Response

from app.agent import OpError, apply_ops
from app.api.auth import User, current_user, owner_of
from app.api.errors import INVALID_OPERATIONS, INVALID_PARAMETERS, NOT_FOUND, UNKNOWN_SCENARIO, ApiError
from app.api.routes.models import sample_or_404
from app.api.routes.runs import load_or_422, scenario_model
from app.api.run_cache import RUN_CACHE_HEADER, cached_run
from app.api.schemas import (
    ApplyOpsRequest,
    CompareRequest,
    CompareResponse,
    CreateProjectRequest,
    CreateVersionRequest,
    OpsVersionDetail,
    ProjectDetail,
    ProjectRepository,
    Region,
    RunParams,
    ScenarioIn,
    ScenarioOut,
    VersionDetail,
    VersionResults,
    VersionResultsRequest,
    VersionSummary,
)
from app.api.store import OwnedStore, Project, ProjectScenario, ProjectStore, Version
from app.costs import (
    CostDelta,
    CostEstimate,
    FailureCost,
    cost_delta,
    describe_failure_missing,
    estimate_cost,
    failure_cost,
    failure_missing,
)
from app.costs.estimate import COMPONENT_NAMES, describe_missing
from app.models.compare import run_delta
from app.models.run import Run

router = APIRouter(prefix="/projects", tags=["projects"])

SCENARIO_NAME = re.compile(r"[a-z0-9_-]{1,60}")


def get_store(request: Request, user: User | None = Depends(current_user)) -> ProjectStore:
    """El store de quien llama (JAJ-78). Todas las rutas de proyectos dependen de esta función, así que
    todas piden sesión (401 sin token válido) y solo ven los proyectos de ese usuario: el de otro da
    404, como si no existiera."""
    return OwnedStore(request.app.state.store, owner_of(user))


def _summary(v: Version) -> VersionSummary:
    return VersionSummary(
        number=v.number, label=f"v{v.number}", origin=v.origin, parent=v.parent, note=v.note, created_at=v.created_at
    )


def _detail(p: Project) -> ProjectDetail:
    # JAJ-92 e IA-5: todos los repos del proyecto, el principal primero
    repos = [ProjectRepository(id=p.id, full_name=r.full_name, branch=r.branch, primary=r.primary) for r in p.repos()]
    return ProjectDetail(
        id=p.id,
        name=p.name,
        sample=p.sample,
        created_at=p.created_at,
        versions=[_summary(v) for v in p.versions],
        repositories=repos or None,
    )


def _project(store: ProjectStore, project_id: str) -> Project:
    project = store.get(project_id)
    if project is None:
        raise ApiError(404, NOT_FOUND, f"No existe el proyecto '{project_id}'.", resource="project")
    return project


def _version(store: ProjectStore, project: Project, number: int) -> Version:
    version = store.get_version(project.id, number)
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
    _version(store, project, parent)
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
    base = _version(store, _project(store, project_id), number)
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
    version = _version(store, _project(store, project_id), number)
    return VersionDetail(**_summary(version).model_dump(), model=version.model)


def _cache_header(response: Response, *hits: bool) -> None:
    """``X-Branchpoint-Run-Cache``: ``hit`` si el run estaba guardado, ``miss`` si se simuló (JAJ-75).
    En compare van los dos, de a y de b, separados por coma."""
    response.headers[RUN_CACHE_HEADER] = ",".join("hit" if hit else "miss" for hit in hits)


@router.post(
    "/{project_id}/versions/{number}/runs",
    response_model=Run,
    summary="Simular una versión (o devolver el run guardado con los mismos parámetros)",
)
def run_version(
    project_id: str, number: int, req: RunParams, response: Response, store: ProjectStore = Depends(get_store)
) -> Run:
    version = _version(store, _project(store, project_id), number)
    params = _with_scenario_rate(store, project_id, version.model, req)
    run, hit = cached_run(store, project_id, number, version.model, params, _label(req))
    _cache_header(response, hit)
    return run


@router.post(
    "/{project_id}/versions/{number}/results",
    response_model=VersionResults,
    summary="Resultados de una versión: simulación, costo mensual y costo de fallar (JAJ-128)",
)
def version_results(
    project_id: str,
    number: int,
    req: VersionResultsRequest,
    response: Response,
    store: ProjectStore = Depends(get_store),
) -> VersionResults:
    """Lo que necesita la pantalla de resultados en una llamada. El ``Run`` es el mismo de
    ``…/runs`` (con los mismos parámetros sale del guardado, JAJ-75); el costo, el de ``…/costs``; y el
    costo de fallar, el que antes solo traía ``compare`` (JAJ-74)."""
    version = _version(store, _project(store, project_id), number)
    params = _with_scenario_rate(store, project_id, version.model, RunParams(**req.model_dump(exclude={"region"})))
    run, hit = cached_run(store, project_id, number, version.model, params, _label(req))
    _cache_header(response, hit)
    cost = estimate_cost(version.model, req.region)
    # el costo de fallar con el negocio del escenario, si trae (JAJ-131); el costo de infraestructura no cambia
    biz_model, _ = scenario_model(version.model, params)
    failure = failure_cost(biz_model, run)
    missing = failure_missing(biz_model)
    return VersionResults(
        version=_summary(version),
        run=run,
        cost=cost,
        failure=failure,
        failure_missing=missing,
        summary=results_summary(version.number, cost, failure, missing, run),
    )


def results_summary(
    number: int, cost: CostEstimate, failure: FailureCost | None, missing: list[str], run: Run | None = None
) -> str:
    """'v2 cuesta US$148.67/mes en us-east-1. Con 3.2 % de errores, US$1,200 a US$9,800 por hora en
    ventas en juego…' (JAJ-128). Dice cuándo el total es parcial (componentes sin precio, JAJ-88), por
    qué no hay costo de fallar, y si la versión no alcanza a atender el tráfico (JAJ-89)."""
    text = f"v{number} cuesta US${cost.total['value']:,.2f}/mes en {cost.region}"
    if cost.missing:
        text += f" sin contar {describe_missing(cost.missing)} (despliegue local o proveedor sin precios)"
    text += "."
    text += " " + (failure.message if failure is not None else describe_failure_missing(missing))
    return text + _saturation_sentence(number, number, run, None) + _overrides_sentence(run)


def _overrides_sentence(run: Run | None) -> str:
    """Con qué reemplazos del escenario se simuló (JAJ-131): sin esto, un resultado con pagos ×10 se lee
    como el de la arquitectura tal cual."""
    return (" " + " ".join(run.overrides)) if run is not None and run.overrides else ""


def _label(req: RunParams) -> str | None:
    """Con la tasa sacada de la tabla, el ``Run`` se llama como el escenario ("cyberday") y no como
    una tasa a mano ("cyberday (262.4 req/s)", lo que pone el motor cuando recibe ``rps``)."""
    return req.scenario if req.rps is None else None


def _with_scenario_rate(store: ProjectStore, project_id: str, model: dict, params: RunParams) -> RunParams:
    """Los ``RunParams`` con las req/s del escenario del proyecto para el modelo de esta versión (JAJ-76).

    El escenario sale de la tabla del proyecto, no de ``traffic.scenarios`` del modelo: así sirve para
    cualquier versión, y ``cyberday`` ×20 da más req/s en una versión con más pico. Las req/s quedan
    en ``rps``, que entra en la ``cache_key`` (JAJ-75): si alguien edita el escenario, la clave cambia
    y no se devuelve un run con la tasa vieja. Con ``rps`` en la request, el escenario es solo un nombre.

    JAJ-131: también trae los reemplazos que guarda el escenario (mezcla de endpoints, dependencias más
    lentas, negocio). Cada uno que mande la request reemplaza al del escenario. Quedan en los params, así
    que también entran en la ``cache_key``.
    """
    if params.rps is not None:
        return params
    scenarios = {s.name: s for s in store.list_scenarios(project_id)}
    scenario = scenarios.get(params.scenario)
    if scenario is None:
        available = sorted(scenarios)
        raise ApiError(
            422,
            UNKNOWN_SCENARIO,
            f"El proyecto no tiene el escenario '{params.scenario}'. "
            + (f"Hay: {', '.join(available)}." if available else "No tiene ninguno: créalo o manda rps."),
            available=available,
        )
    try:
        rate = scenario.rate_for(model)
    except ValueError as e:
        raise ApiError(422, INVALID_PARAMETERS, str(e)) from None
    update: dict = {"rps": rate}
    for field, saved in scenario.overrides().items():
        if getattr(params, field) is None:
            update[field] = saved
    # model_validate y no model_copy: business guardado es un dict y tiene que volver a ScenarioBusiness
    return RunParams.model_validate({**params.model_dump(), **update})


def _scenario_out(s: ProjectScenario) -> ScenarioOut:
    return ScenarioOut(
        name=s.name,
        multiplier=s.multiplier,
        rps=s.rps,
        description=s.description,
        endpoint_weights=s.endpoint_weights,
        slowdowns=s.slowdowns,
        business=s.business,
    )


@router.get("/{project_id}/scenarios", response_model=list[ScenarioOut], summary="Los escenarios del proyecto (JAJ-76)")
def list_scenarios(project_id: str, store: ProjectStore = Depends(get_store)) -> list[ScenarioOut]:
    _project(store, project_id)
    return [_scenario_out(s) for s in store.list_scenarios(project_id)]


@router.get("/{project_id}/scenarios/{name}", response_model=ScenarioOut, summary="Un escenario del proyecto")
def get_scenario(project_id: str, name: str, store: ProjectStore = Depends(get_store)) -> ScenarioOut:
    _project(store, project_id)
    for s in store.list_scenarios(project_id):
        if s.name == name:
            return _scenario_out(s)
    raise ApiError(404, NOT_FOUND, f"El proyecto no tiene el escenario '{name}'.", resource="scenario")


@router.put(
    "/{project_id}/scenarios/{name}",
    response_model=ScenarioOut,
    summary="Crear o reemplazar un escenario del proyecto (sirve para todas sus versiones)",
)
def put_scenario(project_id: str, name: str, req: ScenarioIn, store: ProjectStore = Depends(get_store)) -> ScenarioOut:
    _project(store, project_id)
    if not SCENARIO_NAME.fullmatch(name):
        raise ApiError(
            422,
            INVALID_PARAMETERS,
            f"El nombre '{name}' no sirve: usa de 1 a 60 letras minúsculas, números, _ o - (ej. black_friday).",
        )
    if (req.multiplier is None) == (req.rps is None):
        raise ApiError(422, INVALID_PARAMETERS, "Manda multiplier (× el pico) o rps (req/s fijas), uno de los dos.")
    if req.business is not None and not req.business.model_dump(exclude_none=True):
        req = req.model_copy(update={"business": None})  # {} es lo mismo que no mandarlo
    scenario = ProjectScenario(
        name,
        req.multiplier,
        req.rps,
        req.description,
        endpoint_weights=req.endpoint_weights or None,
        slowdowns=req.slowdowns or None,
        business=req.business.model_dump(exclude_none=True) if req.business else None,
    )
    saved = store.upsert_scenario(project_id, scenario)
    return _scenario_out(saved)


@router.post(
    "/{project_id}/compare",
    response_model=CompareResponse,
    summary="Simular dos versiones con el mismo escenario y semilla y comparar",
)
def compare(
    project_id: str, req: CompareRequest, response: Response, store: ProjectStore = Depends(get_store)
) -> CompareResponse:
    project = _project(store, project_id)
    va, vb = _version(store, project, req.a), _version(store, project, req.b)
    params = RunParams(**req.model_dump(exclude={"a", "b", "region"}))
    # el mismo escenario, con las req/s del pico de cada versión (JAJ-76)
    params_a = _with_scenario_rate(store, project_id, va.model, params)
    params_b = _with_scenario_rate(store, project_id, vb.model, params)
    # la comparación no se guarda: es la diferencia entre dos runs, que sí se guardan (JAJ-75)
    run_a, hit_a = cached_run(store, project_id, va.number, va.model, params_a, _label(params))
    run_b, hit_b = cached_run(store, project_id, vb.number, vb.model, params_b, _label(params))
    _cache_header(response, hit_a, hit_b)
    cost_a, cost_b = estimate_cost(va.model, req.region), estimate_cost(vb.model, req.region)
    delta = cost_delta(cost_a, cost_b)
    biz_a, _ = scenario_model(va.model, params_a)  # con el negocio del escenario, si trae (JAJ-131)
    biz_b, _ = scenario_model(vb.model, params_b)
    fa, fb = failure_cost(biz_a, run_a), failure_cost(biz_b, run_b)  # JAJ-74
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
        failure_missing_a=failure_missing(biz_a),
        failure_missing_b=failure_missing(biz_b),
        summary=compare_summary(va.number, vb.number, delta, fa, fb, run_a, run_b),
    )


def compare_summary(
    a: int,
    b: int,
    cost: CostDelta,
    fa: FailureCost | None,
    fb: FailureCost | None,
    run_a: Run | None = None,
    run_b: Run | None = None,
) -> str:
    """'v2 cuesta +US$57,66/mes y evita entre US$X y US$Y por hora en ventas en juego' (JAJ-74).

    La diferencia se calcula con cada cota (piso y techo) y se ordena de menor a mayor: cuando las dos
    versiones fallan mucho, sus techos se acercan a "si fallara todo" y esa diferencia queda cerca de 0.

    Con los ``Run``, agrega si alguna versión no alcanza a atender el tráfico (JAJ-89): su tasa de
    error no cuenta las requests que siguen en fila, y sin este aviso una versión colapsada se lee sana.
    """
    return _cost_sentence(a, b, cost, fa, fb) + _saturation_sentence(a, b, run_a, run_b) + _overrides_sentence(run_a)


def _cost_sentence(a: int, b: int, cost: CostDelta, fa: FailureCost | None, fb: FailureCost | None) -> str:
    sign = "+" if cost.diff >= 0 else "−"
    text = f"v{b} cuesta {sign}US${abs(cost.diff):,.2f}/mes respecto de v{a}"
    if cost.missing:  # JAJ-88: sin esto, "+US$0.00" con la API en local se lee como "no cambia el costo"
        text += " sin contar " + _missing_clause(a, b, cost)
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


def _missing_clause(a: int, b: int, cost: CostDelta) -> str:
    """Qué no cuenta la diferencia y por qué (JAJ-88). Ejemplos:

    * 'la API ni la DB, que no tienen precio (despliegue local o proveedor sin precios)'
    * 'la API (con precio solo en v2)'
    * 'la DB, que no tiene precio (…), ni la API (con precio solo en v2)'
    """
    both = [c for c in cost.missing if c in cost.missing_a and c in cost.missing_b]
    only = [
        f"{COMPONENT_NAMES[c]} (con precio solo en v{b if c in cost.missing_a else a})"
        for c in cost.missing
        if c not in both
    ]
    if not both:
        return " ni ".join(only)
    head = f"{describe_missing(both)} (despliegue local o proveedor sin precios)"
    return head + (", ni " + " ni ".join(only) if only else "")


def _saturation_sentence(a: int, b: int, run_a: Run | None, run_b: Run | None) -> str:
    saturated = [
        (n, r.saturation)
        for n, r in ((a, run_a), (b, run_b))
        if r is not None and r.saturation and r.saturation.saturated
    ]
    if not saturated:
        return ""
    parts = " y ".join(f"v{n} deja {s.unanswered_rate * 100:.0f} % de las requests sin respuesta" for n, s in saturated)
    who = "Ninguna versión alcanza" if len(saturated) == 2 else f"v{saturated[0][0]} no alcanza"
    floor = "sus tasas de error son un piso" if len(saturated) == 2 else "su tasa de error es un piso"
    return f" Ojo: {who} a atender este tráfico ({parts} al terminar): {floor}."


@router.get(
    "/{project_id}/versions/{number}/costs",
    response_model=CostEstimate,
    summary="Costo mensual de una versión, por componente",
)
def version_costs(
    project_id: str, number: int, region: Region = "us-east-1", store: ProjectStore = Depends(get_store)
) -> CostEstimate:
    return estimate_cost(_version(store, _project(store, project_id), number).model, region)
