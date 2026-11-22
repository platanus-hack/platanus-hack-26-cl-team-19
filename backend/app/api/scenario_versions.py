"""Ajustes de escenario asociados a una versión, sobre los valores del proyecto."""

from __future__ import annotations

from dataclasses import replace

from app.api.store import ProjectScenario

VERSION_SCENARIOS = "version_scenarios"
OVERRIDE_FIELDS = ("endpoint_weights", "slowdowns", "business")


def version_scenario(scenario: ProjectScenario, model: dict) -> ProjectScenario:
    changes = model.get(VERSION_SCENARIOS, {}).get(scenario.name, {})
    updates = {field: changes[field] for field in ("rps", "multiplier") if field in changes}
    for field in OVERRIDE_FIELDS:
        if field in changes:
            updates[field] = {**(getattr(scenario, field) or {}), **changes[field]}
    return replace(scenario, **updates)
