"""Adaptador de Responses API al loop de herramientas del editor."""

import json
from typing import Any

from openai import OpenAI

from app.agent.loop import MAX_TOKENS, Turn, model_for


def _user_part(block: dict[str, Any]) -> dict[str, Any] | None:
    """Un bloque ``text`` o ``image`` del historial (forma de Anthropic) como parte de la Responses API."""
    if block["type"] == "text":
        return {"type": "input_text", "text": block["text"]}
    if block["type"] == "image":
        source = block["source"]
        url = f"data:{source['media_type']};base64,{source['data']}"
        return {"type": "input_image", "image_url": url, "detail": "auto"}
    return None


def response_input(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for message in history:
        content = message["content"]
        if isinstance(content, str):
            items.append(message)
            continue
        parts = []
        for block in content:
            if block["type"] == "openai_output":
                items.extend(block["items"])
            elif block["type"] == "tool_result":
                items.append(
                    {"type": "function_call_output", "call_id": block["tool_use_id"], "output": block["content"]}
                )
            elif message["role"] == "user" and (part := _user_part(block)):
                parts.append(part)
        if parts:
            # texto e imágenes del usuario: un solo mensaje, después de los resultados de tools del mismo turno
            items.append({"role": "user", "content": parts})
    return items


def tool_input(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        parsed = None
    # AgentTools rechaza argumentos desconocidos, incluso para tools sin parámetros.
    return parsed if isinstance(parsed, dict) else {"argumentos_json_invalidos": True}


class OpenAILLM:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        self._api_key = api_key
        self.model = model or model_for("openai", "chat")

    def complete(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Turn:
        schemas = [
            {
                "type": "function",
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
                "strict": False,
            }
            for tool in tools
        ]
        with OpenAI(api_key=self._api_key, timeout=180.0, max_retries=2) as client:
            response = client.responses.create(
                model=self.model,
                instructions=system,
                input=response_input(messages),
                tools=schemas,
                max_output_tokens=MAX_TOKENS,
                store=False,
            )
        if response.status in {"failed", "cancelled"}:
            raise RuntimeError("OpenAI no pudo completar la solicitud.")
        content: list[dict[str, Any]] = [
            {"type": "openai_output", "items": [item.model_dump(exclude_none=True) for item in response.output]}
        ]
        if response.output_text:
            content.append({"type": "text", "text": response.output_text})
        calls = [
            {"type": "tool_use", "id": item.call_id, "name": item.name, "input": tool_input(item.arguments)}
            for item in response.output
            if item.type == "function_call" and response.status != "incomplete" and item.status != "incomplete"
        ]
        content.extend(calls)
        usage = response.usage
        return Turn(
            content,
            "incomplete" if response.status == "incomplete" else ("tool_use" if calls else "end_turn"),
            {"input": usage.input_tokens, "output": usage.output_tokens} if usage else {},
        )
