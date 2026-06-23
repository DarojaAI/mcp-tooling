# MCP integration shapes — config-driven decisions

This document captures the decision tree for adding a new MCP server
capability to OpenClaw. The point: **pick the right integration shape
based on what's available, and let environment variables drive the
configuration** — not per-server code.

## Why this matters now

After the google-workspace server (#42) and the ServerSpec refactor
(#44), adding server #3 looks like a clean exercise. But the trivago
question exposed something: **not every MCP capability needs code in
this repo.**

The current pattern (duffel, google-workspace, soon Amadeus) is
**self-hosted capability adapter** — Python code, install script,
systemd, port allocated. That works when:

- The API needs a long-lived refresh-token OAuth flow (Google).
- We need to wrap a non-MCP API in MCP tools (Duffel REST → MCP tools).
- We need server-side logic (caching, aggregation, custom auth).

But when a vendor ships their **own remote MCP server**, the right
answer is "tell the gateway to connect to it" — zero code in this
repo. That's the trivago case.

The configuration has to support both, and ideally *make the right
choice obvious* from the environment variables alone.

## The integration-shape taxonomy

Five shapes, ranked by how much code we write in mcp-tooling:

### Shape 1: Self-hosted capability adapter (current pattern)

- **What:** Python code in `servers/<name>/`, install script, systemd
  unit, port allocated.
- **When:** API needs custom auth, server-side logic, or there's no
  upstream MCP server.
- **Examples:** duffel (API key), google-workspace (refresh-token OAuth),
  amadeus-hotels (OAuth client credentials). Three auth shapes, one
  ServerSpec.
- **Code cost:** ~500 lines (server) + ~150 (install) + ~150 (deploy
  workflow) per server. After the ServerSpec refactor, ~150 lines per
  server.
- **Lifecycle:** Owned by mcp-tooling. Deploy via Hetzner workflow.
- **Config (env vars):**
  ```bash
  MCPTOOLING_SERVER_<NAME>_ENABLED=true
  MCPTOOLING_SERVER_<NAME>_PORT=8767
  MCPTOOLING_SERVER_<NAME>_SECRETS="API_KEY,API_URL"   # names of required secrets
  MCPTOOLING_SERVER_<NAME>_OAUTH_SCOPES="..."         # if OAuth
  # The secrets themselves (API_KEY=...) live in secrets.env, loaded by the
  # install script via load_secrets().
  ```

### Shape 2: Remote MCP server, no auth

- **What:** A URL the gateway points at. No code in this repo.
- **When:** The vendor publishes an MCP server at a public URL with no
  auth requirement.
- **Examples:** trivago (`https://mcp.trivago.com/mcp`).
- **Code cost:** ~10 lines of config.
- **Lifecycle:** Owned by the vendor. We just configure the connection.
- **Config (env vars):**
  ```bash
  MCPTOOLING_REMOTE_<NAME>_URL=https://mcp.vendor.com/mcp
  MCPTOOLING_REMOTE_<NAME>_TRANSPORT=streamable-http
  ```

### Shape 3: Remote MCP server, with API key auth

- **What:** URL + bearer/API-key header. No code in this repo.
- **When:** Vendor publishes an MCP server that requires a static key.
- **Examples:** Hypothetical. Many B2B MCP servers will land here.
- **Code cost:** ~15 lines of config.
- **Lifecycle:** Owned by the vendor; we manage the key.
- **Config (env vars):**
  ```bash
  MCPTOOLING_REMOTE_<NAME>_URL=https://mcp.vendor.com/mcp
  MCPTOOLING_REMOTE_<NAME>_AUTH_TYPE=bearer
  MCPTOOLING_REMOTE_<NAME>_AUTH_TOKEN=<from secrets.env>
  ```

### Shape 4: Remote MCP server, with OAuth

- **What:** URL + OAuth flow (refresh token or device-code). Gateway
  handles the token exchange.
- **When:** Vendor publishes an MCP server that requires user OAuth.
- **Examples:** Hypothetical. Google / Microsoft will land here once
  they ship public MCP servers (today they only have Dev ones).
- **Code cost:** ~20 lines of config + a small OAuth bootstrap helper
  in the gateway.
- **Lifecycle:** Owned by the vendor; we manage the refresh token.
- **Config (env vars):**
  ```bash
  MCPTOOLING_REMOTE_<NAME>_URL=https://mcp.vendor.com/mcp
  MCPTOOLING_REMOTE_<NAME>_OAUTH_CLIENT_ID=<from secrets.env>
  MCPTOOLING_REMOTE_<NAME>_OAUTH_CLIENT_SECRET=<from secrets.env>
  MCPTOOLING_REMOTE_<NAME>_OAUTH_REFRESH_TOKEN=<from secrets.env>
  MCPTOOLING_REMOTE_<NAME>_OAUTH_SCOPES="read:foo,write:foo"
  ```

### Shape 5: Subprocess wrap of a local binary MCP server

- **What:** Spawn a third-party MCP server binary (Docker, npm, pip
  install) as a subprocess and translate JSON-RPC to it.
- **When:** Vendor publishes a local MCP server binary but no remote
  endpoint. Or the server needs to run on the same host as the agent
  for performance / network reasons.
- **Examples:** Hypothetical — `mcp-server-airbnb` (TypeScript, runs
  locally). Today, the openbnb-org one we'd want to wrap.
- **Code cost:** ~100 lines — a thin Python adapter that translates
  BaseTool calls to JSON-RPC over stdio. Lives in
  `servers/<name>/` (looks like Shape 1 from the gateway's POV) but
  the actual API client is upstream code.
- **Lifecycle:** Mixed. We own the wrapper; upstream owns the binary.
- **Config (env vars):** Same as Shape 1, plus:
  ```bash
  MCPTOOLING_SERVER_<NAME>_SUBPROCESS_CMD="docker run -i --rm mcp/<name>"
  MCPTOOLING_SERVER_<NAME>_SUBPROCESS_PROTOCOL=stdio
  ```

## Decision tree

When adding a new capability, walk this in order. Stop at the first
match.

```
1. Does the vendor publish a remote MCP server?
   ├─ Yes → Shape 2, 3, or 4 depending on auth model.
   │        Config-only change. Zero code in mcp-tooling.
   └─ No  → continue ↓

2. Does the vendor publish a local MCP server binary
   (npm/pip/docker package, runs as a process)?
   ├─ Yes → Shape 5. Thin Python subprocess wrapper.
   │        ~100 lines in mcp-tooling.
   └─ No  → continue ↓

3. Does the API need server-side logic (caching, aggregation,
   custom auth, scope policy beyond what the API offers)?
   ├─ Yes → Shape 1. Self-hosted capability adapter.
   │        ~500 lines (or ~150 after ServerSpec).
   └─ No  → continue ↓

4. Is there an official REST API with simple auth (API key)?
   ├─ Yes → Shape 1, but a thin one. Mostly just an httpx client
   │        wrapped in BaseTool.
   └─ No  → The capability isn't accessible to a TEST-bound agent.
            Stop and document why (ToS risk, partner approval
            needed, etc.).
```

## How the gateway consumes this config

The gateway reads a single `MCP_SERVERS` env var (or a JSON file
sourced from env vars) that lists all enabled servers, each tagged
with its shape. Example:

```json
{
  "servers": [
    {
      "name": "duffel",
      "shape": "self_hosted",
      "package": "servers.duffel",
      "port": 8765,
      "secrets": ["DUFFEL_API_KEY"]
    },
    {
      "name": "google-workspace",
      "shape": "self_hosted",
      "package": "servers.google_workspace",
      "port": 8766,
      "secrets": ["GOOGLE_WORKSPACE_CLIENT_ID", "GOOGLE_WORKSPACE_CLIENT_SECRET", "GOOGLE_WORKSPACE_REFRESH_TOKEN"],
      "scope_policy": "narrow"
    },
    {
      "name": "trivago",
      "shape": "remote_mcp",
      "url": "https://mcp.trivago.com/mcp",
      "transport": "streamable-http"
    }
  ]
}
```

For self-hosted entries, the gateway proxies requests to the local
port. For remote entries, the gateway speaks MCP directly to the
upstream URL (with auth handled per shape).

This is the gateway-side concern, not mcp-tooling. **But the env-var
schema has to be consistent across both.** The mcp-tooling install
scripts produce env vars in this shape; the gateway consumes them.

## What this changes in the refactor plan

The ServerSpec refactor (#44) is the right move for Shape 1. It does
not change for Shapes 2-5 — those don't have mcp-tooling code.

What's *new* in this doc, that the refactor plan in PR #43 didn't
mention:

1. **`servers/<name>/config.yaml`** is the per-server config file
   (Shape 1 only). The deploy workflow reads it to know which secrets
   to forward. This is the PR #44 deliverable — already in the
   design doc.

2. **Remote MCP servers (Shapes 2-4)** are configured at the *gateway*
   level, not in mcp-tooling. mcp-tooling's role is to declare which
   shapes the gateway should support, and to provide the install /
   deploy plumbing for Shape 1.

3. **Subprocess wrap (Shape 5)** is a thin variant of Shape 1 with
   a `subprocess_cmd` field on the ServerSpec. Easy to add to
   `ServerSpec` later — just an optional `transport: str = "stdio"`
   field that, when set, spawns the subprocess instead of running
   in-process.

4. **The integration-shape taxonomy lives at the gateway.** This
   doc should be referenced from `openclaw-gateway` docs too. We
   don't *own* the gateway, but the env-var schema is a shared
   contract.

## The env-var schema proposal

For consistency across all five shapes:

```bash
# All MCP servers — self-hosted or remote — are configured via these.
# <NAME> is the canonical name (lowercase, dashes not underscores
# except for legacy reasons). The gateway reads them; mcp-tooling's
# install scripts produce them.

# Shape 1 (self-hosted)
MCPTOOLING_SERVER_<NAME>_SHAPE=self_hosted
MCPTOOLING_SERVER_<NAME>_PACKAGE=servers.<name>      # python module
MCPTOOLING_SERVER_<NAME>_PORT=<port>
MCPTOOLING_SERVER_<NAME>_SECRETS="KEY1,KEY2"         # which secrets to load from secrets.env
MCPTOOLING_SERVER_<NAME>_OAUTH_SCOPES="scope1,scope2" # optional, OAuth only

# Shape 2 (remote, no auth)
MCPTOOLING_SERVER_<NAME>_SHAPE=remote_mcp
MCPTOOLING_SERVER_<NAME>_URL=https://mcp.vendor.com/mcp
MCPTOOLING_SERVER_<NAME>_TRANSPORT=streamable-http    # or stdio

# Shape 3 (remote, API key)
MCPTOOLING_SERVER_<NAME>_SHAPE=remote_mcp
MCPTOOLING_SERVER_<NAME>_URL=https://mcp.vendor.com/mcp
MCPTOOLING_SERVER_<NAME>_AUTH_TYPE=bearer            # or header
MCPTOOLING_SERVER_<NAME>_AUTH_HEADER_NAME=X-API-Key   # if header
MCPTOOLING_SERVER_<NAME>_AUTH_TOKEN_SECRET=VENDOR_API_KEY   # name of secret in secrets.env

# Shape 4 (remote, OAuth)
MCPTOOLING_SERVER_<NAME>_SHAPE=remote_mcp
MCPTOOLING_SERVER_<NAME>_URL=https://mcp.vendor.com/mcp
MCPTOOLING_SERVER_<NAME>_AUTH_TYPE=oauth2
MCPTOOLING_SERVER_<NAME>_OAUTH_CLIENT_ID_SECRET=VENDOR_CLIENT_ID
MCPTOOLING_SERVER_<NAME>_OAUTH_CLIENT_SECRET_SECRET=VENDOR_CLIENT_SECRET
MCPTOOLING_SERVER_<NAME>_OAUTH_REFRESH_TOKEN_SECRET=VENDOR_REFRESH_TOKEN
MCPTOOLING_SERVER_<NAME>_OAUTH_SCOPES="read:foo,write:foo"

# Shape 5 (subprocess)
# Same as Shape 1, plus:
MCPTOOLING_SERVER_<NAME>_SUBPROCESS_CMD="docker run -i --rm mcp/<name>"
MCPTOOLING_SERVER_<NAME>_SUBPROCESS_PROTOCOL=stdio
```

The `<NAME>` token is uppercased. So the trivago entry is:

```bash
MCPTOOLING_SERVER_TRIVAGO_SHAPE=remote_mcp
MCPTOOLING_SERVER_TRIVAGO_URL=https://mcp.trivago.com/mcp
MCPTOOLING_SERVER_TRIVAGO_TRANSPORT=streamable-http
```

And duffel is:

```bash
MCPTOOLING_SERVER_DUFFEL_SHAPE=self_hosted
MCPTOOLING_SERVER_DUFFEL_PACKAGE=servers.duffel
MCPTOOLING_SERVER_DUFFEL_PORT=8765
MCPTOOLING_SERVER_DUFFEL_SECRETS="DUFFEL_API_KEY"
```

This is the env-var schema the gateway consumes. mcp-tooling's role
is to produce the Shape 1 entries (via install scripts) and document
the schema.

## What mcp-tooling needs to add to support this

1. **PR #44 already covers Shape 1.** The ServerSpec + reusable
   deploy workflow is exactly Shape 1 infrastructure.

2. **One new file: `docs/integrations/mcp-integration-shapes.md`**
   — this document. Already exists once this PR lands.

3. **Future PR: `runtime/server_spec.py` adds `subprocess_cmd`** for
   Shape 5. Trivial change, ~10 lines.

4. **Coordination with openclaw-gateway:** the gateway needs to
   consume the `MCPTOOLING_SERVER_*` env vars. This is a gateway-side
   PR, not mcp-tooling's. But the schema has to be agreed. Worth
   filing an issue against openclaw-gateway to align on the env-var
   schema before adding more Shape 2-4 entries.

5. **The dat-contract side:** `config/dat-contract.yaml` declares
   which secrets are needed for each server. With this schema,
   adding a new server means adding the secrets block to
   `dat-contract.yaml` *and* adding the `MCPTOOLING_SERVER_<NAME>`
   declarations to a per-server config file. The latter is new —
   today it's ad-hoc in the deploy workflow.

## Open questions

- **Where do `MCPTOOLING_SERVER_<NAME>` declarations live?** Options:
  (a) directly in `secrets.env` alongside the secrets; (b) in a
  separate `mcp-servers.env`; (c) in `config/servers/<name>.yaml`
  (the file PR #44 introduces). I'd lean (c) — it's structured,
  reviewable, and matches the deploy workflow's input.

- **Shape 5 (subprocess wrap) — is it worth its own shape?** It's
  Shape 1 with a different transport. Maybe just one shape with
  an optional subprocess transport. That keeps the schema simpler.

- **What about Shape 4 OAuth refresh at runtime?** If the gateway
  refreshes the upstream token, where does the new refresh token
  go? Back to secrets.env? This is a real concern for long-lived
  deployments. Worth designing up front, not after we add the first
  Shape 4 server.

- **Per-environment overrides.** TEST, HEAD, PROD might each have
  different `MCPTOOLING_SERVER_*` configs (different URLs, different
  secrets). The dat-contract side already handles this; the server
  config side doesn't yet.

## What this doc deliberately doesn't do

- Doesn't propose code changes (that's the refactor PRs).
- Doesn't pick a gateway-side implementation (that's openclaw-gateway's
  call).
- Doesn't lock in a final env-var naming convention — the schema is
  proposed and the open questions call out the alternatives.

The point is to **make the decision visible** before we add more
servers. Adding a third Shape 1 server with the current setup works,
but locks us into a shape that doesn't fit trivago (and tomorrow's
remote MCP vendors).