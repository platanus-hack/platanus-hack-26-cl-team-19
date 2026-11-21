"""Adaptador de Responses API al loop de herramientas del editor."""

import json
from typing import Any

from openai import OpenAI

from app.agent.loop import MAX_TOKENS, Turn


def response_input(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for message in history:
        content = message["content"]
        if isinstance(content, str):
            items.append(message)
            continue
        for block in content:
            if block["type"] == "openai_output":
                items.extend(block["items"])
            elif block["type"] == "tool_result":
                items.append(
                    {"type": "function_call_output", "call_id": block["tool_use_id"], "output": block["content"]}
                )
    return items


def tool_input(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        parsed = None
    # AgentTools rechaza argumentos desconocidos, incluso para tools sin parámetros.
    return parsed if isinstance(parsed, dict) else {"argumentos_json_invalidos": True}


class OpenAILLM:
    model = "gpt-4.1-mini"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

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
