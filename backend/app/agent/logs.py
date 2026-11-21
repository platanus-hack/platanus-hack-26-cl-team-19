"""Números de tráfico sacados de un log de acceso, con código determinista (IA-7, JAJ-118).

El LLM nunca lee el log entero ni pone estos números: ``analyze_log`` los calcula y quedan ``OBSERVADO``,
con el archivo y las líneas como fuente. El modelo puede leer tramos con ``read_log`` o ``grep_log`` si el
formato no se reconoce.

Formatos, línea a línea (se elige el que interpreta más líneas de una muestra):

* **combined**: el access log de nginx, Apache y gunicorn
  (``1.2.3.4 - - [21/Nov/2026:10:00:00 +0000] "GET /items/1 HTTP/1.1" 200 512 "-" "curl"``). Si la
  línea termina con un número decimal o con ``rt=0.123``, se toma como la duración en segundos
  (``$request_time`` de nginx).
* **uvicorn**: ``2026-11-21 10:00:00,123 INFO: 1.2.3.4:5 - "GET /items/ HTTP/1.1" 200 OK``. El formato por
  defecto de uvicorn no trae hora: sin ella hay pesos y errores, pero no req/s.
* **json**: un objeto por línea con método (``method``), ruta (``path``, ``url`` o ``uri``), estado
  (``status`` o ``status_code``), hora (``time``, ``timestamp`` o ``@timestamp``: ISO 8601 o epoch) y,
  si está, la duración: en ms con ``duration_ms``, ``latency_ms``, ``elapsed_ms`` o ``response_time_ms``;
  en segundos con ``request_time``, ``duration``, ``latency`` o ``elapsed``.

Errores son las respuestas 5xx (un 4xx es el cliente). Sin duración en el log, no hay p95: no se estima.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

WINDOW_S = 60  # el pico se mide en ventanas de 60 s
MIN_PARSED = 0.5  # con menos de la mitad de las líneas interpretadas, el formato no se reconoce
MAX_UNMATCHED = 20
SAMPLE_LINES = 3

_COMBINED = re.compile(
    r'^\S+ \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" (?P<status>\d{3}) \S+'
    r'(?: "[^"]*" "[^"]*")?(?P<rest>.*)$'
)
_TRAILING_SECONDS = re.compile(r"(?:^|\s)(?:rt=|request_time=)?(?P<s>\d+\.\d+)\s*$")
_UVICORN = re.compile(r'"(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[\d.]+" (?P<status>\d{3})')
_ISO_PREFIX = re.compile(r"^\[?(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)")
_MS_KEYS = ("duration_ms", "latency_ms", "elapsed_ms", "response_time_ms")
_S_KEYS = ("request_time", "duration", "latency", "elapsed")


@dataclass(frozen=True)
class Hit:
    line: int
    method: str
    path: str
    status: int
    epoch: float | None
    duration_ms: float | None


def _epoch_iso(ts: str) -> float | None:
    try:
        dt = datetime.fromisoformat(ts.replace(",", ".").replace(" ", "T", 1))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp()


def _parse_combined(line: str, n: int) -> Hit | None:
    m = _COMBINED.match(line)
    if not m:
        return None
    try:
        epoch = datetime.strptime(m["time"], "%d/%b/%Y:%H:%M:%S %z").timestamp()
    except ValueError:
        epoch = None
    seconds = _TRAILING_SECONDS.search(m["rest"] or "")
    duration = float(seconds["s"]) * 1000 if seconds else None
    return Hit(n, m["method"], m["path"], int(m["status"]), epoch, duration)


def _parse_uvicorn(line: str, n: int) -> Hit | None:
    m = _UVICORN.search(line)
    if not m or _COMBINED.match(line):
        return None
    ts = _ISO_PREFIX.match(line)
    return Hit(n, m["method"], m["path"], int(m["status"]), _epoch_iso(ts["ts"]) if ts else None, None)


def _parse_json(line: str, n: int) -> Hit | None:
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    flat = {**obj, **{k: v for k, v in obj.items() if isinstance(v, dict) for k, v in v.items()}}  # un nivel
    method = flat.get("method") or flat.get("http_method")
    path = flat.get("path") or flat.get("url") or flat.get("uri")
    status = flat.get("status") or flat.get("status_code")
    if not (isinstance(method, str) and isinstance(path, str) and str(status).isdigit()):
        return None
    raw_time = flat.get("time") or flat.get("timestamp") or flat.get("@timestamp")
    epoch: float | None = None
    if isinstance(raw_time, (int, float)):
        epoch = float(raw_time) / (1000 if raw_time > 1e11 else 1)  # epoch en ms o en s
    elif isinstance(raw_time, str):
        epoch = _epoch_iso(raw_time)
    duration = next((float(flat[k]) for k in _MS_KEYS if isinstance(flat.get(k), (int, float))), None)
    if duration is None:
        duration = next((float(flat[k]) * 1000 for k in _S_KEYS if isinstance(flat.get(k), (int, float))), None)
    return Hit(n, method.upper(), path, int(status), epoch, duration)


PARSERS = {"combined": _parse_combined, "uvicorn": _parse_uvicorn, "json": _parse_json}


def _lines(data: bytes | Iterable[str]) -> Iterator[str]:
    if isinstance(data, bytes):
        start = 0
        while start < len(data):  # sin partir todo en una lista: el log puede pesar 10 MB
            end = data.find(b"\n", start)
            end = len(data) if end == -1 else end
            yield data[start:end].decode("utf-8", errors="replace").rstrip("\r")
            start = end + 1
    else:
        for line in data:
            yield line.rstrip("\r\n")


def _route_matchers(endpoint_ids: list[str]) -> list[tuple[str, str, re.Pattern[str]]]:
    """``GET /articles/{slug}`` → regex de la ruta. Las rutas sin parámetros van primero (más específicas)."""
    out = []
    for eid in endpoint_ids:
        method, _, path = eid.partition(" ")
        parts = [
            ("[^/]+" if re.fullmatch(r"\{[^}]+\}|:\w+|<[^>]+>", seg) else re.escape(seg)) for seg in path.split("/")
        ]
        pattern = "/".join(parts).rstrip("/") or ""
        out.append((eid, method.upper(), re.compile(f"^{pattern}/?$")))
    return sorted(out, key=lambda m: (m[2].pattern.count("[^/]+"), -len(m[2].pattern)))


def _match(matchers: list[tuple[str, str, re.Pattern[str]]], method: str, path: str) -> str | None:
    for eid, m, rx in matchers:
        if m == method and rx.match(path):
            return eid
    return None


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 1)


def _collapse(path: str) -> str:
    """Para agrupar rutas que no calzan: los segmentos numéricos o con forma de id pasan a ``{id}``."""
    return "/".join("{id}" if re.fullmatch(r"\d+|[0-9a-f-]{16,}", s) else s for s in path.split("/"))


def analyze_log(data: bytes | Iterable[str], filename: str, endpoint_ids: list[str]) -> dict[str, Any]:
    """El resumen del log. Con un formato que no se reconoce: ``{"error": ..., "sample": [...]}``."""
    lines = _lines(data)
    head: list[tuple[int, str]] = []
    for n, line in enumerate(lines, 1):
        if line.strip():
            head.append((n, line))
        if len(head) >= 200:
            break
    if not head:
        return {"error": f"El log {filename} está vacío.", "sample": []}
    scores = {name: sum(1 for n, ln in head if parse(ln, n)) for name, parse in PARSERS.items()}
    fmt = max(scores, key=lambda k: scores[k])
    parse = PARSERS[fmt]
    matchers = _route_matchers(endpoint_ids)

    total = parsed = errors = 0
    first = last = None
    per_window: Counter[int] = Counter()
    times: list[float] = []
    durations: list[float] = []
    by_endpoint: Counter[str] = Counter()
    durations_by_endpoint: defaultdict[str, list[float]] = defaultdict(list)
    unmatched: Counter[str] = Counter()
    unparsed: list[str] = []

    def consume(n: int, line: str) -> None:
        nonlocal total, parsed, errors, first, last
        if not line.strip():
            return
        total += 1
        hit = parse(line, n)
        if hit is None:
            if len(unparsed) < SAMPLE_LINES:
                unparsed.append(line[:300])
            return
        parsed += 1
        first = n if first is None else first
        last = n
        if hit.status >= 500:
            errors += 1
        if hit.epoch is not None:
            times.append(hit.epoch)
            per_window[int(hit.epoch // WINDOW_S)] += 1
        path = hit.path.split("?", 1)[0].split("#", 1)[0]
        eid = _match(matchers, hit.method, path)
        if eid:
            by_endpoint[eid] += 1
        else:
            unmatched[f"{hit.method} {_collapse(path)}"] += 1
        if hit.duration_ms is not None:
            durations.append(hit.duration_ms)
            if eid:
                durations_by_endpoint[eid].append(hit.duration_ms)

    for n, line in head:
        consume(n, line)
    for n, line in enumerate(lines, head[-1][0] + 1):
        consume(n, line)

    if parsed < MIN_PARSED * total:
        sample = unparsed or [ln[:300] for _, ln in head[:SAMPLE_LINES]]
        return {
            "error": f"No reconocí el formato de {filename}: interpreté {parsed} de {total} líneas. Usa read_log "
            "para ver el formato y pregúntale al usuario cómo genera el log.",
            "sample": sample[:SAMPLE_LINES],
        }

    source = f"log {filename}, líneas {first}–{last}"
    out: dict[str, Any] = {"format": fmt, "lines": total, "parsed": parsed, "unparsed_sample": unparsed}
    if times:
        start, end = min(times), max(times)
        seconds = max(end - start, 1.0)
        out["window"] = {
            "from": datetime.fromtimestamp(start, UTC).isoformat(timespec="seconds"),
            "to": datetime.fromtimestamp(end, UTC).isoformat(timespec="seconds"),
            "seconds": round(seconds),
        }
        peak = max(per_window.values()) / WINDOW_S
        out["peak_rps"] = _obs(round(peak, 2), "req/s", f"{source}: máximo de requests en ventanas de {WINDOW_S} s")
        out["mean_rps"] = _obs(round(len(times) / seconds, 2), "req/s", f"{source}: requests / duración del log")
    else:
        out["window"] = None
        out["note"] = "El log no trae la hora de cada request: no se pueden calcular req/s."
    out["error_rate"] = _obs(round(errors / parsed, 4), "fracción", f"{source}: respuestas 5xx / requests")
    if durations:
        out["latency_p95_ms"] = _obs(_p95(durations), "ms", f"{source}: p95 de la duración de cada request")
    matched = sum(by_endpoint.values())
    out["endpoints"] = [
        {
            "id": eid,
            "requests": count,
            "weight": round(count / matched, 4),
            **({"p95_ms": _p95(durations_by_endpoint[eid])} if durations_by_endpoint.get(eid) else {}),
        }
        for eid, count in by_endpoint.most_common()
    ]
    out["unmatched_paths"] = [{"path": p, "requests": c} for p, c in unmatched.most_common(MAX_UNMATCHED)]
    out["source"] = source
    return out


def _obs(value: float, unit: str, source: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "label": "OBSERVADO", "source": source}
