"""
MCP Tooling Runtime Framework

This package provides the core abstractions for building MCP servers:
- BaseTool: Base class for all tools
- ToolRegistry: Register and dispatch tools
- stdio_server: MCP stdio transport
- http_server: FastAPI HTTP transport
- allowlist: Tool and caller allowlisting
- secrets: Environment variable loading
- health: Health check endpoint
"""

from runtime.base import BaseTool
from runtime.registry import ToolRegistry

__all__ = ["BaseTool", "ToolRegistry"]
