"""
Amadeus Hotels MCP server entrypoint.

Usage:
    python -m servers.amadeus_hotels              # stdio server (default)
    python -m servers.amadeus_hotels --http       # HTTP server on port 8767
    python -m servers.amadeus_hotels --http --port 9000

Per-server variation is captured in SPEC below. The third auth shape
in mcp-tooling (after Duffel's API key + google-workspace's refresh
token): OAuth2 client credentials with short-lived access tokens.

This server is also the proof that the ServerSpec extraction (PR #44)
handles a third auth shape without modification.
"""

import argparse

from runtime.server_spec import ServerSpec, run_server
from servers.amadeus_hotels.client import AmadeusClient
from servers.amadeus_hotels.tools import (
    AutocompleteHotelNameTool,
    GetHotelRatingsTool,
    ListHotelsByCityTool,
    SearchHotelsTool,
)


def build_client(secrets):
    """Construct an AmadeusClient from the loaded secrets dict.

    Amadeus uses OAuth2 client credentials (different from both Duffel's
    static API key and google-workspace's refresh-token flow). The
    client fetches and refreshes its own access token at request time.
    """
    return AmadeusClient(
        client_id=secrets["AMADEUS_CLIENT_ID"],
        client_secret=secrets["AMADEUS_CLIENT_SECRET"],
        env=secrets.get("AMADEUS_ENV", "test"),
    )


def build_tools(client):
    """Construct the Amadeus hotel-search tool set."""
    return [
        ListHotelsByCityTool(client),
        SearchHotelsTool(client),
        AutocompleteHotelNameTool(client),
        GetHotelRatingsTool(client),
    ]


SPEC = ServerSpec(
    name="amadeus-hotels",
    default_port=8767,
    required_secrets=frozenset({"AMADEUS_CLIENT_ID", "AMADEUS_CLIENT_SECRET", "MCPTOOLING_ALLOWED_TOKENS"}),
    optional_secrets=frozenset({"AMADEUS_ENV"}),
    build_client=build_client,
    build_tools=build_tools,
)


def setup():  # noqa: D401 — kept for backwards compatibility with servers/amadeus_hotels/tests
    """Backwards-compatible thin wrapper around runtime.setup(SPEC).

    The runtime module is the canonical implementation; this function
    exists so existing tests in servers/amadeus_hotels/tests/ can
    keep calling am_main.setup() without changes.
    """
    from runtime.server_spec import setup as runtime_setup

    return runtime_setup(SPEC)


def main() -> None:
    parser = argparse.ArgumentParser(description="Amadeus Hotels MCP server")
    parser.add_argument("--http", action="store_true", help="Run HTTP server instead of stdio")
    parser.add_argument(
        "--port", type=int, default=SPEC.default_port, help=f"HTTP server port (default: {SPEC.default_port})"
    )
    args = parser.parse_args()
    run_server(
        SPEC,
        transport="streamable-http" if args.http else "stdio",
        port=args.port,
    )


if __name__ == "__main__":
    main()
