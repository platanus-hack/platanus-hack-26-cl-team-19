"""El loop del agente para el chat del editor (JAJ-67): el modo principal (ADR 0001, JAJ-123).

Mensaje del usuario → modelo → tool calls (``AgentTools``) → resultados → modelo, con un máximo de
iteraciones, y cada paso se transmite al editor como un evento. ``/mcp`` expone las mismas tools como vía
secundaria, para una CLI de IA.

La credencial la selecciona el backend antes de iniciar el loop. Claude y OpenAI comparten las tools.

``LLM`` es la interfaz que usa el loop; ``AnthropicLLM`` la implementa con el SDK y los tests usan uno
falso que devuelve tool calls fijas.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic
import openai

from app.agent.mcp import INSTRUCTIONS
from app.agent.tools import AgentTools
from app.costs.prices import manual

MODEL = "claude-opus-5-5"
OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_MODELS = {"anthropic": MODEL, "openai": OPENAI_MODEL}
IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
MAX_ITERATIONS = 8  # vueltas LLM → tools por mensaje del usuario
MAX_TOKENS = 16_000


def model_for(provider: str, purpose: str) -> str:
    """El modelo de cada proveedor para el chat (``chat``) o para leer el repo (``extract``).

    Se configura con ``BRANCHPOINT_<PROVIDER>_<PURPOSE>_MODEL``, por ejemplo
    ``BRANCHPOINT_ANTHROPIC_EXTRACT_MODEL``. Sin la variable, el modelo de siempre del proveedor."""
    if provider not in DEFAULT_MODELS or purpose not in ("chat", "extract"):
        raise ValueError(f"proveedor o propósito desconocido: {provider!r}, {purpose!r}")
    value = os.environ.get(f"BRANCHPOINT_{provider.upper()}_{purpose.upper()}_MODEL", "").strip()
    return value or DEFAULT_MODELS[provider]


def image_block(media_type: str, data_base64: str) -> dict[str, Any]:
    """Bloque de imagen para un mensaje del usuario, con la forma de la API de Anthropic.

    Es la forma del historial interno: ``AnthropicLLM`` lo manda tal cual y ``OpenAILLM`` lo traduce."""
    if media_type not in IMAGE_MEDIA_TYPES:
        raise ValueError(f"tipo de imagen no soportado: {media_type}")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data_base64}}


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
    """Claude por la API, con la API key seleccionada para el turno."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.model = model or model_for("anthropic", "chat")
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
            messages=with_cache_breakpoint(messages),
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


