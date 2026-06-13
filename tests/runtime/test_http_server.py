"""Tests for runtime.http_server"""

import pytest
from fastapi.testclient import TestClient
from runtime.http_server import create_app
from runtime.registry import ToolRegistry
from runtime.base import BaseTool
from runtime.allowlist import Allowlist


class EchoTool(BaseTool):
    """Echo tool for testing."""
    
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
            "properties": {
                "message": {"type": "string"},
            },
            "required": ["message"],
        }
    
    async def call(self, args: dict) -> dict:
        return {"echo": args["message"]}


def test_healthz_endpoint():
    """Test /healthz endpoint."""
    registry = ToolRegistry()
    app = create_app(registry)
    client = TestClient(app)
    
    response = client.get("/healthz")
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "healthy"
    assert "uptime_seconds" in data
    assert data["tools_registered"] == 0


def test_list_tools_endpoint():
    """Test /tools endpoint."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    
    app = create_app(registry)
    client = TestClient(app)
    
    response = client.get("/tools")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data["tools"]) == 1
    assert data["tools"][0]["name"] == "echo"


def test_execute_endpoint():
    """Test /mcp/execute endpoint."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    
    app = create_app(registry)
    client = TestClient(app)
    
    response = client.post("/mcp/execute", json={
        "tool": "echo",
        "args": {"message": "hello world"},
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["echo"] == "hello world"
    assert data["error"] is None


def test_execute_invalid_args():
    """Test /mcp/execute with invalid arguments."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    
    app = create_app(registry)
    client = TestClient(app)
    
    response = client.post("/mcp/execute", json={
        "tool": "echo",
        "args": {},  # Missing required 'message'
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["result"] is None
    assert "Invalid arguments" in data["error"]


def test_execute_nonexistent_tool():
    """Test /mcp/execute with nonexistent tool."""
    registry = ToolRegistry()
    app = create_app(registry)
    client = TestClient(app)
    
    response = client.post("/mcp/execute", json={
        "tool": "nonexistent",
        "args": {},
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["result"] is None
    assert "not found" in data["error"]


def test_execute_with_allowlist():
    """Test /mcp/execute with allowlist enforcement."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    
    allowlist = Allowlist(
        allowed_tools={"echo"},
        allowed_tokens={"valid-token"},
    )
    
    app = create_app(registry, allowlist=allowlist)
    client = TestClient(app)
    
    # Without token - should fail
    response = client.post("/mcp/execute", json={
        "tool": "echo",
        "args": {"message": "hello"},
    })
    assert response.status_code == 403
    
    # With valid token - should succeed
    response = client.post(
        "/mcp/execute",
        json={"tool": "echo", "args": {"message": "hello"}},
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 200
    
    # With invalid token - should fail
    response = client.post(
        "/mcp/execute",
        json={"tool": "echo", "args": {"message": "hello"}},
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 403


def test_execute_tool_not_in_allowlist():
    """Test /mcp/execute with tool not in allowlist."""
    registry = ToolRegistry()
    registry.register(EchoTool())
    
    allowlist = Allowlist(
        allowed_tools={"other_tool"},  # echo not allowed
        allowed_tokens={"valid-token"},
    )
    
    app = create_app(registry, allowlist=allowlist)
    client = TestClient(app)
    
    response = client.post(
        "/mcp/execute",
        json={"tool": "echo", "args": {"message": "hello"}},
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 403
    assert "not allowed" in response.json()["detail"]
