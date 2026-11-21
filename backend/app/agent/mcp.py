"""Branchpoint como servidor MCP (JAJ-54, JAJ-67): las tools del agente para la CLI de IA del usuario.

El loop con el LLM corre en la CLI del usuario (por ejemplo Claude Code con su suscripción) y el
backend solo ejecuta las tools de ``app/agent/tools.py``. Se monta en la API en ``/mcp``:

    claude mcp add --scope user --transport http branchpoint https://<api>/mcp --header "Authorization: Bearer <token>"

**Quién llama.** Con login (``SUPABASE_URL``), cada request trae el token de sesión de Supabase, el
mismo que usa el editor (JAJ-78), y el usuario solo ve sus proyectos. Sin login
(``BRANCHPOINT_AUTH=off``), los proyectos sin dueño. El token de larga duración para emparejar la
CLI es JAJ-81.

**Transporte.** Streamable HTTP sin estado (cada request se valida sola) y respuestas JSON.
``BRANCHPOINT_MCP_ALLOWED_HOSTS`` (separados por coma) son los Host aceptados (protección contra DNS
rebinding). Por defecto, localhost.
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp import types
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.agent.tools import AgentTools, Limiter, ToolError
from app.api.auth import AuthError, SupabaseAuth
from app.api.store import ProjectStore
from app.ingest.ai_graph import AiComponent, AiEndpoint, AiJob, AiObservation

INSTRUCTIONS = (
    "Branchpoint simula la arquitectura de un repo con un motor de eventos discretos y propone cambios. "
    "Empieza con list_projects. Nunca inventes latencias, capacidades ni costos: salen de simulate, compare y "
    "estimate_cost, y cada resultado trae su procedencia (cítala). Los números del usuario (tráfico, metas, "
    "réplicas) van en set_traffic, set_goals y set_deployment con su frase textual en quote; si no los dijo, "
    "pregúntaselos. Para cambiar la arquitectura usa propose_version con operaciones de ops_schema y después "
    "compare con la versión anterior. Cita el archivo:línea del cuello de botella. Si el cambio que piden no está "
    "en ops_schema (por ejemplo una réplica de lectura, una CDN o cambiar de base de datos), di que Branchpoint "
    "todavía no lo simula. No lo aproximes con otra operación sin avisar. "
    "Si el usuario quiere analizar un repo que tienes en local, léelo tú, sea del framework que sea: busca las "
    "rutas, sigue cada handler y clasifica sus accesos a la DB, caché, servicios externos y colas, con "
    "archivo:línea; después mándalo con submit_architecture. No pongas tiempos ni números: los pone el catálogo."
)
DEFAULT_ALLOWED_HOSTS = "localhost:*,127.0.0.1:*,[::1]:*,testserver"


def _bearer(headers: Any) -> str | None:
    scheme, _, token = (headers.get("authorization") or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _error_result(message: str) -> types.CallToolResult:
    payload = {"error": message}
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
    )


class AuthGate:
    """401 antes de MCP si la API tiene login y la request no trae un token válido: así la CLI sabe que
    tiene que mandar el header ``Authorization``."""

    def __init__(self, app: ASGIApp, auth: SupabaseAuth | None) -> None:
        self.app, self.auth = app, auth

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.auth is not None and scope.get("path", "").startswith("/mcp"):
            token = _bearer(Request(scope).headers)
            message = None
            if token is None:
                message = "Falta el token: agrega --header 'Authorization: Bearer <token>' al conectar la CLI."
            else:
                try:
                    self.auth.verify(token)
                except AuthError as e:
                    message = str(e)
            if message:
                await JSONResponse({"error": message}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_mcp(store: ProjectStore, auth: SupabaseAuth | None, limiter: Limiter | None = None) -> MCPServer:
    """El servidor MCP con las tools de ``AgentTools``. Cada llamada resuelve el usuario de su request."""
    limiter = limiter or Limiter()

    def tools_for(ctx: Context | None) -> AgentTools:
        owner = None
        if auth is not None:
            request = ctx.request_context.request if ctx is not None else None
            token = _bearer(request.headers) if request is not None else None
            if token is None:
                raise ToolError("Falta el token de sesión.")
            owner = auth.verify(token).id
        return AgentTools(store, owner, limiter)

    async def validate_arguments(ctx: Any, call_next: Any) -> Any:
        """Rechaza los argumentos desconocidos o mal tipados con ``{"error": ...}``. Sin esto, el SDK de MCP
        descarta en silencio lo que no está en la firma de la tool, y el LLM no sabría que su número se
        ignoró."""
        params = ctx.params if isinstance(ctx.params, dict) else None
        if ctx.method == "tools/call" and params is not None:
            try:
                AgentTools(store, None).validate(params.get("name", ""), params.get("arguments") or {})
            except ToolError as e:
                return _error_result(str(e))
        return await call_next(ctx)

    server = MCPServer(name="branchpoint", instructions=INSTRUCTIONS, middleware=[validate_arguments])

    def run(tool: str, ctx: Context | None, /, **args: Any) -> Any:  # posicionales: hay tools con un arg name
        try:
            tools = tools_for(ctx)
        except (ToolError, AuthError) as e:
            return {"error": str(e)}
        return tools.call(tool, {k: v for k, v in args.items() if v is not None})

    # Una función por tool, con su firma: así el schema que ve el LLM es explícito.
    @server.tool(description=_d("list_projects"))
    def list_projects(ctx: Context) -> Any:
        return run("list_projects", ctx)

    @server.tool(description=_d("get_model"))
    def get_model(project_id: str, ctx: Context, version: int | None = None) -> Any:
        return run("get_model", ctx, project_id=project_id, version=version)

    @server.tool(description=_d("list_assumptions"))
    def list_assumptions(project_id: str, ctx: Context, version: int | None = None) -> Any:
        return run("list_assumptions", ctx, project_id=project_id, version=version)

    @server.tool(description=_d("list_scenarios"))
    def list_scenarios(project_id: str, ctx: Context) -> Any:
        return run("list_scenarios", ctx, project_id=project_id)

    @server.tool(description=_d("simulate"))
    def simulate(
        project_id: str, ctx: Context, version: int | None = None, scenario: str = "cyberday", seed: int = 0
    ) -> Any:
        return run("simulate", ctx, project_id=project_id, version=version, scenario=scenario, seed=seed)

    @server.tool(description=_d("compare"))
    def compare(project_id: str, a: int, b: int, ctx: Context, scenario: str = "cyberday", seed: int = 0) -> Any:
        return run("compare", ctx, project_id=project_id, a=a, b=b, scenario=scenario, seed=seed)

    @server.tool(description=_d("estimate_cost"))
    def estimate_cost(project_id: str, ctx: Context, version: int | None = None) -> Any:
        return run("estimate_cost", ctx, project_id=project_id, version=version)

    @server.tool(description=_d("ops_schema"))
    def ops_schema(ctx: Context) -> Any:
        return run("ops_schema", ctx)

    @server.tool(description=_d("propose_version"))
    def propose_version(
        project_id: str, ops: list[dict[str, Any]], ctx: Context, version: int | None = None, note: str | None = None
    ) -> Any:
        return run("propose_version", ctx, project_id=project_id, ops=ops, version=version, note=note)

    @server.tool(description=_d("set_traffic"))
    def set_traffic(
        project_id: str,
        volume: float,
        unit: str,
        quote: str,
        ctx: Context,
        peak_factor: float | None = None,
        scenario: str = "cyberday",
        version: int | None = None,
    ) -> Any:
        return run(
            "set_traffic",
            ctx,
            project_id=project_id,
            volume=volume,
            unit=unit,
            quote=quote,
            peak_factor=peak_factor,
            scenario=scenario,
            version=version,
        )

    @server.tool(description=_d("set_deployment"))
    def set_deployment(
        project_id: str, field: str, value: str, quote: str, ctx: Context, version: int | None = None
    ) -> Any:
        return run("set_deployment", ctx, project_id=project_id, field=field, value=value, quote=quote, version=version)

    @server.tool(description=_d("set_goals"))
    def set_goals(
        project_id: str,
        quote: str,
        ctx: Context,
        slo_p95_ms: float | None = None,
        slo_error_rate: float | None = None,
        budget_usd_month: float | None = None,
    ) -> Any:
        return run(
            "set_goals",
            ctx,
            project_id=project_id,
            quote=quote,
            slo_p95_ms=slo_p95_ms,
            slo_error_rate=slo_error_rate,
            budget_usd_month=budget_usd_month,
        )

    @server.tool(description=_d("submit_architecture"))
    def submit_architecture(
        repo: str,
        framework: str,
        language: str,
        endpoints: list[AiEndpoint],
        ctx: Context,
        components: list[AiComponent] | None = None,
        jobs: list[AiJob] | None = None,
        observations: list[AiObservation] | None = None,
        commit: str | None = None,
        project_id: str | None = None,
        name: str | None = None,
    ) -> Any:
        return run(
            "submit_architecture",
            ctx,
            repo=repo,
            framework=framework,
            language=language,
            endpoints=[e.model_dump() for e in endpoints],
            components=[c.model_dump() for c in components] if components else None,
            jobs=[j.model_dump() for j in jobs] if jobs else None,
            observations=[o.model_dump() for o in observations] if observations else None,
            commit=commit,
            project_id=project_id,
            name=name,
        )

    return server


def _d(name: str) -> str:
    from app.agent.tools import TOOL_DESCRIPTIONS

    return TOOL_DESCRIPTIONS[name]


def mcp_asgi_app(server: MCPServer, auth: SupabaseAuth | None) -> ASGIApp:
    """La app ASGI de ``/mcp``: streamable HTTP sin estado, con respuestas JSON y la puerta de auth."""
    hosts = [h.strip() for h in os.environ.get("BRANCHPOINT_MCP_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS).split(",")]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection="*" not in hosts,
        allowed_hosts=[h for h in hosts if h],
        allowed_origins=[],
    )
    app = server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True, transport_security=security
    )
    return AuthGate(app, auth)
