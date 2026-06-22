"""
Google Workspace MCP server entrypoint.

Usage:
    python -m servers.google_workspace              # stdio server (default)
    python -m servers.google_workspace --http       # HTTP server on port 8766
    python -m servers.google_workspace --http --port 9000

Required env (loaded from MCPTOOLING_SECRETS_PATH or /etc/mcp-tooling/secrets.env):
    GOOGLE_WORKSPACE_CLIENT_ID
    GOOGLE_WORKSPACE_CLIENT_SECRET
    GOOGLE_WORKSPACE_REFRESH_TOKEN
    MCPTOOLING_ALLOWED_TOKENS

Optional:
    GOOGLE_WORKSPACE_SCOPES     Comma-separated OAuth scopes. If unset, the
                                full narrow allowlist is used. If set, every
                                scope must be in ALLOWED_SCOPES — otherwise
                                the server refuses to start (scope guard).
    GOOGLE_WORKSPACE_PROJECT_ID  For diagnostics only; not validated.
    MCPTOOLING_PORT             HTTP port (default: 8766 — distinct from
                                duffel's 8765 so they can coexist on one host)
"""

import argparse
import asyncio
import sys

from runtime.allowlist import Allowlist
from runtime.registry import ToolRegistry
from runtime.secrets import load_secrets
from runtime.stdio_server import start_stdio_server
from runtime.streamable_http_server import create_streamable_http_app
from servers.google_workspace.client import GoogleWorkspaceClient, ScopePolicyError
from servers.google_workspace.scope_guard import validate_scopes
from servers.google_workspace.tools import (
    CreateDocumentTool,
    DriveCreateFileTool,
    DriveListFilesTool,
    DriveUpdateFileTool,
    GetDocumentTool,
)

DEFAULT_PORT = 8766


def _parse_scopes(raw: str | None) -> list[str]:
    """Parse GOOGLE_WORKSPACE_SCOPES (comma-separated) into a list."""
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def setup() -> tuple[ToolRegistry, Allowlist, dict[str, str]]:
    """
    Load secrets, validate scopes, build tool registry, build allowlist.

    Returns:
        (registry, allowlist, diagnostics) ready to serve.

    Raises:
        SystemExit: if secrets are missing/invalid, or if scopes violate
                    the narrow-scope policy.
    """
    try:
        secrets = load_secrets(
            required_keys={
                "GOOGLE_WORKSPACE_CLIENT_ID",
                "GOOGLE_WORKSPACE_CLIENT_SECRET",
                "GOOGLE_WORKSPACE_REFRESH_TOKEN",
                "MCPTOOLING_ALLOWED_TOKENS",
            },
            optional_keys={
                "GOOGLE_WORKSPACE_SCOPES",
                "GOOGLE_WORKSPACE_PROJECT_ID",
            },
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Hint: Set MCPTOOLING_SECRETS_PATH or create /etc/mcp-tooling/secrets.env", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Scope guard — runs before any tool registration. A misconfigured
    # server cannot start and silently expose extra capabilities.
    #
    # Two cases:
    #   1. GOOGLE_WORKSPACE_SCOPES unset → use the narrow defaults (empty
    #      list to client, which expands to ALLOWED_SCOPES).
    #   2. GOOGLE_WORKSPACE_SCOPES set → every scope must be in
    #      ALLOWED_SCOPES. Anything broader (gmail, calendar, full drive)
    #      is rejected before any tool is registered.
    configured_scopes = _parse_scopes(secrets.get("GOOGLE_WORKSPACE_SCOPES"))
    if configured_scopes:
        try:
            effective_scopes = validate_scopes(configured_scopes)
        except ScopePolicyError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        # Unset → fall through to client-side defaults (the narrow allowlist).
        effective_scopes = []

    try:
        gw_client = GoogleWorkspaceClient(
            client_id=secrets["GOOGLE_WORKSPACE_CLIENT_ID"],
            client_secret=secrets["GOOGLE_WORKSPACE_CLIENT_SECRET"],
            refresh_token=secrets["GOOGLE_WORKSPACE_REFRESH_TOKEN"],
            scopes=effective_scopes,
            project_id=secrets.get("GOOGLE_WORKSPACE_PROJECT_ID"),
        )
    except ScopePolicyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # noqa: BLE001 — last-ditch validation guard
        print(f"Error: Failed to initialize Google Workspace client: {e}", file=sys.stderr)
        sys.exit(1)

    registry = ToolRegistry()
    registry.register(GetDocumentTool(gw_client))
    registry.register(CreateDocumentTool(gw_client))
    registry.register(DriveListFilesTool(gw_client))
    registry.register(DriveCreateFileTool(gw_client))
    registry.register(DriveUpdateFileTool(gw_client))

    print(f"✅ Registered {len(registry)} Google Workspace tools", file=sys.stderr)
    for tool_name in [t.tool_name for t in registry._tools.values()]:
        print(f"   - {tool_name}", file=sys.stderr)
    print(
        f"🔒 OAuth scopes (effective): {gw_client.scopes} "
        f"(configured: {configured_scopes or 'unset → narrow defaults'})",
        file=sys.stderr,
    )

    # Allowlist — same shape as duffel.
    tokens_str = secrets["MCPTOOLING_ALLOWED_TOKENS"]
    allowed_tokens = set(t.strip() for t in tokens_str.split(",") if t.strip())
    allowlist = Allowlist(
        allowed_tokens=allowed_tokens,
        allow_all_tools=True,
    )

    diagnostics = {
        "scopes": gw_client.scopes,
        "configured_scopes": configured_scopes,
        "project_id": secrets.get("GOOGLE_WORKSPACE_PROJECT_ID", ""),
    }
    return registry, allowlist, diagnostics


def run_http(registry: ToolRegistry, allowlist: Allowlist, port: int) -> None:
    """Run the HTTP server (synchronous entrypoint for uvicorn).

    Mirror of duffel's run_http — stateless streamable-http, DNS-rebinding
    protection disabled because the gateway hits this over the public
    network; bearer-token auth is the real gate.
    """
    import uvicorn

    app = create_streamable_http_app(
        registry,
        allowlist=allowlist,
        json_response=True,
        stateless=True,
        disable_dns_rebinding_protection=True,
    )
    print(f"🚀 Starting Google Workspace MCP streamable-http server on port {port}", file=sys.stderr)
    uvicorn.run(app, host="0.0.0.0", port=port)


async def run_stdio(registry: ToolRegistry) -> None:
    """Run the stdio server (asynchronous entrypoint)."""
    print("🚀 Starting Google Workspace MCP stdio server", file=sys.stderr)
    await start_stdio_server(registry)


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Workspace MCP server")
    parser.add_argument("--http", action="store_true", help="Run HTTP server instead of stdio")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"HTTP server port (default: {DEFAULT_PORT})",
    )
    args = parser.parse_args()

    registry, allowlist, _diagnostics = setup()

    if args.http:
        run_http(registry, allowlist, args.port)
    else:
        asyncio.run(run_stdio(registry))


if __name__ == "__main__":
    main()
