"""Runs guardados por ``cache_key`` (JAJ-75): simular dos veces lo mismo no repite el cálculo.

Las versiones no se editan (cada cambio es una versión nueva) y el motor es determinista con la
misma semilla, así que el ``Run`` de una versión queda fijo por tres cosas:

* el proyecto y el número de versión;
* los ``RunParams`` (escenario, semilla, duración, tasa, perfil de tráfico, créditos de CPU…);
* la versión del motor, ``ENGINE_VERSION``.

``cache_key`` es el sha256 de las tres. ``ENGINE_VERSION`` es el hash del código de ``app/engine`` y
``app/models``: cualquier cambio al motor o a cómo se lee el modelo cambia la clave y los runs viejos
dejan de usarse, sin que nadie tenga que acordarse de subir un número.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.api.routes.runs import run_model
from app.api.schemas import RunParams
from app.api.store import ProjectStore
from app.models.run import Run

RUN_CACHE_HEADER = "X-Branchpoint-Run-Cache"  # hit o miss; el CORS lo expone al navegador

_APP = Path(__file__).resolve().parent.parent
_ENGINE_PACKAGES = ("engine", "models")
_RUN = TypeAdapter(Run)


def _engine_version() -> str:
    digest = hashlib.sha256()
    for package in _ENGINE_PACKAGES:
        for path in sorted((_APP / package).rglob("*.py")):
            digest.update(path.relative_to(_APP).as_posix().encode())
            # sin \r: el mismo código da el mismo hash en Windows (autocrlf) y en Linux
            digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:16]


ENGINE_VERSION = _engine_version()


def cache_key(project_id: str, number: int, params: RunParams, label: str | None = None) -> str:
    payload = {
        "project": project_id,
        "version": number,
        "params": params.model_dump(mode="json"),
        "engine": ENGINE_VERSION,
        "label": label,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run_to_json(run: Run) -> dict[str, Any]:
    return _RUN.dump_python(run, mode="json")


def run_from_json(data: dict[str, Any]) -> Run:
    return _RUN.validate_python(data)


def cached_run(
    store: ProjectStore,
    project_id: str,
    number: int,
    model: dict[str, Any],
    params: RunParams,
    label: str | None = None,
) -> tuple[Run, bool]:
    """El ``Run`` de la versión: el guardado si existe (``True``) o uno recién simulado y guardado
    (``False``). Una simulación que falla (422) no se guarda.

    ``label`` reemplaza el nombre del escenario en el ``Run`` (JAJ-76: cuando la tasa sale de la tabla
    de escenarios del proyecto) y entra en la clave."""
    key = cache_key(project_id, number, params, label)
    saved = store.find_run(key)
    if saved is not None:
        return run_from_json(saved), True
    run = run_model(model, params)
    if label is not None:
        run = dataclasses.replace(run, scenario=label)
    resolved = {**params.model_dump(mode="json"), "rps": run.rps}  # con la tasa final
    store.save_run(project_id, number, key, resolved, run_to_json(run), ENGINE_VERSION)
    return run, False
