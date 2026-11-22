"""Endpoints y valores de configuración que la ingesta no debe dejar pasar (JAJ-108).

Los tres problemas originales de BE-18 eran del extractor AST, que se borró con la PR #75 (JAJ-117). La
ingesta ahora parte de lo que propone la IA, y su forma (``ArchitectureSubmission``) ya los impide: un
solo método HTTP por endpoint, sin WebSockets, y sin ids repetidos. Estos tests lo fijan.

Lo que sí seguía pasando: un 0 citado por la IA (``api.workers=0``) o escrito en un comando
(``--workers 0``) armaba un modelo con 0 procesos, que la API rechaza (JAJ-101) o que, sin consultas a la
DB, rompía ``checks()`` con ``min()`` vacío.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.ingest import build_model as bm
from app.ingest.ai_graph import ArchitectureSubmission, build_from_ai
from app.ingest.iac import scan_deployment
from app.models import load_model

WHY = "visto en el código"


def endpoint(method="GET", path="/ping", **extra) -> dict:
    return {"method": method, "path": path, "handler": "h", "file": "main.py", "line": 1, "why": WHY, **extra}


def submission(*endpoints, observations=()) -> ArchitectureSubmission:
    return ArchitectureSubmission.model_validate(
        {
            "repo": "acme/ping",
            "framework": "fastapi",
            "language": "python",
            "endpoints": list(endpoints) or [endpoint()],
            "observations": [
                {"field": f, "value": v, "file": "main.py", "line": 1, "why": WHY} for f, v in observations
            ],
        }
    )


# --- BE-18: un endpoint por método, sin WebSockets ni ids repetidos -----------------------------------


@pytest.mark.parametrize("method", ["GET,POST", "WEBSOCKET", "websocket", "get"])
def test_one_http_method_per_endpoint_and_no_websockets(method):
    with pytest.raises(ValidationError, match="method"):
        submission(endpoint(method=method))


def test_repeated_endpoints_are_rejected():
    with pytest.raises(ValidationError, match="endpoints repetidos: GET /items"):
        submission(endpoint(path="/items"), endpoint(path="/items", handler="otro"))


def test_a_route_with_two_methods_is_two_endpoints_and_the_get_is_a_read():
    raw = build_from_ai(submission(endpoint(path="/multi"), endpoint(method="POST", path="/multi")), {})
    ids = [e["id"] for e in raw["endpoints"]]
    assert ids == ["GET /multi", "POST /multi"] and len(set(ids)) == len(ids)
    get = next(e for e in raw["endpoints"] if e["method"] == "GET")
    post = next(e for e in raw["endpoints"] if e["method"] == "POST")
    assert get["weight"]["value"] > post["weight"]["value"]  # las lecturas se llevan el 85 % del tráfico


# --- valores de configuración en 0 -----------------------------------------------------------------


def test_zero_workers_cited_by_the_ai_is_discarded_with_a_warning():
    raw = build_from_ai(submission(observations=[("api.workers", 0)]), {})
    workers = raw["deployment"]["api"]["workers"]
    assert workers["value"] >= 1 and workers["label"] == "SUPUESTO" and workers["needs_review"]
    assert any("api.workers=0" in w and "se descarta" in w for w in raw["deployment"]["iac"]["warnings"])
    load_model(raw)  # antes: invalid_model (0 workers) o, sin consultas a la DB, min() vacío en checks()


@pytest.mark.parametrize(
    "field, value, kept",
    [("db.pool_size", 0, False), ("db.pool_timeout_s", 0, False), ("db.max_overflow", 0, True)],
)
def test_pool_values_below_what_the_engine_models(field, value, kept):
    """``pool_size=0`` en SQLAlchemy es un pool sin límite y un timeout de 0 s no deja esperar: se
    descartan. ``max_overflow=0`` es válido (sin conexiones extra) y se queda."""
    raw = build_from_ai(submission(endpoint(), observations=[(field, value)]), {})
    pool = raw["deployment"]["db"]["pool_per_worker"]
    key = field.split(".")[1]
    assert (pool[key]["value"] == value) == kept
    assert any(f"{field}={value}" in w for w in raw["deployment"]["iac"]["warnings"]) != kept
    load_model(raw)


def test_zero_workers_in_a_dockerfile_is_ignored_with_a_warning(tmp_path):
    (tmp_path / "Dockerfile").write_text('CMD ["uvicorn", "main:app", "--workers", "0"]\n', encoding="utf-8")
    iac = scan_deployment(tmp_path).to_dict()
    assert "api.workers" not in iac["observed"]
    assert any("pide 0 procesos" in w for w in iac["warnings"])
    raw = build_from_ai(submission(), {}, iac=iac)
    assert raw["deployment"]["api"]["workers"]["value"] >= 1
    load_model(raw)


def test_checks_without_any_capacity_has_no_bottleneck():
    """Si ninguna capacidad tiene valor (sin consultas a la DB y sin CPU útil), ``checks()`` no se cae: el
    cuello queda en ``None``."""
    model = copy.deepcopy(build_from_ai(submission(), {}))
    model["deployment"]["api"]["workers"]["value"] = 0  # cores = 0: la cota de CPU de la API queda en 0
    out = bm.checks(model)
    assert all(s["bottleneck"] is None and s["utilization"] == {} for s in out["scenarios"].values())
