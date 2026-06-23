"""
Duffel MCP server entrypoint.

Usage:
    python -m servers.duffel              # stdio server (default)
    python -m servers.duffel --http       # HTTP server on port 8765
    python -m servers.duffel --http --port 9000

Refactored against runtime.ServerSpec (see runtime/server_spec.py +
docs/integrations/serverspec-refactor.md). Per-server variation is
captured in SPEC below.
"""

import argparse

from runtime.server_spec import ServerSpec, run_server
from servers.duffel.client import DuffelClient
from servers.duffel.tools import (
    BookFlightTool,
    CancelBookingTool,
    GetBookingTool,
    GetOfferTool,
    SearchFlightsTool,
)


def build_client(secrets):
    """Construct a DuffelClient from the loaded secrets dict."""
    return DuffelClient(
        api_key=secrets["DUFFEL_API_KEY"],
        base_url=secrets.get("DUFFEL_API_URL", "https://api.duffel.com"),
    )


def build_tools(client):
    """Construct the Duffel tool set. Returns a list of BaseTool instances."""
    return [
        SearchFlightsTool(client),
        GetOfferTool(client),
        BookFlightTool(client),
        GetBookingTool(client),
        CancelBookingTool(client),
    ]


SPEC = ServerSpec(
    name="duffel",
    default_port=8765,
    required_secrets=frozenset({"DUFFEL_API_KEY", "MCPTOOLING_ALLOWED_TOKENS"}),
    optional_secrets=frozenset({"DUFFEL_API_URL", "MCPTOOLING_CONFIRM_BOOKING", "MCPTOOLING_CONFIRM_DESTRUCTIVE"}),
    build_client=build_client,
    build_tools=build_tools,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Duffel MCP server")
    parser.add_argument("--http", action="store_true", help="Run HTTP server instead of stdio")
    parser.add_argument("--port", type=int, default=SPEC.default_port, help=f"HTTP server port (default: {SPEC.default_port})")
    args = parser.parse_args()
    run_server(
        SPEC,
        transport="streamable-http" if args.http else "stdio",
        port=args.port,
    )


if __name__ == "__main__":
    main()