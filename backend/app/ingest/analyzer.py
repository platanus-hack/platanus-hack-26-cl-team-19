"""Claude lee el repo en la ingesta de GitHub y propone su arquitectura (JAJ-85, JAJ-86, ADR 0002).

Sirve para cualquier framework: no hay extractores por lenguaje. El LLM recorre el tarball extraído
con tres tools de solo lectura (``list_files``, ``read_file``, ``grep``) y termina con
``submit_architecture``, que usa el mismo schema que la tool MCP de la CLI (``ai_graph.py``). Si la
propuesta no pasa el schema, el error vuelve al LLM para que la corrija.

Límites: un máximo de vueltas, de líneas por lectura y de resultados de ``grep``. Las rutas no pueden
salir del repo. El repo y el commit los pone el servidor, no el LLM.

La credencial es la del usuario (header ``X-Anthropic-Api-Key``) o, en modo demo, la del equipo, igual
que el chat del editor. ``llm`` cumple la interfaz ``LLM`` de ``app/agent/loop.py``.
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.ingest.ai_graph import ArchitectureSubmission
from app.ingest.build_model import NO_ENDPOINTS, NoEndpoints
from app.ingest.iac import MAX_FILE_BYTES, SKIP_DIRS

MAX_ITERATIONS = 40
MAX_LINES = 400  # por lectura
MAX_CHARS = 40_000  # por resultado de tool
MAX_GREP_HITS = 100
MAX_TREE = 600  # archivos en el árbol inicial
SKIP = SKIP_DIRS | {"vendor", "target", ".next", "coverage", ".idea", ".vscode", "migrations"}
TEXT_SUFFIX_BLOCK = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".lock", ".svg", ".woff", ".woff2"}

SYSTEM = """Eres el analizador de arquitectura de Branchpoint, un simulador de backends. Lee el repo con \
list_files, read_file y grep, y termina SIEMPRE con una sola llamada a submit_architecture.

Qué buscar, sin importar el lenguaje ni el framework:
1. Cada endpoint HTTP: método, ruta completa (con los prefijos de routers y montajes) y el handler, con su \
archivo:línea.
2. Lo que hace cada handler, siguiendo las funciones que llama hasta llegar a la base de datos, la caché, \
otros servicios o colas. Cada paso, en orden, con su archivo:línea y la forma de la consulta (pk, lookup, \
range, scan, commit...). Marca in_loop si se repite por cada elemento de una lista (N+1). Si una lectura de \
caché consulta la DB solo cuando falla, ponlas en on_miss.
3. Los trabajos de cola (jobs) con sus pasos, y los componentes del sistema (DB, caché, colas, servicios \
externos, storage) con su tecnología.
4. Solo si están escritos literalmente en el repo: cuántos procesos levanta la API y el tamaño del pool de \
conexiones a la DB (observations), con la línea exacta donde está el número.

Reglas:
- No inventes tiempos, filas, latencias ni costos: el schema no los acepta. Los pone el catálogo de \
Branchpoint.
- Cada archivo:línea tiene que existir en el repo: léelo antes de citarlo.
- Si no estás seguro de la forma de una consulta, usa shape "unknown".
- Si el repo no tiene un servidor HTTP, llama a report_no_endpoints.
- Sé eficiente: usa grep para encontrar rutas y accesos antes de leer archivos completos."""


class AnalysisFailed(RuntimeError):
    """La IA no terminó el análisis: el mensaje es para el usuario, en español."""


class RepoReader:
    """Lectura del repo para el LLM, sin salir de ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, rel: str) -> Path:
        path = (self.root / rel.lstrip("/")).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"{rel}: la ruta sale del repo")
        return path

    def files(self, under: str = "") -> list[str]:
        base = self._path(under)
        out = []
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(self.root)
            if any(part in SKIP or part.startswith(".") and part not in (".github",) for part in rel.parts[:-1]):
                continue
            if p.is_file() and not p.is_symlink() and p.suffix.lower() not in TEXT_SUFFIX_BLOCK:
                out.append(rel.as_posix())
        return out

    def list_files(self, path: str = "", pattern: str | None = None) -> dict[str, Any]:
        found = self.files(path)
        if pattern:
            found = [f for f in found if fnmatch.fnmatch(f, pattern) or fnmatch.fnmatch(Path(f).name, pattern)]
        return {"files": found[:MAX_TREE], "total": len(found), "truncated": len(found) > MAX_TREE}

    def read_file(self, path: str, start: int = 1, end: int | None = None) -> dict[str, Any]:
        p = self._path(path)
        if not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f"{path}: no existe o pesa más de {MAX_FILE_BYTES // 1024} KB")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, start)
        end = min(len(lines), end or start + MAX_LINES - 1, start + MAX_LINES - 1)
        body = "\n".join(f"{i}\t{lines[i - 1]}" for i in range(start, end + 1))
        return {"path": path, "lines": f"{start}-{end}", "total_lines": len(lines), "content": body[:MAX_CHARS]}

    def grep(self, pattern: str, path: str = "", glob: str | None = None) -> dict[str, Any]:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"regex inválida: {e}") from None
        hits = []
        for rel in self.files(path):
            if glob and not fnmatch.fnmatch(Path(rel).name, glob) and not fnmatch.fnmatch(rel, glob):
                continue
            p = self.root / rel
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(hits) >= MAX_GREP_HITS:
                        return {"hits": hits, "truncated": True}
        return {"hits": hits, "truncated": False}


