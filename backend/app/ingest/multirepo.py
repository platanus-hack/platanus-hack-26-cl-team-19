"""Un proyecto de varios repos (IA-5, JAJ-121): el modelo del principal más los secundarios como servicios.

El motor simula un solo servicio: el del repo principal. Cada repo secundario entra en
``deployment.services`` como un servicio que no se simula (``simulated: false``), con su tecnología y la
cantidad de endpoints que encontró la IA, junto a sus componentes (su DB, su caché) que el principal no
tenga ya. Un paso externo del principal que nombra a un secundario (por el nombre del servicio o por el
detalle del paso) queda enlazado a ese servicio; lo que no calza sigue como externo: no se adivina.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from app.models.architecture import RESOURCE_BACKGROUND


@dataclass(frozen=True)
class RepoResult:
    """El análisis de un repo del proyecto: su modelo, o el motivo por el que falló."""

    full_name: str
    branch: str
    commit: str | None
    model: dict[str, Any] | None
    error: str | None = None


def short_name(full_name: str) -> str:
    return full_name.split("/", 1)[-1]


def _names_service(step: dict[str, Any], name: str) -> bool:
    """El paso externo nombra al repo: el servicio es igual o el detalle lo menciona como palabra."""
    wanted = name.lower()
    service = str(step.get("service") or "").lower()
    if service == wanted:
        return True
    words = re.split(r"[^a-z0-9_-]+", f"{service} {step.get('detail') or ''}".lower())
    return wanted in words


def _walk(steps: list[dict[str, Any]]):
    for s in steps:
        yield s
        yield from _walk(s.get("on_miss") or [])


def _secondary_service(r: RepoResult) -> dict[str, Any]:
    source = ((r.model or {}).get("repo") or {}).get("source") or {}
    service: dict[str, Any] = {
        "name": short_name(r.full_name),
        "role": "service",
        "repo": r.full_name,
        "simulated": False,
        "origin": {
            "kind": "ia",
            "via": "ingesta",
            "source": f"Repo {r.full_name}@{r.branch}" + (f" ({r.commit[:7]})" if r.commit else ""),
        },
    }
    if r.model is not None:
        service["engine"] = source.get("framework")
        service["technology"] = source.get("framework")
        service["endpoints"] = len(r.model.get("endpoints", []))
    else:
        service["error"] = r.error
    return service


def merge_repos(primary: RepoResult, secondaries: list[RepoResult]) -> dict[str, Any]:
    """El modelo del proyecto: el del principal, con los secundarios como servicios no simulados."""
    model = copy.deepcopy(primary.model)
    assert model is not None, "el principal tiene que tener modelo"
    dep = model.setdefault("deployment", {})
    services: list[dict[str, Any]] = dep.setdefault("services", [])
    taken = {(str(s.get("name", "")).lower(), s.get("role")) for s in services}
    warnings: list[str] = model.setdefault("warnings", [])
    linked: list[str] = []

    for r in secondaries:
        svc = _secondary_service(r)
        services.append(svc)
        if r.model is None:
            warnings.append(f"No se pudo analizar {r.full_name}: {r.error}. Aparece en el diagrama sin detalle.")
            continue
        for comp in (r.model.get("deployment") or {}).get("services", []):
            key = (str(comp.get("name", "")).lower(), comp.get("role"))
            if key in taken:  # el mismo componente que ya tiene el principal (su DB compartida, por ejemplo)
                continue
            taken.add(key)
            services.append({**copy.deepcopy(comp), "repo": r.full_name, "simulated": False})

        name = svc["name"]
        replaced: set[str] = set()
        steps = [s for e in model.get("endpoints", []) for s in _walk(e.get("steps", []))]
        steps += [s for q in (dep.get("queues") or {}).values() for s in _walk(q.get("job_steps", []))]
        for step in steps:
            if step.get("resource") == "external" and step.get("kind") != RESOURCE_BACKGROUND:
                if _names_service(step, name):
                    if step.get("service") and str(step["service"]).lower() != name.lower():
                        replaced.add(str(step["service"]).lower())
                    step["service"] = name
                    step["linked_repo"] = r.full_name
                    linked.append(f"{step.get('at')} → {r.full_name}")
        if replaced:  # el componente externo que nombraba al secundario pasa a ser su servicio
            services[:] = [
                s for s in services if not (s.get("role") == "external" and str(s.get("name", "")).lower() in replaced)
            ]

    for s in services:
        if s.get("repo") is None and s.get("origin"):
            s.setdefault("repo", primary.full_name)
    repo = model.setdefault("repo", {})
    repo["sources"] = [
        {
            "full_name": r.full_name,
            "branch": r.branch,
            "commit": r.commit,
            "primary": r is primary,
            "analysis": ((r.model or {}).get("repo") or {}).get("source", {}).get("analysis"),
            **({"error": r.error} if r.error else {}),
        }
        for r in (primary, *secondaries)
    ]
    if linked:
        repo["links"] = linked
    return model


def single_repo_sources(model: dict[str, Any], full_name: str, branch: str, commit: str | None) -> None:
    """``repo.sources`` de un proyecto de un solo repo, para que todos los modelos tengan la misma forma."""
    repo = model.setdefault("repo", {})
    repo["sources"] = [
        {
            "full_name": full_name,
            "branch": branch,
            "commit": commit,
            "primary": True,
            "analysis": (repo.get("source") or {}).get("analysis"),
        }
    ]
