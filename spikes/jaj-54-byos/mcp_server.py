"""JAJ-54: prototipo de Branchpoint como servidor MCP, para que el usuario lo use con SU propia CLI de IA.

El agente (el loop con el LLM) corre en la CLI del usuario, por ejemplo Claude Code con su suscripción.
Branchpoint solo expone tools que llaman al motor. Así Branchpoint nunca ve ni guarda una credencial
de IA, y los tokens los paga la cuenta del usuario, dentro de lo que permite cada proveedor (ver
README.md).

Tools (las mismas del ADR 0001, sobre los modelos de ejemplo de backend/app/samples):
  * list_examples(): modelos de ejemplo y sus escenarios.
  * simulate(example, scenario, ...): corre el motor y devuelve el resumen del Run.
  * propose(example, ops, scenario): aplica operaciones tipadas (JAJ-68), simula antes y después
    con la misma semilla y devuelve el delta y el costo mensual.
  * ops_schema(): el JSON Schema de las operaciones, para que el LLM sepa qué puede pedir.

Ninguna tool recibe números libres del LLM: `simulate` solo elige un escenario del modelo, y `propose`
recibe operaciones validadas (cuyos números de diseño quedan SUPUESTO, o con la `quote` del usuario).
En JAJ-67 el tráfico entra solo por `set_traffic(..., quote)`. Cada resultado trae su procedencia.

Uso (desde la raíz del repo, con las dependencias del backend y `pip install "mcp>=2,<3"`):
    python spikes/jaj-54-byos/mcp_server.py                 # http://127.0.0.1:8765/mcp
    claude mcp add --transport http branchpoint http://127.0.0.1:8765/mcp
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.agent.ops import OpError, apply_ops, collect_assumptions, ops_json_schema  # noqa: E402
from app.costs.estimate import estimate_cost  # noqa: E402
from app.engine import simulate as run_engine  # noqa: E402
from app.models import load_model  # noqa: E402
from app.models.compare import run_delta  # noqa: E402
from app.models.graph import model_summary  # noqa: E402
from app.models.run import Run  # noqa: E402
from app.samples import load_sample, sample_ids  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402  (mcp 2.x)

server = MCPServer(
    name="branchpoint",
    instructions=(
        "Branchpoint simula la arquitectura de un repo (motor de eventos discretos) y propone cambios. "
        "Nunca inventes latencias, capacidades ni costos: salen de simulate y propose. Para proponer un "
        "cambio, pide ops_schema y usa propose con operaciones de ese schema. Cita el archivo:línea del "
        "cuello de botella que devuelve el motor."
    ),
)


class ToolError(Exception):
    """Un error que el LLM tiene que leer y corregir. Todas las tools lo devuelven como {"error": ...}."""


def _example(example: str) -> dict[str, Any]:
    raw = load_sample(example)
    if raw is None:
        raise ToolError(f"No existe el ejemplo '{example}'. Hay: {', '.join(sample_ids())}.")
    return raw


SIM_SECONDS = 30.0  # duración fija: el LLM no la elige


def _provenance(raw: dict[str, Any], run: Run) -> dict[str, Any]:
    """De dónde salen los números del resumen, para que el LLM lo cite (regla del proyecto)."""
    supuestos = collect_assumptions(raw)["total"]
    return {
        "label": "SUPUESTO" if supuestos else "ESTIMADO",
        "source": f"Motor de eventos discretos de Branchpoint: escenario {run.scenario}, semilla {run.seed}, "
        f"{run.duration_s:g} s simulados",
        "assumptions": supuestos,
        "note": "Un resultado hereda la etiqueta más débil de sus entradas. Los SUPUESTO del modelo se ven "
        "en el editor (en JAJ-67, con la tool list_assumptions).",
    }


def _summary(run: Run, raw: dict[str, Any]) -> dict[str, Any]:
    b = run.bottleneck
    return {
        "scenario": run.scenario,
        "rps": run.rps,
        "p95_ms": run.latency.p95_ms,
        "error_rate": round(run.error_rate, 4),
        "throughput_rps": round(run.throughput_rps, 1),
        "bottleneck": {
            "resource": b.resource,
            "utilization": round(b.utilization, 3),
            "message": b.message,
            "line": b.line,  # archivo:línea, como campo propio (además de dentro de message)
        },
        "warnings": run.warnings,  # todas: entre ellas, si el motor es optimista cerca de la capacidad
        "provenance": _provenance(raw, run),
    }


def _simulate(raw: dict[str, Any], scenario: str, seed: int) -> Run:
    model = load_model(raw)
    if scenario not in model.scenarios:
        raise ToolError(f"El modelo no tiene el escenario '{scenario}'. Hay: {', '.join(model.scenarios)}.")
    return run_engine(model, scenario, seed=seed, duration_s=SIM_SECONDS)


@server.tool()
def list_examples() -> list[dict[str, Any]]:
    """Lista los modelos de ejemplo (repos analizados) con su despliegue y las req/s de cada escenario."""
    return [{"id": sid, **model_summary(raw, load_model(raw))} for sid in sample_ids() if (raw := load_sample(sid))]


@server.tool()
def simulate(example: str, scenario: str = "cyberday", seed: int = 0) -> dict[str, Any]:
    """Simula un modelo de ejemplo bajo uno de sus escenarios (pico_normal, cyberday) y resume el Run:
    p95, errores, throughput, el cuello de botella con su archivo:línea y la procedencia. La tasa de
    tráfico sale del escenario del modelo, no se pasa a mano."""
    try:
        raw = _example(example)
        return _summary(_simulate(raw, scenario, seed), raw)
    except ToolError as e:
        return {"error": str(e)}
    except Exception as e:  # noqa: BLE001 - todo error llega al LLM con la misma forma
        return {"error": f"Error interno de Branchpoint ({type(e).__name__}): {e}"}


@server.tool()
def ops_schema() -> dict[str, Any]:
    """JSON Schema de las operaciones de arquitectura que acepta propose (scale_api, change_db_plan,
    add_pooler, add_cache, move_to_queue)."""
    return ops_json_schema()


@server.tool()
def propose(example: str, ops: list[dict[str, Any]], scenario: str = "cyberday", seed: int = 0) -> dict[str, Any]:
    """Aplica operaciones de arquitectura a un modelo de ejemplo, simula antes y después con el mismo
    escenario y semilla, y devuelve el delta (p95, errores, cuello de botella) y el costo mensual."""
    try:
        raw = _example(example)
        result = apply_ops(raw, ops)
        before = _simulate(raw, scenario, seed)
        after = _simulate(result.model, scenario, seed)
        delta = run_delta(before, after, raw, result.model)
        cost_a, cost_b = estimate_cost(raw), estimate_cost(result.model)
    except (ToolError, OpError) as e:
        return {"error": str(e)}  # el LLM lo lee y corrige
    except Exception as e:  # noqa: BLE001 - todo error llega al LLM con la misma forma
        return {"error": f"Error interno de Branchpoint ({type(e).__name__}): {e}"}
    return {
        "changes": result.changes,
        "warnings": result.warnings,
        "before": _summary(before, raw),
        "after": _summary(after, result.model),
        "p95_ms": {"before": delta.p95_ms.a, "after": delta.p95_ms.b},
        "error_rate": {"before": delta.error_rate.a, "after": delta.error_rate.b},
        "usd_month": {"before": cost_a.total, "after": cost_b.total},
    }


if __name__ == "__main__":
    server.run("streamable-http", host="127.0.0.1", port=8765)
