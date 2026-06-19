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

from runtime.allowlist import Allowlist
from runtime.registry import ToolRegistry
from runtime.secrets import load_secrets
from runtime.stdio_server import start_stdio_server
from runtime.streamable_http_server import create_streamable_http_app
from servers.duffel.client import DuffelClient
from servers.duffel.tools import (
    BookFlightTool,
    CancelBookingTool,
    GetBookingTool,
    GetOfferTool,
    SearchFlightsTool,
)


def setup() -> tuple[ToolRegistry, Allowlist]:
    """
    Load secrets, build tool registry, and build allowlist.

    Returns:
        (registry, allowlist) ready to serve.

    Raises:
        SystemExit: if secrets are missing or invalid.
    """
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

    duffel_client = DuffelClient(
        api_key=secrets["DUFFEL_API_KEY"],
        base_url=secrets.get("DUFFEL_API_URL", "https://api.duffel.com"),
    )

    registry = ToolRegistry()
    registry.register(SearchFlightsTool(duffel_client))
    registry.register(GetOfferTool(duffel_client))
    registry.register(BookFlightTool(duffel_client))
    registry.register(GetBookingTool(duffel_client))
    registry.register(CancelBookingTool(duffel_client))

    print(f"✅ Registered {len(registry)} Duffel tools", file=sys.stderr)
    for tool_name in [t.tool_name for t in registry._tools.values()]:
        print(f"   - {tool_name}", file=sys.stderr)

    # Build allowlist from the same tokens we just loaded (MCPTOOLING_ALLOWED_TOKENS
    # in the secrets file is the canonical source — don't require a second env var).
    tokens_str = secrets["MCPTOOLING_ALLOWED_TOKENS"]
    allowed_tokens = set(t.strip() for t in tokens_str.split(",") if t.strip())
    tools_str = secrets.get("MCPTOOLING_ALLOWED_TOOLS", "")
    if tools_str:
        allowed_tools = set(t.strip() for t in tools_str.split(",") if t.strip())
        allowlist = Allowlist(
            allowed_tools=allowed_tools,
            allowed_tokens=allowed_tokens,
            allow_all_tools=False,
        )
    else:
        allowlist = Allowlist(
            allowed_tokens=allowed_tokens,
            allow_all_tools=True,
        )

    return registry, allowlist


def run_http(registry: ToolRegistry, allowlist: Allowlist, port: int) -> None:
    """Run the HTTP server (synchronous entrypoint for uvicorn).

    Uses the official MCP SDK's streamable-http transport so the gateway
    can speak proper MCP protocol (initialize, tools/list, tools/call)
    instead of the legacy {tool, args} REST wrapper.

    DNS-rebinding protection is disabled because the gateway hits this
    server over the public network (the default FastMCP allowlist only
    permits loopback hosts). Bearer-token auth is the real gate.
    """
    import uvicorn

    app = create_streamable_http_app(
        registry,
        allowlist=allowlist,
        json_response=True,
        stateless=False,
        disable_dns_rebinding_protection=True,
    )
    print(f"🚀 Starting Duffel MCP streamable-http server on port {port}", file=sys.stderr)
    uvicorn.run(app, host="0.0.0.0", port=port)


async def run_stdio(registry: ToolRegistry) -> None:
    """Run the stdio server (asynchronous entrypoint)."""
    print("🚀 Starting Duffel MCP stdio server", file=sys.stderr)
    await start_stdio_server(registry)


def main() -> None:
    parser = argparse.ArgumentParser(description="Duffel MCP server")
    parser.add_argument("--http", action="store_true", help="Run HTTP server instead of stdio")
    parser.add_argument("--port", type=int, default=8765, help="HTTP server port (default: 8765)")
    args = parser.parse_args()

    registry, allowlist = setup()

    if args.http:
        run_http(registry, allowlist, args.port)
    else:
        asyncio.run(run_stdio(registry))


if __name__ == "__main__":
    main()
