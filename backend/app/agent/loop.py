"""El loop del agente para el chat del editor (JAJ-67, modo secundario según JAJ-54).

El modo principal es MCP: el loop corre en la CLI del usuario. Este loop es para quien no tiene una CLI
o para la demo: mensaje del usuario → Claude → tool calls (``AgentTools``) → resultados → Claude, con un
máximo de iteraciones, y cada paso se transmite al editor como un evento.

La credencial es la API key del usuario (viaja en cada request y no se guarda) o, en modo demo, la del
equipo (``BRANCHPOINT_CHAT_DEMO=on``: el SDK la resuelve del entorno, una key o Workload Identity
Federation). Branchpoint nunca usa el login de claude.ai de un usuario.

``LLM`` es la interfaz que usa el loop; ``AnthropicLLM`` la implementa con el SDK y los tests usan uno
falso que devuelve tool calls fijas.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.agent.mcp import INSTRUCTIONS
from app.agent.tools import AgentTools
from app.costs.prices import manual

MODEL = "claude-opus-5-5"
MAX_ITERATIONS = 8  # vueltas LLM → tools por mensaje del usuario
MAX_TOKENS = 16_000


@dataclass
class Turn:
    """Lo que devolvió el LLM en una vuelta. ``content`` va tal cual de vuelta en el historial."""

    content: list[dict[str, Any]]
    stop_reason: str | None
    usage: dict[str, int] = field(default_factory=dict)


class LLM(Protocol):
    model: str

    def complete(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Turn: ...


class AnthropicLLM:
    """Claude por la API, con la key del usuario o, sin ella, la credencial que resuelva el SDK (demo)."""

    def __init__(self, api_key: str | None = None, model: str = MODEL) -> None:
        import anthropic

        self.model = model
        self._client = (
            anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=180.0)
            if api_key
            else (anthropic.Anthropic(max_retries=2, timeout=180.0))
        )

    def complete(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Turn:
        with self._client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=system,
            tools=tools,
            messages=messages,
        ) as stream:
            msg = stream.get_final_message()
        u = msg.usage
        return Turn(
            # tal cual, con los bloques de thinking: la API los pide de vuelta en la conversación con tools
            content=[b.model_dump(mode="json", exclude_none=True) for b in msg.content],
            stop_reason=msg.stop_reason,
            usage={
                "input": u.input_tokens,
                "output": u.output_tokens,
                "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
            },
        )


def cost_usd(model: str, usage: dict[str, int]) -> dict[str, Any] | None:
    """Costo de los tokens con la tabla de precios del repo (``manual.json``), no un número inventado."""
    try:
        table = manual()["llm_tokens"]
        p = table["usd_per_million"][model]
    except KeyError:
        return None
    usd = (
        usage.get("input", 0) * p["input"]
        + usage.get("output", 0) * p["output"]
        + usage.get("cache_read", 0) * p.get("cache_read", p["input"])
        + usage.get("cache_write", 0) * p["input"] * 1.25  # escritura de caché de 5 min: 1,25 × entrada
    ) / 1e6
    return {"value": round(usd, 4), "unit": "US$", "label": "ESTIMADO", "source": table["source"]}


def system_prompt(project_id: str) -> str:
    return (
        f"{INSTRUCTIONS}\n\nEstás en el chat del editor de Branchpoint. El proyecto abierto es project_id="
        f"{project_id!r}: úsalo en las tools sin preguntar. Responde en español, breve, y cita la procedencia "
        "de los números."
    )


def run_agent(
    tools: AgentTools,
    llm: LLM,
    project_id: str,
    messages: list[dict[str, Any]],
    max_iterations: int = MAX_ITERATIONS,
) -> Iterator[dict[str, Any]]:
    """Corre el loop y emite eventos para el editor:

    * ``{"type": "text", "text"}``: lo que escribe Claude.
    * ``{"type": "tool_call", "id", "name", "input"}`` y ``{"type": "tool_result", "id", "name", "result"}``.
    * ``{"type": "done", "stop_reason", "iterations", "usage", "cost"}`` al final.
    * ``{"type": "error", "message"}`` si el LLM falla.
    """
    history = [dict(m) for m in messages]
    schemas = tools.schemas()
    usage: dict[str, int] = {}
    for iteration in range(1, max_iterations + 1):
        try:
            turn = llm.complete(system_prompt(project_id), history, schemas)
        except Exception as e:  # noqa: BLE001 - el editor muestra el error; nada se rompe
            yield {"type": "error", "message": f"El LLM falló ({type(e).__name__}): {e}"}
            return
        for k, v in turn.usage.items():
            usage[k] = usage.get(k, 0) + v
        history.append({"role": "assistant", "content": turn.content})
        calls = [b for b in turn.content if b.get("type") == "tool_use"]
        for b in turn.content:
            if b.get("type") == "text" and b.get("text"):
                yield {"type": "text", "text": b["text"]}
        if turn.stop_reason != "tool_use" or not calls:
            yield _done(turn.stop_reason, iteration, llm.model, usage)
            return
        results = []
        for call in calls:
            yield {"type": "tool_call", "id": call["id"], "name": call["name"], "input": call.get("input", {})}
            result = tools.call(call["name"], call.get("input") or {})
            yield {"type": "tool_result", "id": call["id"], "name": call["name"], "result": result}
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                    "is_error": isinstance(result, dict) and "error" in result,
                }
            )
        history.append({"role": "user", "content": results})
    yield {"type": "text", "text": f"Llegué al máximo de {max_iterations} pasos para este mensaje. Pídeme seguir."}
    yield _done("max_iterations", max_iterations, llm.model, usage)


def _done(stop_reason: str | None, iterations: int, model: str, usage: dict[str, int]) -> dict[str, Any]:
    return {
        "type": "done",
        "stop_reason": stop_reason,
        "iterations": iterations,
        "usage": usage,
        "cost": cost_usd(model, usage),
    }
