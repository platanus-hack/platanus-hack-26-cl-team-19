"""Comparar dos versiones: el delta de sus ``Run`` y qué cambió entre sus modelos.

Ambos ``Run`` deben venir del mismo escenario y semilla, así la diferencia es del cambio de
arquitectura y no del azar de las llegadas.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.models.run import Run

MAX_CHANGES = 100


@dataclass
class MetricDelta:
    a: float | None
    b: float | None
    diff: float | None  # b - a
    pct: float | None  # (b - a) / a, None si a es 0 o falta


@dataclass
class Change:
    path: str  # ej. deployment.api.replicas, endpoints[GET /items/].steps[0].time
    a: Any
    b: Any


@dataclass
class RunDelta:
    p50_ms: MetricDelta
    p95_ms: MetricDelta
    p99_ms: MetricDelta
    error_rate: MetricDelta
    throughput_rps: MetricDelta
    bottleneck_a: str | None
    bottleneck_b: str | None
    bottleneck_changed: bool
    model_changes: list[Change]
    model_changes_truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _delta(a: float | None, b: float | None) -> MetricDelta:
    if a is None or b is None:
        return MetricDelta(a, b, None, None)
    return MetricDelta(a, b, b - a, (b - a) / a if a else None)


def run_delta(a: Run, b: Run, model_a: dict[str, Any], model_b: dict[str, Any]) -> RunDelta:
    changes = model_changes(model_a, model_b)
    return RunDelta(
        p50_ms=_delta(a.latency.p50_ms, b.latency.p50_ms),
        p95_ms=_delta(a.latency.p95_ms, b.latency.p95_ms),
        p99_ms=_delta(a.latency.p99_ms, b.latency.p99_ms),
        error_rate=_delta(a.error_rate, b.error_rate),
        throughput_rps=_delta(a.throughput_rps, b.throughput_rps),
        bottleneck_a=a.bottleneck.resource,
        bottleneck_b=b.bottleneck.resource,
        bottleneck_changed=a.bottleneck.resource != b.bottleneck.resource,
        model_changes=changes[:MAX_CHANGES],
        model_changes_truncated=len(changes) > MAX_CHANGES,
    )


# Partes del modelo que no son arquitectura: metadatos del repo, cotas derivadas y la lista de
# supuestos. Cambian solas cuando cambia lo demás y harían ruido en la lista de cambios.
_IGNORED = {"repo", "checks", "assumptions"}
# En un número del modelo solo importa el valor; la fuente y la fecha no son un cambio.
_PROVENANCE = {"unit", "label", "source", "date", "needs_review", "derived"}


def model_changes(a: dict[str, Any], b: dict[str, Any]) -> list[Change]:
    out: list[Change] = []
    for key in sorted(set(a) | set(b)):
        if key in _IGNORED:
            continue
        if key == "endpoints":
            _diff_keyed(a.get(key, []), b.get(key, []), "endpoints", out)
        else:
            _diff(a.get(key), b.get(key), key, out)
    return out


def _diff_keyed(a: list[Any], b: list[Any], path: str, out: list[Change]) -> None:
    """Endpoints por id, así reordenarlos no cuenta como cambio y agregar uno se ve como tal."""
    ka = {e.get("id"): e for e in a if isinstance(e, dict)}
    kb = {e.get("id"): e for e in b if isinstance(e, dict)}
    for k in [*ka, *(k for k in kb if k not in ka)]:
        p = f"{path}[{k}]"
        if k not in kb:
            out.append(Change(p, "presente", None))
        elif k not in ka:
            out.append(Change(p, None, "presente"))
        else:
            _diff(ka[k], kb[k], p, out)


def _diff(a: Any, b: Any, path: str, out: list[Change]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in [*a, *(k for k in b if k not in a)]:
            if k in _PROVENANCE:
                continue
            _diff(a.get(k), b.get(k), f"{path}.{k}" if k != "value" else path, out)
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            _diff(a[i] if i < len(a) else None, b[i] if i < len(b) else None, f"{path}[{i}]", out)
    elif a != b:
        out.append(Change(path, _leaf(a), _leaf(b)))


def _leaf(x: Any) -> Any:
    """Un subárbol que aparece o desaparece entero se resume, para no copiar un endpoint completo."""
    if isinstance(x, dict):
        return x.get("value", "presente")
    if isinstance(x, list):
        return f"{len(x)} elementos"
    return x
