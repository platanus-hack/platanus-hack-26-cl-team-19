"""Un LLM con guion para la prueba de punta a punta: lee el repo con las tools reales del analizador.

No es un LLM: hace tres grep (rutas, llamadas a otros servicios y accesos a la DB) y arma la arquitectura
citando las líneas que encontró. Sirve para probar todo el camino sin una key real. Lo que entrega pasa por
el schema y por check_evidence como cualquier respuesta.
"""

from __future__ import annotations

import json
import os
import re
import time

from app.agent.loop import Turn

ROUTES = r"(@(app|router)\.(get|post|put|delete|patch)\(|\b(app|router|r)\.(get|post|put|delete|patch|GET|POST|PUT|DELETE)\(\s*['\"]/)"
CALLS = r"(httpx\.(get|post)|requests\.(get|post)|fetch\(|axios\.(get|post))"
DB = r"(db\.(get|add|scalars|commit|Create|query)|prisma\.\w+\.\w+\()"
ROUTE = re.compile(r"\.(get|post|put|delete|patch|GET|POST|PUT|DELETE)\(\s*['\"]([^'\"]*)")


def _hits(message: dict) -> list[tuple[str, int, str]]:
    content = json.loads(message["content"][0]["content"])
    out = []
    for hit in content.get("hits", []):
        file, line, code = hit.split(":", 2)
        out.append((file, int(line), code))
    return out


def _owner(endpoints: list[dict], file: str, line: int) -> dict | None:
    """El endpoint del mismo archivo declarado más cerca antes de esa línea."""
    before = [e for e in endpoints if e["file"] == file and e["line"] <= line]
    return max(before, key=lambda e: e["line"]) if before else None


class ScriptedAnalyst:
    model = "claude-opus-5-5"

    def complete(self, system, messages, tools):
        time.sleep(float(os.environ.get("E2E_STEP_DELAY_S", "0")))  # para ver el progreso en la UI
        turns = sum(1 for m in messages if m["role"] == "assistant")
        usage = {"input": 2500 + 1500 * turns, "output": 300}
        if turns < 3:
            pattern = (ROUTES, CALLS, DB)[turns]
            call = {"type": "tool_use", "id": f"g{turns}", "name": "grep", "input": {"pattern": pattern}}
            return Turn([call], "tool_use", usage)
        routes, calls, dbs = (_hits(m) for m in messages if m["role"] == "user" and isinstance(m["content"], list))
        endpoints, seen = [], set()
        for file, line, code in routes:
            m = ROUTE.search(code)
            if not m:  # decorador de FastAPI: la ruta está en la misma línea
                continue
            method, path = m.group(1).upper(), "/" + m.group(2).lstrip("/")
            path = re.sub(r":(\w+)", r"{\1}", path)
            if (method, path) in seen:
                continue
            seen.add((method, path))
            endpoints.append({"method": method, "path": path, "handler": f"h{len(endpoints)}", "file": file,
                              "line": line, "why": "ruta declarada en esta línea", "effects": []})  # fmt: skip
        for file, line, code in dbs:
            ep = _owner(endpoints, file, line)
            if ep is None:
                continue
            write = any(w in code for w in ("add", "commit", "create", "Create"))
            ep["effects"].append({
                "kind": "db", "op": "write" if write else "read", "shape": "commit" if write else "lookup",
                "entity": "Tabla", "detail": code.strip()[:80], "file": file, "line": line,
                "why": "acceso a la base de datos",
            })  # fmt: skip
        for file, line, code in calls:
            ep = _owner(endpoints, file, line)
            host = re.search(r"https?://([a-z0-9-]+)", code)
            if ep is None:
                continue
            ep["effects"].append({
                "kind": "external", "service": host.group(1) if host else "externo", "detail": code.strip()[:80],
                "file": file, "line": line, "why": "llamada HTTP a otro servicio",
            })  # fmt: skip
        if not endpoints:
            call = {"type": "tool_use", "id": "n", "name": "report_no_endpoints", "input": {"reason": "sin rutas"}}
            return Turn([call], "tool_use", usage)
        first = endpoints[0]
        arch = {
            "framework": "fastapi" if first["file"].endswith(".py") else "express" if first["file"].endswith(".ts") else "gin",
            "language": first["file"].rsplit(".", 1)[-1],
            "endpoints": endpoints,
            "components": [{"name": "postgres", "role": "db", "technology": "Postgres", "file": first["file"],
                            "line": first["line"], "why": "la base de datos de los handlers"}],
        }  # fmt: skip
        call = {"type": "tool_use", "id": "s", "name": "submit_architecture", "input": arch}
        return Turn([call], "tool_use", usage)
