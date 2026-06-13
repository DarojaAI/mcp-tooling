"""
Health check reporting for MCP servers.
"""

import time
from typing import Any
from runtime.registry import ToolRegistry


def health_report(start_time: float, registry: ToolRegistry) -> dict[str, Any]:
    """
    Generate a health report for /healthz endpoints.
    
    Args:
        start_time: Server start time (time.time())
        registry: ToolRegistry with registered tools
    
    Returns:
        Health report dict
    """
    uptime_seconds = time.time() - start_time
    
    return {
        "status": "healthy",
        "version": "0.1.0",
        "uptime_seconds": round(uptime_seconds, 2),
        "tools_registered": len(registry),
        "tools": [tool.tool_name for tool in registry._tools.values()],
    }