def with_cache_breakpoint(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Marca el último bloque de la conversación con ``cache_control`` (caché de prompt de Anthropic).

    El loop reenvía todo el historial en cada vuelta: con la marca, lo ya enviado se cobra a precio de lectura
    de caché en la vuelta siguiente (spikes/ia-0-analizador). No modifica ``messages``."""
    if not messages:
        return messages
    last = dict(messages[-1])
    content = last["content"]
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [dict(b) for b in content]
    if not blocks or blocks[-1].get("type") in ("thinking", "redacted_thinking"):
        return messages
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    last["content"] = blocks
    return [*messages[:-1], last]


TOKEN_KINDS = ("input", "output", "cache_read", "cache_write")  # las claves de usage y de usd_per_million


def cost_usd(model: str, usage: dict[str, int]) -> dict[str, Any] | None:
    """Costo de los tokens con la tabla de precios del repo (``manual.json``), no un número inventado.

    Los cuatro precios salen de la tabla, incluida la escritura de caché (``cache_write``, la de 5
    minutos: antes era un ×1,25 escrito aquí, JAJ-109). ``None`` si el modelo no está en la tabla o le
    falta alguno: mejor sin costo que con uno que no tiene fuente."""
    try:
        table = manual()["llm_tokens"]
        p = table["usd_per_million"][model]
        rates = {kind: p[kind] for kind in TOKEN_KINDS}
    except KeyError:
        return None
    usd = sum(usage.get(kind, 0) * rate for kind, rate in rates.items()) / 1e6
    return {"value": round(usd, 4), "unit": "US$", "label": "ESTIMADO", "source": table["source"]}


def system_prompt(project_id: str) -> str:
    return (
        f"{INSTRUCTIONS}\n\nEstás en el chat del editor de Branchpoint. El proyecto abierto es project_id="
        f"{project_id!r}: úsalo en las tools sin preguntar. Responde en español, breve, y cita la procedencia "
        "de los números."
    )


_BILLING_ERRORS = {
    "billing_error": "reportó un problema de facturación o pago",
    "credit_balance_exhausted": "reportó que se agotaron los créditos de API de la organización",
    "insufficient_quota": "reportó cuota de API insuficiente para esta credencial",
    "project_spend_limit_exceeded": "reportó que el proyecto alcanzó su tope de gasto",
    "organization_spend_limit_exceeded": "reportó que la organización alcanzó su tope de gasto",
    "organization_usage_limit_exceeded": "reportó que la organización alcanzó su límite de uso",
}

_HTTP_ERRORS = {
    400: "rechazó los parámetros de la solicitud",
    401: "rechazó la autenticación de la API key",
    402: "reportó un problema de facturación o pago",
    403: "denegó el acceso con esta API key",
    404: "no encontró el modelo solicitado o la API key no tiene acceso",
    429: "rechazó temporalmente la solicitud por un límite de API",
    503: "está temporalmente no disponible",
    529: "está temporalmente sobrecargado",
}


def _provider_error(error: anthropic.APIError | openai.APIError, model: str) -> str:
    provider = "OpenAI" if isinstance(error, openai.APIError) else "Anthropic"
    if not isinstance(error, (anthropic.APIStatusError, openai.APIStatusError)):
        return f"No se pudo completar la conexión con {provider}."
    code = (error.code if isinstance(error, openai.APIStatusError) else error.error_code) or error.type
    reason = _BILLING_ERRORS.get(code or "") or _HTTP_ERRORS.get(error.status_code, "no pudo completar la solicitud")
    details = [f"HTTP {error.status_code}", f"modelo {model}"]
    if isinstance(code, str) and re.fullmatch(r"[a-z][a-z_0-9]{0,79}", code):
        details.append(code)
    if error.request_id and re.fullmatch(r"req(?:uest)?_[A-Za-z0-9]{1,100}", error.request_id):
        details.append(f"ID {error.request_id}")
    return f"{provider} {reason}. ({' · '.join(details)})"


def run_agent(
    tools: AgentTools,
    llm: LLM,
    project_id: str,
    messages: list[dict[str, Any]],
    max_iterations: int = MAX_ITERATIONS,
    *,
    editor_version: int | None = None,
    editor_scenario: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Corre el loop y emite eventos para el editor:

    * ``{"type": "text", "text"}``: lo que escribe el modelo.
    * ``{"type": "tool_call", "id", "name", "input"}`` y ``{"type": "tool_result", "id", "name", "result"}``.
    * ``{"type": "done", "stop_reason", "iterations", "usage", "cost"}`` al final.
    * ``{"type": "error", "message"}`` si el LLM falla.
    """
    history = [dict(m) for m in messages]
    schemas = tools.schemas(cli=False)  # el chat no ve el repo: sin submit_architecture
    prompt = system_prompt(project_id)
    if editor_version is not None:
        prompt += (
            f"\nLa versión abierta es v{editor_version}, el escenario seleccionado es {editor_scenario!r}. "
            "Usa esa versión en herramientas de lectura. Para cambiar un escenario, usa propose_scenario. "
            "Para cambios de arquitectura, usa propose_version. Las propuestas quedan pendientes: "
            "pide al usuario que las acepte en la tarjeta antes de afirmar que se aplicaron. "
            "Para el tráfico en req/s usa rps, para multiplicar el pico usa multiplier y para conversión usa una fracción."
        )
    usage: dict[str, int] = {}
    for iteration in range(1, max_iterations + 1):
        try:
            turn = llm.complete(prompt, history, schemas)
        except (anthropic.APIError, openai.APIError) as error:
            yield {"type": "error", "message": _provider_error(error, llm.model)}
            return
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
