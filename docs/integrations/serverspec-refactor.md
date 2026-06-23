# ServerSpec refactor — API sketch + plan

This is the design doc for refactoring `servers/<name>/__main__.py`,
the install scripts, and the deploy workflows into a single declarative
shape. Goal: make adding server #3 (and #4, #5, ...) a thin
exercise rather than a 600-line copy-paste.

This is **not** an implementation. It's the design to review before
writing code. Once approved, the refactor lands as a PR (or two), then
server #3 lands against the new pattern.

## Background — what's actually duplicated today

Measured against the duffel + google-workspace `__main__.py` files
(after PR #42):

| File | Lines today |
| --- | --- |
| `servers/duffel/__main__.py` | 141 |
| `servers/google_workspace/__main__.py` | 199 |
| `scripts/deploy/install-vm.sh` | 130 |
| `scripts/deploy/install-google-workspace-vm.sh` | 186 |
| `.github/workflows/deploy-duffel-hetzner.yml` | 131 |
| `.github/workflows/deploy-google-workspace-hetzner.yml` | 139 |

After `ServerSpec`, the new `__main__.py` files are ~40-70 lines (the
duffel one collapses the most; google-workspace stays bigger because of
the scope policy). After the deploy refactor, the per-server workflow
files disappear entirely (replaced by `config/servers/<name>.yaml`
entries).

## The API

`ServerSpec` is a single dataclass in `runtime/server_spec.py`. It
captures everything that's per-server. The runtime provides `run(spec)`
which handles everything else.

```python
# runtime/server_spec.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from runtime.base import BaseTool


@dataclass(frozen=True)
class ServerSpec:
    """
    Declarative spec for a single MCP server.

    Pass one of these to runtime.run_server() and you get a working
    stdio or streamable-http MCP server with secrets loaded, scope
    policy enforced, tools registered, allowlist built, health
    endpoint exposed, and graceful shutdown wired up.
    """

    # Identity (used in logs, systemd unit name, health endpoint output)
    name: str                                  # e.g. "duffel"
    default_port: int                          # e.g. 8765

    # Secrets schema (used by runtime.secrets.load_secrets under the hood)
    required_secrets: frozenset[str]           # e.g. {"DUFFEL_API_KEY", "MCPTOOLING_ALLOWED_TOKENS"}
    optional_secrets: frozenset[str] = frozenset()

    # OAuth scope policy (None for API-key servers)
    # If provided, validate_scopes() is called before any tool registers;
    # SystemExit(2) on violation. scope_guard is a thin wrapper around
    # servers/<name>/scope_guard.py for OAuth servers.
    scope_policy: ScopePolicy | None = None

    # Client construction. Takes the loaded secrets dict (with
    # MCPTOOLING_ALLOWED_TOKENS and any optional secrets), returns
    # whatever the tools need. For duffel: returns a DuffelClient.
    # For google-workspace: returns a GoogleWorkspaceClient.
    build_client: Callable[[dict[str, str]], Any]

    # Tool construction. Takes the client (or anything build_client
    # returned), returns the list of BaseTool instances to register.
    build_tools: Callable[[Any], list[BaseTool]]

    # Optional per-server customization hooks
    on_startup: Callable[[ToolRegistry, dict[str, str]], None] | None = None
    # Hook for additional stderr logging, e.g. google-workspace's
    # "🔒 OAuth scopes (effective): ..." line. Called after tools register
    # but before serving.

    # Allowlist overrides (rare). Most servers leave this None.
    allow_all_tools: bool = True               # google-workspace: True
                                              # duffel: True (MCPTOOLING_ALLOWED_TOOLS
                                              # can flip this to False at runtime)


@dataclass(frozen=True)
class ScopePolicy:
    """
    OAuth scope policy for a server. Only OAuth servers set this.

    Two flavors:
    - "narrow" (google-workspace, today): ALLOWED_SCOPES is a hardcoded
      list in the server's scope_guard.py. The runtime just calls
      validate_scopes() before registering tools.
    - "dynamic" (future, e.g. a "bring your own scope" server): ALLOWED_SCOPES
      is computed from server config. Not used today; design supports it.
    """
    parse: Callable[[str | None], list[str]]              # raw env value → list of scopes
    validate: Callable[[list[str]], list[str]]            # dedupe + allowlist check
    default_when_unset: list[str]                         # used if env var unset


def run_server(
    spec: ServerSpec,
    *,
    transport: str = "stdio",      # "stdio" | "streamable-http"
    port: int | None = None,
) -> None:
    """
    Run an MCP server from a ServerSpec.

    Equivalent to the body of <name>/__main__.py today, minus the
    server-specific bits captured in `spec`.

    Exit codes:
      0 — clean shutdown
      1 — secrets missing or invalid
      2 — scope policy violation
      Other — propagated from uvicorn/asyncio
    """
```

### Why a dataclass, not a YAML config

- YAML config adds a second source of truth: the spec file *and* the
  Python code. Drift is inevitable.
- Callbacks (`build_client`, `build_tools`) need Python anyway — clients
  wrap an HTTP library, tools wrap a client. YAML can't express them
  without becoming a DSL.
- A dataclass gives full type-checker support and is testable with plain
  pytest. No new validator needed.
- If we ever want config-driven behavior, we can add a `ServerSpec.from_yaml(...)`
  factory later. Dataclass-first, config-file-second is the right order.

### Why not just a base class with hooks

- Base classes force inheritance. A spec dataclass lets a server be
  assembled from functions, which is easier to test (pass a fake
  `build_client` in unit tests) and easier to compose (multiple
  `build_client` variants for test/prod).
- Specs are values; you can pass them around, log them, serialize them.

## What each existing server would look like after the refactor

### Duffel — `servers/duffel/__main__.py` after

```python
"""Duffel MCP server entrypoint."""

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


def build_client(secrets: dict[str, str]) -> DuffelClient:
    return DuffelClient(
        api_key=secrets["DUFFEL_API_KEY"],
        base_url=secrets.get("DUFFEL_API_URL", "https://api.duffel.com"),
    )


def build_tools(client: DuffelClient):
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
    parser.add_argument("--port", type=int, default=SPEC.default_port)
    args = parser.parse_args()
    run_server(
        SPEC,
        transport="streamable-http" if args.http else "stdio",
        port=args.port,
    )


if __name__ == "__main__":
    main()
```

~40 lines vs. 141 today. The spec is the entire server's worth of
variation, on one screen.

### Google Workspace — `servers/google_workspace/__main__.py` after

```python
"""Google Workspace MCP server entrypoint."""

import argparse

from runtime.server_spec import ServerSpec, ScopePolicy, run_server
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
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


SCOPE_POLICY = ScopePolicy(
    parse=_parse_scopes,
    validate=validate_scopes,
    default_when_unset=sorted(ALLOWED_SCOPES),
)


def build_client(secrets: dict[str, str]) -> GoogleWorkspaceClient:
    raw_scopes = secrets.get("GOOGLE_WORKSPACE_SCOPES")
    parsed = SCOPE_POLICY.parse(raw_scopes)
    if parsed:
        effective = SCOPE_POLICY.validate(parsed)
    else:
        effective = SCOPE_POLICY.default_when_unset
    return GoogleWorkspaceClient(
        client_id=secrets["GOOGLE_WORKSPACE_CLIENT_ID"],
        client_secret=***"GOOGLE_WORKSPACE_CLIENT_SECRET"],
        refresh_token=***"GOOGLE_WORKSPACE_REFRESH_TOKEN"],
        scopes=effective,
    )


def build_tools(client):
    return [
        GetDocumentTool(client),
        CreateDocumentTool(client),
        DriveListFilesTool(client),
        DriveCreateFileTool(client),
        DriveUpdateFileTool(client),
    ]


def _log_scopes(registry, secrets):
    print(f"🔒 OAuth scopes: {secrets.get('GOOGLE_WORKSPACE_SCOPES') or 'narrow defaults'}", file=__import__('sys').stderr)


SPEC = ServerSpec(
    name="google-workspace",
    default_port=8766,
    required_secrets=frozenset({
        "GOOGLE_WORKSPACE_CLIENT_ID",
        "GOOGLE_WORKSPACE_CLIENT_SECRET",
        "GOOGLE_WORKSPACE_REFRESH_TOKEN",
        "MCPTOOLING_ALLOWED_TOKENS",
    }),
    optional_secrets=frozenset({"GOOGLE_WORKSPACE_SCOPES", "GOOGLE_WORKSPACE_PROJECT_ID"}),
    scope_policy=SCOPE_POLICY,
    build_client=build_client,
    build_tools=build_tools,
    on_startup=_log_scopes,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Google Workspace MCP server")
    parser.add_argument("--http", action="store_true", help="Run HTTP server instead of stdio")
    parser.add_argument("--port", type=int, default=SPEC.default_port)
    args = parser.parse_args()
    run_server(
        SPEC,
        transport="streamable-http" if args.http else "stdio",
        port=args.port,
    )


if __name__ == "__main__":
    main()
```

Still ~70 lines (more than duffel because of scope policy), but the
*shape* is now identical to duffel. The per-server variation is
visible and testable.

## The install script refactor

`scripts/deploy/install-mcp-server.sh` is a single generic script that
takes env vars and renders the right systemd unit + secrets file. The
per-server scripts (`install-vm.sh`, `install-google-workspace-vm.sh`)
are replaced by env-var-driven calls to the generic script.

```bash
#!/usr/bin/env bash
# scripts/deploy/install-mcp-server.sh
# Generic installer for any MCP server. Reads MCP_SERVER_* env vars
# and renders systemd unit + secrets file + scope guard (if OAuth).
#
# Required env vars:
#   MCP_SERVER_NAME            e.g. "duffel"
#   MCP_SERVER_PORT            e.g. 8765
#   MCP_SERVER_SECRETS         space-separated required secret names
#   MCP_SERVER_SCOPE_GUARD     "true" to enable OAuth scope guard, else unset
#
# The secrets themselves are passed by the deploy workflow as
# MCP_SERVER_SECRET_<KEY>=value, forwarded to /etc/mcp-tooling/secrets.env.
```

Deploy workflow calls it like:

```yaml
- name: Install google-workspace
  env:
    MCP_SERVER_NAME: google-workspace
    MCP_SERVER_PORT: 8766
    MCP_SERVER_SECRETS: "GOOGLE_WORKSPACE_CLIENT_ID GOOGLE_WORKSPACE_CLIENT_SECRET GOOGLE_WORKSPACE_REFRESH_TOKEN"
    MCP_SERVER_SCOPE_GUARD: "true"
    MCP_SERVER_REQUIRED_SCOPES: "https://www.googleapis.com/auth/drive.file,https://www.googleapis.com/auth/documents"
    GOOGLE_WORKSPACE_CLIENT_ID: *** secrets.GOOGLE_WORKSPACE_CLIENT_ID }}
    GOOGLE_WORKSPACE_CLIENT_SECRET: *** secrets.GOOGLE_WORKSPACE_CLIENT_SECRET }}
    GOOGLE_WORKSPACE_REFRESH_TOKEN: *** secrets.GOOGLE_WORKSPACE_REFRESH_TOKEN }}
    MCPTOOLING_ALLOWED_TOKENS: ${{ secrets.MCPTOOLING_ALLOWED_TOKENS }}
  run: bash scripts/deploy/install-mcp-server.sh
```

This is the bigger refactor — generic install script + reusable deploy
workflow. It also touches `linux-desktop-seed` (the deploy side), so
this should land as a coordinated change.

## The deploy workflow refactor

The two existing `deploy-*-hetzner.yml` workflows collapse into one
caller:

```yaml
# .github/workflows/deploy-mcp-server.yml
name: Deploy MCP server to Hetzner

on:
  workflow_dispatch:
    inputs:
      server_name:
        description: 'Server name (e.g. duffel, google-workspace)'
        required: true
      action: { ... }
      environment: { ... }
      force: { ... }

jobs:
  setup: { ... }                # same as today
  apply: { ... }                # delegates to reusable-terraform-apply in infra-actions
  deploy:
    needs: [setup, apply]
    uses: DarojaAI/infra-actions/.github/workflows/reusable-hetzner-deploy.yml@main
    with:
      server_ip: ${{ needs.apply.outputs.server_ip }}
      server_name: ${{ needs.setup.outputs.server_name }}
      environment: ${{ inputs.environment }}
      remote_path: /opt/mcp-tooling
      install_script: scripts/deploy/install-mcp-server.sh
      health_endpoint: /healthz
      health_port: ${{ vars.MCP_SERVER_PORT }}    # NEW: per-server
    secrets:
      SSH_PRIVATE_KEY: *** secrets.SSH_PRIVATE_KEY }}
      # NEW: MCP_SERVER_* env vars forwarded from a per-server config file
      # (e.g. config/servers/<name>.yaml). The reusable reads this file
      # and forwards each secret as an env var to the install script.
```

Per-server configuration lives in `config/servers/<name>.yaml`:

```yaml
# config/servers/google-workspace.yaml
server_name: google-workspace
port: 8766
required_secrets:
  - GOOGLE_WORKSPACE_CLIENT_ID
  - GOOGLE_WORKSPACE_CLIENT_SECRET
  - GOOGLE_WORKSPACE_REFRESH_TOKEN
  - MCPTOOLING_ALLOWED_TOKENS
scope_guard:
  enabled: true
  required_scopes:
    - https://www.googleapis.com/auth/drive.file
    - https://www.googleapis.com/auth/documents
```

The deploy workflow reads this file, forwards the listed secrets to the
installer, and the installer renders the right unit. **One workflow,
many servers.**

## Topic groupings (after we have ≥2 servers per topic)

Don't do this in the refactor PR. Land it as a follow-up once a second
docs server (Notion?) and a second travel server (Amadeus hotels?) exist.

When we do, the shape is:

```
servers/
├── travel/
│   ├── duffel/             # moved from servers/duffel/
│   ├── amadeus_hotels/     # future
│   └── _shared.py          # topic-level scope policy + test fixtures
└── docs/
    ├── google_workspace/   # moved from servers/google_workspace/
    └── notion/             # future
```

Importantly, the package name is `servers.travel.duffel`, which means
`python -m servers.travel.duffel` to run it. **This is a breaking
change** for the deploy workflow's invocation path. The deploy
refactor above handles it — once deploy is generic, the
`MCP_SERVER_PACKAGE` config field controls the Python module path.

## Skills (separate piece, after refactor lands)

Two Skill Workshop proposals worth capturing:

- **`add-mcp-server`** — procedure for adding a new server to
  mcp-tooling using the new `ServerSpec` pattern. Captures the
  decisions codified above.
- **`review-mcp-server-scope-policy`** — procedure for reviewing a PR
  that adds or changes OAuth scopes. The narrow-scope guard logic from
  google-workspace's PR is the canonical case study.

These go in the openclaw skill registry, not in this repo. They help
the agent (me, future agents) do the work; they're not code in
mcp-tooling.

## Refactor plan — order of PRs

1. **PR #43: extract `ServerSpec` + `run_server`.** New file
   `runtime/server_spec.py`. Refactor `servers/duffel/__main__.py` and
   `servers/google_workspace/__main__.py` to use it. All 103 existing
   tests must still pass; no behavior changes. This is the load-bearing
   refactor; do not skip the test gate.

2. **PR #44: generic install script + reusable deploy workflow.**
   - `scripts/deploy/install-mcp-server.sh` (new).
   - `scripts/deploy/install-vm.sh` and
     `scripts/deploy/install-google-workspace-vm.sh` get deleted
     (replaced by env-var calls to the generic script in the deploy
     workflow).
   - `.github/workflows/deploy-mcp-server.yml` (new, reusable).
   - `.github/workflows/deploy-duffel-hetzner.yml` and
     `.github/workflows/deploy-google-workspace-hetzner.yml` get
     deleted (replaced by callers of the reusable).
   - `config/servers/duffel.yaml` and
     `config/servers/google-workspace.yaml` (new).
   - **This PR also needs a coordinated change in
     `DarojaAI/infra-actions`** (the reusable deploy caller must accept
     the new env-var forwarding contract) and in `linux-desktop-seed`
     (the dat-contract-side mirror).
   - The new `reusable-hetzner-deploy.yml` in infra-actions lives
     there; we just consume it from mcp-tooling.

3. **PR #45: add server #3 (Amadeus hotels or Notion).** This is the
   proof — if the refactor in #43 + #44 holds, adding a server is
   <300 lines of new code (one `__main__.py`, one client, one tool
   module per tool, one `config/servers/<name>.yaml`).

4. **PR #46 (later, after ≥2 servers per topic exist): topic
   groupings.** Move `servers/duffel/` → `servers/travel/duffel/`,
   etc. Update deploy config. **Only do this if the topic has real
   shared code** (scope policy, test fixtures, topic doc).

5. **Separate piece, in parallel: Skill Workshop proposals** for
   `add-mcp-server` and `review-mcp-server-scope-policy`. These help
   future agents; they don't block PRs #43-46.

## Risks and how to handle them

- **Risk: `ServerSpec` is wrong, we can't represent server #3 with it.**
  Two ways to detect early: (a) sketch the spec for the next obvious
  server (Amadeus hotels, which is search-only with API-key auth and
  no scope policy) before merging #43. If it fits cleanly, the spec is
  right. (b) Don't merge #43 until #44 (the deploy refactor) is also
  designed — they need to fit together.

- **Risk: the generic install script becomes its own complex thing.**
  Mitigation: bash, not Python. envsubst, not templating. If we need
  more, the install is already at its limit and we should switch to a
  Python installer in the venv.

- **Risk: linux-desktop-seed coordination.** The deploy refactor
  changes how secrets are forwarded; that needs a matching change in
  linux-desktop-seed's contract + deploy workflow. Plan it as a
  joint PR sequence, not a single-PR surprise.

- **Risk: scope creep.** "While we're here, let's also do topic
  groupings / add Notion / add a CLI / etc." Topic groupings are PR
  #46 (later). Server #3 is PR #45 (the proof). Don't bundle them
  with #43 or #44.

## Open questions for review

- Is `build_client` / `build_tools` the right granularity? Alternative
  is a single `build_registry(secrets) -> ToolRegistry` function that
  does both. Pros of two functions: easier to unit-test the client
  construction separately. Pros of one: less indirection. I'd lean
  two-function but it's a judgment call.

- Should `run_server` accept the scope policy's `default_when_unset`
  as a `default` env-var name (`GOOGLE_WORKSPACE_SCOPES`) instead of
  as a list? The current design has the list hardcoded in the spec,
  which is what we want for narrow-scope servers but might be too
  rigid for a future "operator-configured scopes" server. I'd keep
  the list-in-spec for now; revisit when we have a server that needs
  runtime-configured scopes.

- Where does the per-server BATS test for the install script live?
  Today it's `tests/bats/install-google-workspace.bats`. After the
  refactor, it's `tests/bats/install-mcp-server.bats` with one test
  per scope-guard mode (off + each OAuth allowlist). I'd add a
  per-server override file (`tests/bats/install-google-workspace.bats`)
  that asserts the specific OAuth scope policy is wired in. Same
  pattern as the per-server pytest suite.

## What's deliberately NOT in scope for this refactor

- YAML-driven server config. The dataclass is the source of truth.
- Code generation. We don't have enough repetition to justify it.
- Topic groupings (PR #46).
- Skill Workshop proposals (separate piece).
- Adding any new server. The refactor proves itself; server #3 is the
  proof of proof.

## References

- PR #42 (the google-workspace PR that exposed the duplication):
  https://github.com/DarojaAI/mcp-tooling/pull/42
- `runtime/server_spec.py` — to be added in PR #43
- `docs/authoring-server.md` — to be updated in PR #43 with the new pattern
- `DarojaAI/infra-actions` — owner of the reusable deploy caller
- `DarojaAI/linux-desktop-seed` — owner of the matching contract-side changes