def _submit_schema() -> dict[str, Any]:
    schema = ArchitectureSubmission.model_json_schema()
    for key in ("repo", "commit"):  # los pone el servidor
        schema["properties"].pop(key, None)
        if key in schema.get("required", []):
            schema["required"].remove(key)
    return schema


TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "Lista los archivos del repo (sin node_modules, venv ni binarios). path limita a una "
        "carpeta; pattern filtra con glob (ej. *.ts, routes/*).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": f"Lee un archivo con números de línea, hasta {MAX_LINES} líneas por llamada.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start": {"type": "integer", "minimum": 1},
                "end": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "grep",
        "description": f"Busca una regex (Python) línea por línea. Devuelve hasta {MAX_GREP_HITS} archivo:línea. "
        "glob filtra por nombre de archivo (ej. *.go).",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}},
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_architecture",
        "description": "Entrega la arquitectura del repo. Termina el análisis si pasa la validación; si no, "
        "devuelve los errores para corregirlos.",
        "input_schema": _submit_schema(),
    },
    {
        "name": "report_no_endpoints",
        "description": "El repo no tiene un servidor HTTP que modelar (es una librería, un frontend, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string", "maxLength": 300}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]


def _validation_message(e: ValidationError) -> str:
    return "submit_architecture no pasó la validación; corrige y vuelve a enviarla: " + "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'arquitectura'}: {err['msg']}" for err in e.errors()[:20]
    )


def analyze_repo(
    root: Path, llm: Any, repo: str, commit: str | None = None, *, max_iterations: int = MAX_ITERATIONS
) -> tuple[ArchitectureSubmission, dict[str, int]]:
    """La arquitectura del repo según el LLM, y los tokens que usó. Lanza ``NoEndpoints`` si el repo no
    tiene servidor HTTP y ``AnalysisFailed`` si el LLM no la entrega válida dentro del límite."""
    reader = RepoReader(root)
    tree = reader.list_files()
    intro = (
        f"Repo {repo}"
        + (f", commit {commit}" if commit else "")
        + f". Tiene {tree['total']} archivos de texto"
        + (f" (muestro los primeros {MAX_TREE})" if tree["truncated"] else "")
        + ":\n"
        + "\n".join(tree["files"])
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": intro}]
    usage: dict[str, int] = {}
    for _ in range(max_iterations):
        turn = llm.complete(SYSTEM, messages, TOOLS)
        for k, v in turn.usage.items():
            usage[k] = usage.get(k, 0) + v
        messages.append({"role": "assistant", "content": turn.content})
        calls = [b for b in turn.content if b.get("type") == "tool_use"]
        if not calls:
            messages.append({"role": "user", "content": "Termina con submit_architecture o report_no_endpoints."})
            continue
        results = []
        for call in calls:
            args = call.get("input") or {}
            name = call["name"]
            is_error = False
            if name == "submit_architecture":
                try:
                    sub = ArchitectureSubmission.model_validate({**args, "repo": repo, "commit": commit})
                except ValidationError as e:
                    result: Any = {"error": _validation_message(e)}
                    is_error = True
                else:
                    return sub, usage
            elif name == "report_no_endpoints":
                raise NoEndpoints(NO_ENDPOINTS)
            elif name in ("list_files", "read_file", "grep"):
                try:
                    result = getattr(reader, name)(**args)
                except (ValueError, TypeError, OSError) as e:
                    result, is_error = {"error": str(e)}, True
            else:
                result, is_error = {"error": f"No existe la tool {name}."}, True
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False)[:MAX_CHARS],
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": results})
    raise AnalysisFailed(
        f"La IA no terminó de analizar el repo en {max_iterations} pasos. Intenta de nuevo, o analízalo desde tu "
        "CLI de IA conectada por MCP (submit_architecture)."
    )
