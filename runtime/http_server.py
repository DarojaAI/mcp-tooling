"""
HTTP server for MCP tools using FastAPI.

Provides:
- POST /mcp/execute - Call a tool via HTTP
- GET /healthz - Health check
- CORS allowlist (not wildcard)
"""

from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from runtime.registry import ToolRegistry
from runtime.health import health_report
from runtime.allowlist import Allowlist
import time


class ExecuteRequest(BaseModel):
    """Request body for POST /mcp/execute"""
    tool: str
    args: dict[str, Any]


class ExecuteResponse(BaseModel):
    """Response body for POST /mcp/execute"""
    result: dict[str, Any] | None = None
    error: str | None = None


def create_app(
    registry: ToolRegistry,
    allowlist: Allowlist | None = None,
    allowed_origins: list[str] | None = None,
) -> FastAPI:
    """
    Create a FastAPI app for MCP tool serving.
    
    Args:
        registry: ToolRegistry with registered tools
        allowlist: Optional Allowlist for tool/caller filtering
        allowed_origins: CORS allowed origins (default: ["http://localhost", "http://127.0.0.1"])
    
    Returns:
        FastAPI app instance
    """
    start_time = time.time()
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifespan context manager (startup/shutdown hooks)."""
        # Startup
        yield
        # Shutdown
        pass
    
    app = FastAPI(
        title="MCP Tooling HTTP Server",
        description="HTTP transport for MCP tools",
        version="0.1.0",
        lifespan=lifespan,
    )
    
    # CORS middleware (allowlist-based, not wildcard)
    if allowed_origins is None:
        allowed_origins = ["http://localhost", "http://127.0.0.1"]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    
    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        """Health check endpoint."""
        return health_report(start_time, registry)
    
    @app.get("/tools")
    async def list_tools() -> dict[str, Any]:
        """List all registered tools (MCP tools/list format)."""
        return {"tools": registry.list_tools()}
    
    @app.post("/mcp/execute")
    async def execute(
        req: ExecuteRequest,
        authorization: str | None = Header(None),
    ) -> ExecuteResponse:
        """
        Execute a tool via HTTP.
        
        Args:
            req: Tool name + arguments
            authorization: Optional Bearer token for caller allowlist
        
        Returns:
            Tool result or error
        """
        # Allowlist checks
        if allowlist is not None:
            # Check tool name allowlist
            if not allowlist.is_tool_allowed(req.tool):
                raise HTTPException(status_code=403, detail=f"Tool '{req.tool}' not allowed")
            
            # Check caller token allowlist
            token = None
            if authorization and authorization.startswith("Bearer "):
                token = authorization[7:]  # Strip "Bearer " prefix
            
            if not allowlist.is_caller_allowed(token):
                raise HTTPException(status_code=403, detail="Unauthorized caller")
        
        # Execute tool
        try:
            result = await registry.call(req.tool, req.args)
            return ExecuteResponse(result=result)
        except ValueError as e:
            # Validation or tool-not-found error
            return ExecuteResponse(error=str(e))
        except Exception as e:
            # Unexpected error
            return ExecuteResponse(error=f"Internal error: {str(e)}")
    
    return app
