"""
MCP stdio server implementation.

Wraps the official mcp Python SDK's stdio transport for tool serving.
"""

import asyncio
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server

from runtime.registry import ToolRegistry


async def start_stdio_server(registry: ToolRegistry) -> None:
    """
    Start an MCP server over stdio transport.
    
    Args:
        registry: ToolRegistry with registered tools
    
    This function blocks until the stdio connection closes.
    """
    server = Server("mcp-tooling")
    
    @server.list_tools()
    async def list_tools() -> list[dict[str, Any]]:
        """Handle tools/list requests."""
        return registry.list_tools()
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Handle tools/call requests.
        
        Returns:
            List of content blocks (MCP protocol format)
        """
        try:
            result = await registry.call(name, arguments)
            
            # Wrap result in MCP content format
            return [
                {
                    "type": "text",
                    "text": str(result),
                }
            ]
        except ValueError as e:
            # Validation or tool-not-found error
            return [
                {
                    "type": "text",
                    "text": f"Error: {str(e)}",
                }
            ]
        except Exception as e:
            # Unexpected error
            return [
                {
                    "type": "text",
                    "text": f"Internal error: {str(e)}",
                }
            ]
    
    # Run the stdio server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main(registry: ToolRegistry) -> None:
    """
    Main entry point for stdio servers.
    
    Usage:
        if __name__ == "__main__":
            registry = ToolRegistry()
            registry.register(MyTool())
            main(registry)
    """
    try:
        asyncio.run(start_stdio_server(registry))
    except KeyboardInterrupt:
        print("\nShutting down stdio server", file=sys.stderr)
