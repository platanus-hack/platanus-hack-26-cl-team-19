"""JAJ-54: verifica el servidor MCP como lo usaría una CLI de IA, sin LLM ni credenciales.

Se conecta por streamable HTTP (lo mismo que `claude mcp add --transport http`), lista las tools y
hace las llamadas que haría el agente ante "¿qué pasa en CyberDay?": simular y proponer un cambio.

    python spikes/jaj-54-byos/mcp_server.py         # en otra terminal, o con & al final
    python spikes/jaj-54-byos/check_client.py
"""

from __future__ import annotations

import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8765/mcp"
EXAMPLE = "full-stack-fastapi-template"


def payload(result) -> object:
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    return json.loads(result.content[0].text)


async def main() -> None:
    async with streamable_http_client(URL) as (read, write, *_):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])

            sim = payload(await session.call_tool("simulate", {"example": EXAMPLE, "scenario": "cyberday"}))
            print("\nsimulate cyberday:", json.dumps(sim, ensure_ascii=False, indent=1)[:900])

            bad = payload(
                await session.call_tool("propose", {"example": EXAMPLE, "ops": [{"op": "scale_api", "replicas": 0}]})
            )
            assert "replicas" in bad.get("error", ""), bad
            print("\npropose inválido (el LLM lo lee y corrige):", bad)

            prop = payload(
                await session.call_tool(
                    "propose", {"example": EXAMPLE, "ops": [{"op": "scale_api", "replicas": 4}], "scenario": "cyberday"}
                )
            )
            print("\npropose scale_api ×4:")
            print(" changes:", prop["changes"])
            print(" p95 ms:", prop["p95_ms"], "| errores:", prop["error_rate"])
            print(" cuello antes:", prop["before"]["bottleneck"]["message"])
            print(" cuello después:", prop["after"]["bottleneck"]["message"])
            cost = prop["usd_month"]["after"]
            assert cost["label"] and cost["source"], cost  # el costo también trae procedencia
            print(
                " US$/mes:",
                prop["usd_month"]["before"]["value"],
                "->",
                cost["value"],
                f"({cost['label']}: {cost['source']})",
            )
            print(" procedencia:", prop["after"]["provenance"]["label"], "|", prop["after"]["provenance"]["source"])

            no_quote = payload(
                await session.call_tool(
                    "propose",
                    {"example": EXAMPLE, "ops": [{"op": "add_cache", "endpoint": "GET /users/", "hit_ratio": 0.9}]},
                )
            )
            assert "quote" in no_quote.get("error", ""), no_quote
            print("\npropose add_cache sin quote (dato del usuario):", no_quote["error"])

            bad_scenario = payload(await session.call_tool("simulate", {"example": EXAMPLE, "scenario": "blackfriday"}))
            assert "error" in bad_scenario, bad_scenario
            print("simulate con escenario inexistente:", bad_scenario["error"])

            # simulate no tiene rps en su schema: un número inventado por el LLM se descarta
            sneaky = payload(await session.call_tool("simulate", {"example": EXAMPLE, "rps": 5000}))
            assert sneaky["rps"] == sim["rps"], "simulate usó un rps que no viene del escenario"
            print(f"\nsimulate con rps=5000 inventado: usa {sneaky['rps']} req/s, la tasa del escenario")


if __name__ == "__main__":
    asyncio.run(main())
