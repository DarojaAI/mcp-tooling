"""
ServerSpec + run_server: declarative MCP server entrypoint.

Each server in servers/<name>/ declares a ServerSpec (a frozen dataclass
capturing name, port, secrets schema, optional OAuth scope policy,
build_client + build_tools callbacks) and calls run_server(spec) from
its __main__.py. Everything else — secrets loading, scope validation,
tool registration, allowlist building, stdio vs streamable-http
transport, graceful shutdown — is handled here.

Why a dataclass + callbacks (not YAML, not a base class):
  - YAML adds a second source of truth and a second validator.
  - Callbacks (build_client, build_tools) are Python anyway, so
    there's no abstraction savings in moving them to config.
  - A dataclass is fully type-checkable and trivially unit-testable:
    pass fake build_client/build_tools in tests, no real API needed.
  - If we ever want config-driven behavior, we can add
    ServerSpec.from_yaml(...) later. Dataclass-first is the right order.

Scope policy:
  - Non-OAuth servers (API keys, tokens, etc.) leave spec.scope_policy
    as None. No validation runs.
  - OAuth servers pass a ScopePolicy with:
      - parse(env_value) -> list[str]
      - validate(list[str]) -> list[str]   (raises on disallowed)
      - default_when_unset: list[str]      (used if env var unset)
    run_server calls parse(), then validate() if non-empty, BEFORE
    build_client is called. A failed validation raises SystemExit(2)
    without registering any tools.

Exit codes (preserved from pre-refactor server behavior):
  0 — clean shutdown
  1 — secrets missing/invalid
  2 — scope policy violation
  Other — propagated from uvicorn/asyncio
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from runtime.allowlist import Allowlist
from runtime.base import BaseTool
from runtime.registry import ToolRegistry
from runtime.secrets import load_secrets
from runtime.stdio_server import start_stdio_server
from runtime.streamable_http_server import create_streamable_http_app

# Type aliases (kept short for readability in spec declarations)
SecretDict = dict[str, str]
BuildClient = Callable[..., Any]  # see ServerSpec.build_client for the canonical signature
BuildTools = Callable[[Any], list[BaseTool]]
StartupHook = Callable[[ToolRegistry, SecretDict], None]


@dataclass(frozen=True)
class ScopePolicy:
    """
    OAuth scope policy for an MCP server.

    Used by run_server() to validate OAuth scopes BEFORE any tool is
    registered. The validation flow:
      1. raw = secrets.get(scope_env_var)
      2. configured = parse(raw) -> list[str]
      3. If configured is non-empty: validate(configured) -> list[str]
         (raises on disallowed scope; run_server catches and exits 2)
      4. If configured is empty: effective = default_when_unset
    """

    scope_env_var: str
    parse: Callable[[str | None], list[str]]
    validate: Callable[[list[str]], list[str]]
    default_when_unset: list[str]


@dataclass(frozen=True)
class ServerSpec:
    """
    Declarative spec for a single MCP server.

    See module docstring for design rationale.
    """

    name: str
    default_port: int
    required_secrets: frozenset[str]
    optional_secrets: frozenset[str] = frozenset()
    scope_policy: ScopePolicy | None = None
    build_client: BuildClient | None = None
    # Canonical signature: build_client(secrets: SecretDict, *, scopes: list[str] | None = None) -> Any
    # Non-OAuth servers ignore the scopes kwarg; OAuth servers receive the
    # validated effective scopes via scopes= and pass them to the API client.
    build_tools: BuildTools | None = None
    on_startup: StartupHook | None = None
    allow_all_tools: bool = True


# ---------------------------------------------------------------------------
# Public API: setup (testable) + run (entrypoint)
# ---------------------------------------------------------------------------


def setup(
    spec: ServerSpec,
) -> tuple[ToolRegistry, Allowlist, dict[str, Any]]:
    """
    Load secrets, apply scope policy, build the registry and allowlist.

    Returns:
        (registry, allowlist, diagnostics) ready to serve.

    Raises:
        SystemExit(1): if secrets are missing/invalid.
        SystemExit(2): if OAuth scopes violate the scope_policy.

    This is the testable entrypoint — `setup(spec)` is what server
    unit tests call. It is also what `run_server(spec, ...)` calls
    internally before starting a transport.
    """
    try:
        secrets = load_secrets(
            required_keys=set(spec.required_secrets),
            optional_keys=set(spec.optional_secrets),
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Hint: Set MCPTOOLING_SECRETS_PATH or create /etc/mcp-tooling/secrets.env", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Scope policy: applied BEFORE build_client so a misconfigured OAuth
    # server cannot register any tools. configured_scopes is recorded
    # for diagnostics so server logs + tests can assert what was used.
    configured_scopes: list[str] = []
    effective_scopes: list[str] = []
    if spec.scope_policy is not None:
        raw_scope_value = secrets.get(spec.scope_policy.scope_env_var)
        configured_scopes = spec.scope_policy.parse(raw_scope_value)
        if configured_scopes:
            try:
                effective_scopes = spec.scope_policy.validate(configured_scopes)
            except Exception as e:  # noqa: BLE001 — scope_policy.validate raises typed errors
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(2)
        else:
            effective_scopes = list(spec.scope_policy.default_when_unset)

    # Build client. OAuth servers receive the validated effective scopes;
    # non-OAuth servers get scopes=None.
    if spec.build_client is None:
        raise RuntimeError(
            f"ServerSpec for '{spec.name}' has no build_client callback"
        )
    if spec.build_tools is None:
        raise RuntimeError(
            f"ServerSpec for '{spec.name}' has no build_tools callback"
        )
    if spec.scope_policy is not None:
        client = spec.build_client(secrets, scopes=effective_scopes)
    else:
        client = spec.build_client(secrets)

    # Build tools.
    tools = spec.build_tools(client)
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)

    print(f"✅ Registered {len(registry)} {spec.name} tools", file=sys.stderr)
    for tool_name in [t.tool_name for t in registry._tools.values()]:
        print(f"   - {tool_name}", file=sys.stderr)
    if spec.scope_policy is not None:
        print(
            f"🔒 OAuth scopes (effective): {effective_scopes} "
            f"(configured: {configured_scopes or 'unset → narrow defaults'})",
            file=sys.stderr,
        )

    # Allowlist.
    tokens_str = secrets["MCPTOOLING_ALLOWED_TOKENS"]
    allowed_tokens = set(t.strip() for t in tokens_str.split(",") if t.strip())
    if spec.allow_all_tools:
        allowlist = Allowlist(
            allowed_tokens=allowed_tokens,
            allow_all_tools=True,
        )
    else:
        # Honor an optional MCPTOOLING_ALLOWED_TOOLS override.
        tools_str = secrets.get("MCPTOOLING_ALLOWED_TOOLS", "")
        allowed_tools = set(t.strip() for t in tools_str.split(",") if t.strip()) if tools_str else set()
        allowlist = Allowlist(
            allowed_tools=allowed_tools,
            allowed_tokens=allowed_tokens,
            allow_all_tools=False,
        )

    # Optional on_startup hook — used by google-workspace for extra
    # stderr logging, etc. Called after tools are registered.
    if spec.on_startup is not None:
        spec.on_startup(registry, secrets)

    diagnostics: dict[str, Any] = {
        "name": spec.name,
        "tool_count": len(registry),
        "scopes": effective_scopes,
        "configured_scopes": configured_scopes,
    }
    return registry, allowlist, diagnostics


def run_server(
    spec: ServerSpec,
    *,
    transport: str = "stdio",
    port: int | None = None,
) -> None:
    """
    Run an MCP server from a ServerSpec.

    Args:
        spec: The ServerSpec to run.
        transport: "stdio" (default) or "streamable-http".
        port: HTTP port (required for streamable-http; ignored for stdio).
              Defaults to spec.default_port if not provided.

    Raises:
        SystemExit: per the exit codes in the module docstring.
    """
    if transport not in ("stdio", "streamable-http"):
        print(f"Error: Unknown transport '{transport}'", file=sys.stderr)
        sys.exit(1)

    registry, allowlist, _diagnostics = setup(spec)

    if transport == "streamable-http":
        http_port = port if port is not None else spec.default_port
        run_http(registry, allowlist, spec.name, http_port)
    else:
        asyncio.run(run_stdio(registry, spec.name))


def run_http(registry: ToolRegistry, allowlist: Allowlist, name: str, port: int) -> None:
    """Start the streamable-http transport (synchronous, uvicorn entrypoint)."""
    import uvicorn

    app = create_streamable_http_app(
        registry,
        allowlist=allowlist,
        json_response=True,
        stateless=True,
        disable_dns_rebinding_protection=True,
    )
    print(f"🚀 Starting {name} MCP streamable-http server on port {port}", file=sys.stderr)
    uvicorn.run(app, host="0.0.0.0", port=port)


async def run_stdio(registry: ToolRegistry, name: str) -> None:
    """Start the stdio transport (asynchronous)."""
    print(f"🚀 Starting {name} MCP stdio server", file=sys.stderr)
    await start_stdio_server(registry)