"""Tests for runtime.streamable_http_server

Verifies the MCP streamable-http transport speaks proper JSON-RPC 2.0:
initialize, tools/list, tools/call with the right envelopes.

Note: TestClient must be used as a context manager so that the FastAPI
lifespan event fires — that lifespan drives FastMCP's
StreamableHTTPSessionManager.run().
"""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from runtime.allowlist import Allowlist
from runtime.base import BaseTool
from runtime.registry import ToolRegistry
from runtime.streamable_http_server import create_streamable_http_app


class EchoTool(BaseTool):
    @property
    def tool_name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo the input"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }

    async def call(self, args: dict) -> dict:
        return {"echo": args["message"]}


class CalcTool(BaseTool):
    @property
    def tool_name(self) -> str:
        return "calc"

    @property
    def description(self) -> str:
        return "Add two numbers"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        }

    async def call(self, args: dict) -> dict:
        return {"sum": args["a"] + args["b"]}


@contextmanager
def client_for(app) -> Iterator[TestClient]:
    """Wrap TestClient so the lifespan (session manager) starts."""
    with TestClient(app) as client:
        yield client


def test_healthz_endpoint():
    registry = ToolRegistry()
    registry.register(EchoTool())
    app = create_streamable_http_app(registry)
    with client_for(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["tools_registered"] == 1


def test_list_tools_endpoint():
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(CalcTool())
    app = create_streamable_http_app(registry)
    with client_for(app) as client:
        response = client.get("/tools")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tools"]) == 2
        names = {t["name"] for t in data["tools"]}
        assert names == {"echo", "calc"}


def test_mcp_initialize():
    registry = ToolRegistry()
    registry.register(EchoTool())
    app = create_streamable_http_app(registry, stateless=True, json_response=True, disable_dns_rebinding_protection=True)
    with client_for(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert "result" in body
        assert body["result"]["protocolVersion"] == "2025-03-26"


def test_mcp_tools_list():
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(CalcTool())
    app = create_streamable_http_app(registry, stateless=True, json_response=True, disable_dns_rebinding_protection=True)
    with client_for(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert "result" in body
        tools = {t["name"]: t for t in body["result"]["tools"]}
        assert "echo" in tools
        assert "calc" in tools
        assert "message" in tools["echo"]["inputSchema"]["properties"]


def test_mcp_tools_call_echo():
    registry = ToolRegistry()
    registry.register(EchoTool())
    app = create_streamable_http_app(registry, stateless=True, json_response=True, disable_dns_rebinding_protection=True)
    with client_for(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"message": "hello world"}},
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        result = body["result"]
        assert result["isError"] is False
        text = result["content"][0]["text"]
        assert "hello world" in text


def test_mcp_tools_call_calc():
    registry = ToolRegistry()
    registry.register(CalcTool())
    app = create_streamable_http_app(registry, stateless=True, json_response=True, disable_dns_rebinding_protection=True)
    with client_for(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "calc", "arguments": {"a": 7, "b": 35}},
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        result = body["result"]
        assert result["isError"] is False
        text = result["content"][0]["text"]
        assert "42" in text


def test_mcp_unknown_tool():
    registry = ToolRegistry()
    registry.register(EchoTool())
    app = create_streamable_http_app(registry, stateless=True, json_response=True, disable_dns_rebinding_protection=True)
    with client_for(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "nonexistent", "arguments": {}},
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        result = body["result"]
        assert result["isError"] is True


def test_mcp_allowlist_rejects_unauthorized():
    registry = ToolRegistry()
    registry.register(EchoTool())
    allowlist = Allowlist(allowed_tokens={"valid-token"})
    app = create_streamable_http_app(registry, allowlist=allowlist, stateless=True, json_response=True, disable_dns_rebinding_protection=True)
    with client_for(app) as client:
        # No token — should be rejected at the gate
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"message": "hi"}},
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 403

        # Valid token — should succeed
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"message": "hi"}},
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": "Bearer valid-token",
            },
        )
        assert response.status_code == 200


def test_independent_handlers_no_closure_aliasing():
    """Regression test: each tool must hit its own handler, not share via closure."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(CalcTool())
    app = create_streamable_http_app(registry, stateless=True, json_response=True, disable_dns_rebinding_protection=True)
    with client_for(app) as client:
        # echo must hit EchoTool, not CalcTool
        r1 = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"message": "abc"}},
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert r1.status_code == 200
        text = r1.json()["result"]["content"][0]["text"]
        assert "abc" in text
        assert "sum" not in text

        # calc must hit CalcTool, not EchoTool
        r2 = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "calc", "arguments": {"a": 2, "b": 3}},
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert r2.status_code == 200
        text = r2.json()["result"]["content"][0]["text"]
        assert "5" in text
