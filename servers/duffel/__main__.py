"""
Duffel MCP server entrypoint.

Usage:
    python -m servers.duffel              # stdio server (default)
    python -m servers.duffel --http       # HTTP server on port 8765
    python -m servers.duffel --http --port 9000  # HTTP server on custom port
"""

import argparse
import asyncio
import sys
from pathlib import Path

from runtime.registry import ToolRegistry
from runtime.stdio_server import start_stdio_server
from runtime.http_server import create_app
from runtime.secrets import load_secrets
from runtime.allowlist import Allowlist
from servers.duffel.client import DuffelClient
from servers.duffel.tools import (
    SearchFlightsTool,
    GetOfferTool,
    BookFlightTool,
    GetBookingTool,
    CancelBookingTool,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Duffel MCP server")
    parser.add_argument("--http", action="store_true", help="Run HTTP server instead of stdio")
    parser.add_argument("--port", type=int, default=8765, help="HTTP server port (default: 8765)")
    args = parser.parse_args()
    
    # Load secrets
    try:
        secrets = load_secrets(
            required_keys={
                "DUFFEL_API_KEY",
                "MCPTOOLING_ALLOWED_TOKENS",
            },
            optional_keys={
                "DUFFEL_API_URL",
                "MCPTOOLING_CONFIRM_BOOKING",
                "MCPTOOLING_CONFIRM_DESTRUCTIVE",
            },
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Hint: Set MCPTOOLING_SECRETS_PATH or create /etc/mcp-tooling/secrets.env", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Create Duffel client
    duffel_client = DuffelClient(
        api_key=secrets["DUFFEL_API_KEY"],
        base_url=secrets.get("DUFFEL_API_URL", "https://api.duffel.com"),
    )
    
    # Create tool registry
    registry = ToolRegistry()
    registry.register(SearchFlightsTool(duffel_client))
    registry.register(GetOfferTool(duffel_client))
    registry.register(BookFlightTool(duffel_client))
    registry.register(GetBookingTool(duffel_client))
    registry.register(CancelBookingTool(duffel_client))
    
    print(f"✅ Registered {len(registry)} Duffel tools", file=sys.stderr)
    for tool_name in [t.tool_name for t in registry._tools.values()]:
        print(f"   - {tool_name}", file=sys.stderr)
    
    if args.http:
        # HTTP server
        import uvicorn
        
        allowlist = Allowlist.from_env()
        app = create_app(registry, allowlist=allowlist)
        
        print(f"🚀 Starting Duffel MCP HTTP server on port {args.port}", file=sys.stderr)
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    else:
        # stdio server
        print("🚀 Starting Duffel MCP stdio server", file=sys.stderr)
        await start_stdio_server(registry)


if __name__ == "__main__":
    asyncio.run(main())
