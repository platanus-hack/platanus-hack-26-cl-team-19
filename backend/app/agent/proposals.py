"""Validación compartida entre la vista previa y la aceptación de propuestas del chat."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.ops import OpError, apply_ops
from app.api.scenario_versions import OVERRIDE_FIELDS, VERSION_SCENARIOS, version_scenario
from app.api.schemas import ScenarioBusiness
from app.api.store import ProjectScenario
from app.models.overrides import apply_overrides


class ScenarioChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=60)
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


def prepare_proposal(model: dict, draft: ProposalDraft, scenarios: list[ProjectScenario]) -> PreparedProposal:
    if draft.ops is not None:
        result = apply_ops(model, draft.ops)
        return PreparedProposal(result.model, result.changes, result.warnings)
    change = draft.scenario
    assert change is not None
    saved = next((scenario for scenario in scenarios if scenario.name == change.name), None)
    if saved is None:
        raise OpError(f"El escenario '{change.name}' no existe en el proyecto.")
    return _prepare_scenario(model, change, saved)


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
