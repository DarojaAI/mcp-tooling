"""
MCP streamable-http server using the official MCP SDK's FastMCP.

Provides a real MCP streamable-http endpoint that speaks proper
JSON-RPC 2.0 (initialize, tools/list, tools/call, etc.).

Wraps FastMCP's streamable_http_app() with a FastAPI shell so we
keep the existing /healthz and /tools convenience endpoints plus
the same allowlist + CORS semantics as the old wrapper.

Implementation note: FastMCP's streamable_http_app() registers its
session-manager lifespan on a Starlette instance. When we mount that
under FastAPI, the lifespan event doesn't reach FastMCP's app (Starlette
only drives lifespan for the OUTERMOST Starlette app). So we drive
FastMCP's session manager ourselves from FastAPI's lifespan — same
effect, correct lifecycle.
"""

import inspect as _inspect
import json
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from mcp.server.fastmcp import FastMCP

from runtime.allowlist import Allowlist
from runtime.health import health_report
from runtime.registry import ToolRegistry


def _register_tools(fastmcp: FastMCP, registry: ToolRegistry) -> None:
    """Mirror registry tools into FastMCP.

    For each tool we build a handler whose signature and annotations
    match the tool's input_schema. FastMCP derives the JSON schema from
    the type hints, so callers see the same input shape they'd see
    over stdio or via the registry.
    """
    for tool in registry.list_tools():
        tool_name = tool["name"]
        description = tool.get("description", "")
        input_schema = tool.get("inputSchema", {"type": "object", "properties": {}})
        properties = input_schema.get("properties", {})
        required = set(input_schema.get("required", []))

        params = []
        annotations: dict[str, Any] = {"return": str}
        for pname, pschema in properties.items():
            ptype = pschema.get("type", "string")
            py_type = {
                "string": str,
                "integer": int,
                "number": float,
                "boolean": bool,
                "array": list,
                "object": dict,
            }.get(ptype, str)
            default = _inspect.Parameter.empty if pname in required else None
            params.append(
                _inspect.Parameter(
                    name=pname,
                    kind=_inspect.Parameter.KEYWORD_ONLY,
                    annotation=py_type,
                    default=default,
                )
            )
            annotations[pname] = py_type

        # Build the handler inside a factory function so each iteration
        # gets its own lexical scope (avoids late-binding closure bugs).
        def make_handler(bound_tool_name: str):
            async def handler(**kwargs) -> str:
                args = {k: v for k, v in kwargs.items() if v is not None}
                result = await registry.call(bound_tool_name, args)
                return str(result)
            return handler

        handler = make_handler(tool_name)

        if params:
            handler.__signature__ = _inspect.Signature(parameters=params)
        handler.__annotations__ = annotations
        handler.__name__ = tool_name

        fastmcp.add_tool(handler, name=tool_name, description=description)


def create_streamable_http_app(
    registry: ToolRegistry,
    allowlist: Allowlist | None = None,
    allowed_origins: list[str] | None = None,
    mcp_path: str = "/mcp",
    json_response: bool = False,
    stateless: bool = False,
    disable_dns_rebinding_protection: bool = False,
) -> FastAPI:
    """
    Create a FastAPI app that speaks real MCP streamable-http.

    Args:
        registry: ToolRegistry with registered tools
        allowlist: Optional Allowlist for tool/caller filtering
        allowed_origins: CORS allowed origins
        mcp_path: URL path for the MCP streamable-http endpoint
        json_response: Return JSON instead of SSE
        stateless: No session persistence between requests
        disable_dns_rebinding_protection: Disable FastMCP's DNS-rebinding
            protection. Only enable in tests behind trusted infra; production
            deployments should leave the default (loopback-only hosts).

    Returns:
        FastAPI app instance
    """
    start_time = time.time()

    fastmcp = FastMCP(
        name="mcp-tooling",
        instructions="MCP tool servers for OpenClaw agents",
    )
    _register_tools(fastmcp, registry)
    fastmcp.settings.json_response = json_response
    fastmcp.settings.stateless_http = stateless
    fastmcp.settings.streamable_http_path = mcp_path

    if disable_dns_rebinding_protection:
        from mcp.server.transport_security import TransportSecuritySettings

        fastmcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )

    if allowed_origins is None:
        allowed_origins = ["http://localhost", "http://127.0.0.1"]

    # Trigger lazy session_manager creation so we can drive its lifespan
    # directly from FastAPI's lifespan (Mount doesn't propagate lifespan).
    mcp_asgi_app = fastmcp.streamable_http_app()
    session_manager = fastmcp.session_manager
    assert session_manager is not None, "FastMCP failed to create session manager"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with session_manager.run():
            yield

    app = FastAPI(
        title="MCP Tooling HTTP Server",
        description="MCP streamable-http transport for MCP tools",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id", "Last-Event-ID"],
    )

    @app.middleware("http")
    async def allowlist_gate(request: Request, call_next):
        if request.url.path == mcp_path or request.url.path.startswith(mcp_path + "/"):
            if allowlist is not None:
                auth = request.headers.get("authorization", "")
                token = auth[7:] if auth.startswith("Bearer ") else None
                if not allowlist.is_caller_allowed(token):
                    return JSONResponse(
                        status_code=403,
                        content={"error": "Unauthorized caller"},
                    )
        return await call_next(request)

    @app.api_route(
        mcp_path,
        methods=["GET", "POST", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def mcp_endpoint(request: Request) -> Response:
        """Bridge the request to FastMCP's ASGI app."""
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": request.method,
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.path.encode(),
            "query_string": request.url.query.encode(),
            "root_path": "",
            "headers": [
                (k.lower().encode(), v.encode())
                for k, v in request.headers.items()
            ],
            "client": (request.client.host, request.client.port) if request.client else None,
            "server": (request.url.hostname or "localhost", request.url.port or 80),
        }

        body = b""
        if request.method in ("POST", "DELETE"):
            body = await request.body()

        receive_calls = {"done": False}

        async def receive():
            if not receive_calls["done"]:
                receive_calls["done"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        response_status = 500
        response_headers: list[tuple[bytes, bytes]] = []
        response_body = bytearray()
        started = False

        async def send(message):
            nonlocal response_status, started
            if message["type"] == "http.response.start":
                started = True
                response_status = message.get("status", 200)
                response_headers[:] = message.get("headers", [])
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        await mcp_asgi_app(scope, receive, send)

        if not started:
            return Response(content=b"", status_code=500)

        content_type = "application/octet-stream"
        for k, v in response_headers:
            if k.lower() == b"content-type":
                content_type = v.decode()
                break

        out_headers = {
            k.decode(): v.decode()
            for k, v in response_headers
            if k.lower() not in (b"content-length", b"content-type")
        }

        return Response(
            content=bytes(response_body),
            status_code=response_status,
            headers=out_headers,
            media_type=content_type,
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return health_report(start_time, registry)

    @app.get("/tools")
    async def list_tools_http() -> dict[str, Any]:
        """List all registered tools (non-MCP convenience endpoint)."""
        return {"tools": registry.list_tools()}

    return app
