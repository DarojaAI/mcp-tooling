"""
vm_ops MCP server entrypoint.

Exposes host diagnostics (read-only) and gated destructive ops
(restart_service, kill_process) on the same VM it runs on.

Usage:
    python -m servers.vm_ops              # stdio server (default)
    python -m servers.vm_ops --http       # HTTP server on port 8768
    python -m servers.vm_ops --http --port 9000

Refactored against runtime.ServerSpec (see runtime/server_spec.py +
docs/integrations/serverspec-refactor.md). Per-server variation is
captured in SPEC below.

vm_ops has no client object — the tools call out to the host directly
via ``servers.vm_ops.host_command``. ``build_client`` returns a
sentinel dict so the spec dataclass stays satisfied.
"""

import argparse

from runtime.server_spec import ServerSpec, run_server
from servers.vm_ops.tools import (
    CheckDiskTool,
    GetServiceStatusTool,
    GetSystemInfoTool,
    KillProcessTool,
    ListListeningPortsTool,
    ListProcessesTool,
    RestartServiceTool,
    TailLogsTool,
)


def build_client(_secrets):
    """No external API client for vm_ops — the tools call the host
    directly. Return a sentinel dict so ServerSpec is happy.
    """
    return {}


def build_tools(_client):
    """Construct the vm_ops tool set. Returns a list of BaseTool instances."""
    return [
        GetSystemInfoTool(),
        TailLogsTool(),
        ListProcessesTool(),
        ListListeningPortsTool(),
        CheckDiskTool(),
        GetServiceStatusTool(),
        RestartServiceTool(),
        KillProcessTool(),
    ]


SPEC = ServerSpec(
    name="vm_ops",
    default_port=8768,
    required_secrets=frozenset({"MCPTOOLING_ALLOWED_TOKENS"}),
    optional_secrets=frozenset({"MCPTOOLING_CONFIRM_DESTRUCTIVE"}),
    build_client=build_client,
    build_tools=build_tools,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="vm-ops MCP server (host diagnostics + gated destructive ops)")
    parser.add_argument("--http", action="store_true", help="Run HTTP server instead of stdio")
    parser.add_argument(
        "--port",
        type=int,
        default=SPEC.default_port,
        help=f"HTTP server port (default: {SPEC.default_port})",
    )
    args = parser.parse_args()
    run_server(
        SPEC,
        transport="streamable-http" if args.http else "stdio",
        port=args.port,
    )


if __name__ == "__main__":
    main()
