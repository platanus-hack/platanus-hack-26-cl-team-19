"""Validación compartida entre la vista previa y la aceptación de propuestas del chat."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.ops import OpError, apply_ops
from app.api.scenario_versions import OVERRIDE_FIELDS, VERSION_SCENARIOS, version_scenario
from app.api.schemas import ScenarioBusiness
from app.api.store import SCENARIO_NAME, ProjectScenario
from app.models.overrides import apply_overrides


class ScenarioChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(None, max_length=500)
    rps: float | None = Field(None, gt=0)
    multiplier: float | None = Field(None, gt=0, le=1000)
    endpoint_weights: dict[str, Annotated[float, Field(ge=0)]] | None = None
    slowdowns: dict[str, Annotated[float, Field(gt=0, le=100)]] | None = None
    business: ScenarioBusiness | None = None

    @model_validator(mode="after")
    def _validate_rate(self) -> ScenarioChange:
        if self.rps is not None and self.multiplier is not None:
            raise ValueError("Elige una tasa fija o un multiplicador del pico.")
        return self


class ProposalDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: int = Field(ge=1)
    note: str | None = Field(None, max_length=500)
    scenario: ScenarioChange | None = None
    ops: list[dict[str, Any]] | None = Field(None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def _one_change(self) -> ProposalDraft:
        if (self.scenario is None) == (self.ops is None):
            raise ValueError("La propuesta tiene que ser de escenario o de arquitectura.")
        return self


@dataclass
class PreparedProposal:
    model: dict
    changes: list[str]
    warnings: list[str]
    # Escenario que no existe en el proyecto: al aceptar se guarda en la tabla, sin versión nueva (JAJ-149)
    new_scenario: ProjectScenario | None = None


def prepare_proposal(model: dict, draft: ProposalDraft, scenarios: list[ProjectScenario]) -> PreparedProposal:
    if draft.ops is not None:
        result = apply_ops(model, draft.ops)
        return PreparedProposal(result.model, result.changes, result.warnings)
    change = draft.scenario
    assert change is not None
    saved = next((scenario for scenario in scenarios if scenario.name == change.name), None)
    if saved is None:
        return _prepare_new_scenario(model, change)
    return _prepare_scenario(model, change, saved)


def already_created(model: dict, draft: ProposalDraft, scenarios: list[ProjectScenario]) -> bool:
    """True si la propuesta creaba un escenario y ya está guardado tal cual: aceptarla dos veces no falla."""
    change = draft.scenario
    saved = next((s for s in scenarios if change and s.name == change.name), None)
    if change is None or saved is None:
        return False
    try:
        return _prepare_new_scenario(model, change).new_scenario == saved
    except ValueError:
        return False


def _prepare_new_scenario(model: dict, change: ScenarioChange) -> PreparedProposal:
    """Un escenario que el proyecto no tiene (ej. ``cyberday`` en un proyecto que nace solo con ``actual``)."""
    if not SCENARIO_NAME.fullmatch(change.name):
        raise OpError(
            f"El nombre '{change.name}' no sirve: usa de 1 a 60 letras minúsculas, números, _ o - (ej. cyberday)."
        )
    if change.rps is None and change.multiplier is None:
        raise OpError(
            f"El escenario '{change.name}' es nuevo: indica su tráfico con rps (req/s fijas) "
            "o multiplier (× el pico de la versión)."
        )
    scenario = ProjectScenario(
        change.name,
        change.multiplier,
        change.rps,
        change.description,
        endpoint_weights=change.endpoint_weights or None,
        slowdowns=change.slowdowns or None,
        business=(change.business.model_dump(exclude_none=True) if change.business else None) or None,
    )
    rate = scenario.rate_for(model)  # ValueError (sin pico) llega como error de la herramienta
    traffic = f"{rate:g} req/s" + (f" (×{change.multiplier:g} el pico)" if change.multiplier is not None else "")
    _, notes = apply_overrides(copy.deepcopy(model), **scenario.overrides())
    return PreparedProposal(
        model, [f"Escenario nuevo: {change.name}", f"Tráfico pico: {traffic}.", *notes], [], scenario
    )


def _prepare_scenario(model: dict, change: ScenarioChange, saved: ProjectScenario) -> PreparedProposal:
    updates = change.model_dump(exclude={"name"}, exclude_none=True)
    if change.rps is not None or change.multiplier is not None:
        updates.update(rps=change.rps, multiplier=change.multiplier)
    updates = {key: value for key, value in updates.items() if value or key in {"rps", "multiplier"}}
    if not updates:
        raise OpError("Indica qué quieres cambiar del escenario.")
    candidate = copy.deepcopy(model)
    patch = candidate.setdefault(VERSION_SCENARIOS, {}).setdefault(saved.name, {})
    for key, value in updates.items():
        patch[key] = {**patch.get(key, {}), **value} if key in OVERRIDE_FIELDS else value
    current = version_scenario(saved, candidate)
    previous = version_scenario(saved, model)
    if current == previous:
        raise OpError("El escenario ya tiene esos valores en la versión base.")
    before, after = previous.rate_for(model), current.rate_for(candidate)
    _, notes = apply_overrides(candidate, **current.overrides())
    if before != after:
        notes.insert(0, f"Tráfico pico: {before:g} → {after:g} req/s.")
    if not notes:
        notes.append(f"Tráfico pico: {after:g} req/s.")
    return PreparedProposal(candidate, notes, [])
