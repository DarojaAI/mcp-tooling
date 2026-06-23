"""
Google Workspace MCP server entrypoint.

Usage:
    python -m servers.google_workspace              # stdio server (default)
    python -m servers.google_workspace --http       # HTTP server on port 8766
    python -m servers.google_workspace --http --port 9000

Refactored against runtime.ServerSpec (see runtime/server_spec.py +
docs/integrations/serverspec-refactor.md). Per-server variation is
captured in SPEC below.

Scope policy: SCOPE_POLICY uses servers/google_workspace/scope_guard.py
as the single source of truth for ALLOWED_SCOPES. The runtime applies
the policy before build_client() is called, so a misconfigured server
cannot register any tools.
"""

import argparse

from runtime.server_spec import ScopePolicy, ServerSpec, run_server
from servers.google_workspace.client import GoogleWorkspaceClient
from servers.google_workspace.scope_guard import ALLOWED_SCOPES, validate_scopes
from servers.google_workspace.tools import (
    CreateDocumentTool,
    DriveCreateFileTool,
    DriveListFilesTool,
    DriveUpdateFileTool,
    GetDocumentTool,
)


def _parse_scopes(raw: str | None) -> list[str]:
    """Parse GOOGLE_WORKSPACE_SCOPES (comma-separated) into a list."""
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


SCOPE_POLICY = ScopePolicy(
    scope_env_var="GOOGLE_WORKSPACE_SCOPES",
    parse=_parse_scopes,
    validate=validate_scopes,
    default_when_unset=sorted(ALLOWED_SCOPES),
)


def build_client(secrets, *, scopes=None):
    """Construct a GoogleWorkspaceClient.

    Receives the validated effective scopes from the runtime when a
    ScopePolicy is in play. If scopes is None (unset config), the
    client falls back to its own narrow-default behavior.
    """
    return GoogleWorkspaceClient(
        client_id=secrets["GOOGLE_WORKSPACE_CLIENT_ID"],
        client_secret=secrets["GOOGLE_WORKSPACE_CLIENT_SECRET"],
        refresh_token=secrets["GOOGLE_WORKSPACE_REFRESH_TOKEN"],
        scopes=list(scopes) if scopes else None,
        project_id=secrets.get("GOOGLE_WORKSPACE_PROJECT_ID"),
    )


def build_tools(client):
    """Construct the Google Workspace tool set."""
    return [
        GetDocumentTool(client),
        CreateDocumentTool(client),
        DriveListFilesTool(client),
        DriveCreateFileTool(client),
        DriveUpdateFileTool(client),
    ]


SPEC = ServerSpec(
    name="google-workspace",
    default_port=8766,
    required_secrets=frozenset(
        {
            "GOOGLE_WORKSPACE_CLIENT_ID",
            "GOOGLE_WORKSPACE_CLIENT_SECRET",
            "GOOGLE_WORKSPACE_REFRESH_TOKEN",
            "MCPTOOLING_ALLOWED_TOKENS",
        }
    ),
    optional_secrets=frozenset({"GOOGLE_WORKSPACE_SCOPES", "GOOGLE_WORKSPACE_PROJECT_ID"}),
    scope_policy=SCOPE_POLICY,
    build_client=build_client,
    build_tools=build_tools,
)


def setup():  # noqa: D401 — kept for backwards compatibility with servers/google_workspace/tests
    """Backwards-compatible thin wrapper around runtime.setup(SPEC).

    The runtime module is the canonical implementation; this function
    exists so existing tests in servers/google_workspace/tests/ can
    keep calling gw_main.setup() without changes.
    """
    from runtime.server_spec import setup as runtime_setup

    return runtime_setup(SPEC)


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Workspace MCP server")
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
