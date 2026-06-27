# MCP integration shapes — decision tree + per-shape recipes

This document captures the decision tree for adding a new MCP server
capability to OpenClaw. The point: **pick the right integration shape
based on what's available, and let per-server config files drive the
configuration** — not per-server code, and not environment variables
at scale.

See also:

- [`authoring-server.md`](../authoring-server.md) — step-by-step
  recipe for writing a Shape 1 server (Python, install script,
  systemd). The shapes doc tells you *when* to reach for it; the
  authoring doc tells you *how*.
- [`mcp-endpoint-discovery.md`](mcp-endpoint-discovery.md) — the
  artifact + `config/endpoints.yaml` registry mechanics. The shapes
  doc tells you *which* server config to write; the discovery doc
  tells you *how* a client finds the running server.

## Why this matters now

After the google-workspace server (#42), the ServerSpec refactor
(#44), the generic deploy workflow (#47), per-port firewall +
artifact mechanism (#49), and the static endpoint registry (#51),
adding server #4 is mostly an exercise in picking a shape and
filling in a YAML file. PR #52 wired **Shape 2 (remote_mcp, no
auth)**, so vendors that publish their own MCP server (trivago,
DeepL MCP, Notion MCP without auth, etc.) are now a five-line YAML
file away from being available to the gateway.

The current production pattern is **per-server YAML at
`config/servers/<name>.yaml`** — one file per server, schema-validated,
PR-reviewable, deploy-dispatched. The deploy workflow reads the YAML,
the install script (Shape 1 only) or the local manifest render
(Shape 2) writes `/etc/mcp-tooling/endpoint.json` (Shape 1) or a
local artifact (Shape 2), and `update-endpoints.yml` merges it into
`config/endpoints.yaml` — the in-repo registry the OpenClaw gateway
reads.

Why not a 90-line `secrets.env` with `MCPTOOLING_SERVER_<NAME>_URL`,
`MCPTOOLING_SERVER_<NAME>_PORT`, …? Because at 30 servers that's 90+
env vars, no schema validation, no diff-friendly review, no nested
values, and shell-escape pain on URLs with query strings. We tried it
on paper; per-server YAML scales where env vars don't. (See
[Why not env vars](#why-not-env-vars) below.)

## Wire-up status

| Shape | Description | Wired? | Reference |
|-------|-------------|--------|-----------|
| 1 | Self-hosted capability adapter (Python + install script + systemd) | ✅ | PR #44, #47, #48, [`authoring-server.md`](../authoring-server.md) |
| 2 | Remote MCP, no auth | ✅ via `shape: remote_mcp` | PR #52, [`config/servers/trivago.yaml`](../../config/servers/trivago.yaml) |
| 3 | Remote MCP, API key / bearer | ❌ schema documented below | follow-up |
| 4 | Remote MCP, OAuth refresh | ❌ schema documented below | follow-up |
| 5 | Subprocess wrap of a local binary MCP server | ❌ schema documented below | follow-up |

Shape 1 + Shape 2 are the only ones the deploy pipeline runs today.
Shapes 3-5 follow the same per-server YAML pattern; each is a
small follow-up PR once the auth/transport plumbing is in place.

## Adding a server (any wired shape)

The streamlined process is the same for every wired shape: write a
YAML file, dispatch the deploy workflow, merge the registry entry.
Five minutes of work for either shape.

### Adding a Shape 1 server (self-hosted)

Shape 1 is for vendors that don't publish an MCP server — or that
need custom auth, server-side logic, or scope policy that the vendor
doesn't provide. You're writing a Python server that wraps their
API (or their MCP binary) and exposing MCP tools.

1. **Author the server.** Follow
   [`docs/authoring-server.md`](../authoring-server.md) for the
   step-by-step. Three custom auth shapes already work via the
   ServerSpec: API key (duffel), refresh-token OAuth (google-workspace),
   client-credentials OAuth (amadeus-hotels).
2. **Write the deploy config** at `config/servers/<name>.yaml`:
   ```yaml
   name: <name>
   package: servers.<name>     # python module path
   port: <unique port>
   secrets:
     - <SECRET_KEY_1>
     - <SECRET_KEY_2>
     - MCPTOOLING_ALLOWED_TOKENS
   optional_secrets:
     - <OPTIONAL_KEY>
   # oauth_scope_guard + allowed_scopes only if the server enforces
   # OAuth scopes and you want the install script to pre-validate.
   ```
3. **Open the port** in `terraform.tfvars` for the target env:
   ```hcl
   inbound_ports = [8765, 8766, 8767, <new port>]
   ```
4. **Add the secrets** to `config/dat-contract.yaml` so the GitHub
   environment knows what's required.
5. **Dispatch `deploy-mcp-server.yml`** with
   `server_name=<name> action=apply environment=<env>`. The
   workflow reads the YAML, provisions the VM, installs the server,
   writes `/etc/mcp-tooling/endpoint.json`, and publishes an
   `mcp-endpoint-<name>-<env>` artifact.
6. **Run `update-endpoints.yml`** with the deploy run's ID. It merges
   the artifact into `config/endpoints.yaml`. A PR opens automatically;
   merge it.
7. **Verify** with `scripts/ci/print-endpoint.py --server <name>
   --env <env>`. The OpenClaw gateway picks the URL up on its next
   discovery cycle.

### Adding a Shape 2 server (remote_mcp, no auth)

Shape 2 is for vendors that publish their own public MCP endpoint.
No Python code, no VM, no install script — you just point the
gateway at their URL.

1. **Write the deploy config** at `config/servers/<vendor>.yaml`:
   ```yaml
   shape: remote_mcp
   name: <vendor>
   url: https://mcp.<vendor>.com/mcp
   transport: streamable-http   # or stdio (rare for remote)
   ```
   The reference example is
   [`config/servers/trivago.yaml`](../../config/servers/trivago.yaml).
2. **Dispatch `deploy-mcp-server.yml`** with
   `server_name=<vendor> action=apply environment=<env>`. The
   workflow detects `shape: remote_mcp` and **skips** the Terraform
   and VM-install jobs entirely; it renders `endpoint.json` directly
   from the YAML and publishes the same `mcp-endpoint-<vendor>-<env>`
   artifact Shape 1 produces.
3. **Run `update-endpoints.yml`** with the deploy run's ID. The
   merged registry entry carries `shape: remote_mcp` and `transport:
   streamable-http`.
4. **Verify** with `scripts/ci/print-endpoint.py --server <vendor>
   --env <env>`. The OpenClaw gateway consumes the registry entry
   without branching on shape.

The whole flow is a 5-line YAML file, two workflow_dispatch calls,
and a PR merge. No infra changes.

## The integration-shape taxonomy

Five shapes, ranked by how much code we write in mcp-tooling:

### Shape 1: Self-hosted capability adapter

- **What:** Python code in `servers/<name>/`, install script,
  systemd unit, port allocated. Wraps either a vendor's REST API
  or a vendor's MCP server binary (Shape 5 is the documented variant
  for the latter).
- **When:** API needs custom auth (refresh-token OAuth, client
  credentials), server-side logic (caching, aggregation), or there's
  no upstream MCP server at all.
- **Examples:** duffel (API key), google-workspace (refresh-token
  OAuth, narrow scope), amadeus-hotels (client-credentials OAuth).
- **Code cost:** ~500 lines (server) + ~150 (install) + ~150 (deploy
  workflow) per server. After the ServerSpec refactor, ~150 lines per
  server for the deploy workflow side.
- **Lifecycle:** Owned by mcp-tooling. Deploy via Hetzner workflow.
- **Config (`config/servers/<name>.yaml`):**
  ```yaml
  name: <name>
  package: servers.<name>
  port: <port>
  secrets:
    - <SECRET_KEY_1>
    - <SECRET_KEY_2>
    - MCPTOOLING_ALLOWED_TOKENS
  optional_secrets:
    - <OPTIONAL_KEY>
  oauth_scope_guard: false       # set true for OAuth servers that enforce scopes
  allowed_scopes: []             # only used when oauth_scope_guard: true
  ```

### Shape 2: Remote MCP server, no auth ✅ wired

- **What:** A URL the gateway points at. No code in mcp-tooling.
- **When:** The vendor publishes an MCP server at a public URL with
  no auth requirement.
- **Examples:** trivago (`https://mcp.trivago.com/mcp`).
- **Code cost:** ~10 lines of config (5-line YAML + deploy-workflow
  conditional, which PR #52 already shipped).
- **Lifecycle:** Owned by the vendor. We just configure the
  connection.
- **Config (`config/servers/<name>.yaml`):**
  ```yaml
  shape: remote_mcp
  name: <vendor>
  url: https://mcp.<vendor>.com/mcp
  transport: streamable-http   # or stdio
  ```
  Deploy: `deploy-mcp-server.yml` skips Terraform and the install
  step; writes the `endpoint.json` artifact from the YAML directly.

### Shape 3: Remote MCP server, with API key auth ⚠️ not wired

- **What:** URL + bearer/API-key header. No code in mcp-tooling,
  but the deploy workflow needs a secret-store lookup for the key.
- **When:** Vendor publishes an MCP server that requires a static
  key.
- **Examples:** Hypothetical — many B2B MCP servers will land here.
- **Code cost:** ~15 lines of config + a secret-store forwarder in
  `update-endpoints.yml` (so the registry entry carries a secret
  *reference*, not a secret value).
- **Lifecycle:** Owned by the vendor; we manage the key.
- **Proposed config (`config/servers/<name>.yaml`):**
  ```yaml
  shape: remote_mcp
  name: <vendor>
  url: https://mcp.<vendor>.com/mcp
  transport: streamable-http
  auth_type: bearer              # or header
  auth_header_name: X-API-Key    # if auth_type=header
  auth_token_secret: VENDOR_API_KEY   # name of secret in secrets.env
  ```

### Shape 4: Remote MCP server, with OAuth ⚠️ not wired

- **What:** URL + OAuth flow (refresh token or device-code). The
  gateway handles the token exchange.
- **When:** Vendor publishes an MCP server that requires user OAuth.
- **Examples:** Hypothetical. Google / Microsoft will land here
  once they ship public MCP servers.
- **Code cost:** ~20 lines of config + a small OAuth bootstrap
  helper in the gateway (token-refresh at runtime, refresh-token
  writeback to the secret store).
- **Lifecycle:** Owned by the vendor; we manage the refresh token.
- **Proposed config (`config/servers/<name>.yaml`):**
  ```yaml
  shape: remote_mcp
  name: <vendor>
  url: https://mcp.<vendor>.com/mcp
  transport: streamable-http
  auth_type: oauth2
  oauth_client_id_secret: VENDOR_CLIENT_ID
  oauth_client_secret_secret: VENDOR_CLIENT_SECRET
  oauth_refresh_token_secret: VENDOR_REFRESH_TOKEN
  oauth_scopes: "read:foo,write:foo"
  ```

### Shape 5: Subprocess wrap of a local binary MCP server ⚠️ not wired

- **What:** Spawn a third-party MCP server binary (Docker, npm, pip
  install) as a subprocess and translate JSON-RPC to it.
- **When:** Vendor publishes a local MCP server binary but no
  remote endpoint. Or the server needs to run on the same host as
  the agent for performance / network reasons.
- **Examples:** Hypothetical — `mcp-server-airbnb` (TypeScript,
  runs locally).
- **Code cost:** ~100 lines — a thin Python adapter that translates
  BaseTool calls to JSON-RPC over stdio. Lives in `servers/<name>/`
  (looks like Shape 1 from the gateway's POV) but the actual API
  client is upstream code.
- **Lifecycle:** Mixed. We own the wrapper; upstream owns the binary.
- **Proposed config (`config/servers/<name>.yaml`):**
  ```yaml
  shape: self_hosted             # still self_hosted from the gateway's POV
  name: <name>
  package: servers.<name>
  port: <port>
  subprocess_cmd: "docker run -i --rm mcp/<name>"
  subprocess_protocol: stdio
  secrets:
    - MCPTOOLING_ALLOWED_TOKENS
  ```
  Note: Shape 5 is Shape 1 with a `subprocess_cmd` field. It may
  not deserve its own row in the taxonomy — the open question is
  whether we collapse it into Shape 1 with an optional transport.

## Decision tree

When adding a new capability, walk this in order. Stop at the first
match.

```
1. Does the vendor publish a remote MCP server?
   ├─ Yes, no auth     → Shape 2. ✅ wired.
   │                     Drop a 5-line YAML, dispatch deploy, merge
   │                     the registry entry. Zero code in mcp-tooling.
   ├─ Yes, API key     → Shape 3. ❌ schema only; PR needed for
   │                     secret-store plumbing.
   ├─ Yes, OAuth       → Shape 4. ❌ schema only; PR needed for
   │                     refresh-token writeback design.
   └─ No               → continue ↓

2. Does the vendor publish a local MCP server binary
   (npm/pip/docker package, runs as a process)?
   ├─ Yes → Shape 5. ❌ schema only; PR needed for the
   │        subprocess transport (~100 lines in mcp-tooling).
   └─ No  → continue ↓

3. Does the API need server-side logic (caching, aggregation,
   custom auth, scope policy beyond what the API offers)?
   ├─ Yes → Shape 1. ✅ wired.
   │        Follow docs/authoring-server.md; drop a YAML;
   │        dispatch deploy; merge the registry entry.
   │        ~500 lines (or ~150 after ServerSpec) of Python.
   └─ No  → continue ↓

4. Is there an official REST API with simple auth (API key)?
   ├─ Yes → Shape 1, but a thin one. Mostly just an httpx client
   │        wrapped in BaseTool.
   └─ No  → The capability isn't accessible to a TEST-bound agent.
            Stop and document why (ToS risk, partner approval
            needed, etc.).
```

## How clients consume this config

The deploy pipeline produces three artifacts per server, all of
which a client (OpenClaw gateway, peer MCP server, ad-hoc script)
can read:

```
   config/servers/<name>.yaml    ← human-edited source of truth
              │
              ▼
   deploy-mcp-server.yml         ← workflow_dispatch
              │
              ▼
   mcp-endpoint-<name>-<env>     ← GitHub Actions artifact (Shape 1
              │                     SCPs from VM; Shape 2 renders
              │                     locally from YAML)
              ▼
   update-endpoints.yml          ← merges artifact into:
              │
              ▼
   config/endpoints.yaml         ← in-repo registry, per-(server, env)
              │
              ▼
   OpenClaw gateway              ← reads the registry on its discovery
                                   cycle; no env-var parsing needed
```

The artifact mechanism is documented in
[`mcp-endpoint-discovery.md`](mcp-endpoint-discovery.md). The
short version:

- **Time-sensitive query** (where is this server *right now*?) →
  fetch the artifact via `gh run download`. Requires GitHub auth.
- **Stable query** (what servers does this repo expose in steady
  state?) → read `config/endpoints.yaml`. No auth.
- **Wire format** for either path is the same JSON shape with the
  same required keys (`name`, `shape`, `mcp_url`, `last_deployed`),
  plus shape-specific fields (`health` for Shape 1, `transport` for
  Shape 2, etc.).

The OpenClaw gateway consumes the registry via the same path for
every shape — that's the entire point of `config/endpoints.yaml`
existing.

## Why not env vars

The first draft of this doc (PR #45) proposed an env-var schema like:

```bash
MCPTOOLING_SERVER_<NAME>_SHAPE=remote_mcp
MCPTOOLING_SERVER_<NAME>_URL=https://mcp.vendor.com/mcp
MCPTOOLING_SERVER_<NAME>_TRANSPORT=streamable-http
```

We considered it seriously, then rejected it at scale:

| Concern | Env vars | Per-server YAML |
|---------|----------|-----------------|
| 30 servers × ~3 vars each | 90+ lines of env | 30 small files |
| Schema validation | none (stringly-typed) | JSON Schema + `endpoint_registry.py` |
| Diff in PR review | append 3 lines to a giant file | one new file, scoped review |
| URL/secret escaping | shell-quote pain | YAML's job |
| Per-env overrides (test/head/prod) | env layering | `config/servers/<env>/<name>.yaml` or dat-contract |
| Conflict risk (two servers, same var prefix) | real | none (file names don't collide) |

Per-server YAML is the source of truth; env vars are an internal
*wire format* between the install script and the gateway's process
env. The gateway never reads `MCPTOOLING_SERVER_<NAME>_*` — it reads
`config/endpoints.yaml`, which the install pipeline renders from the
YAML.

## Decisions captured

Things we agreed and want to keep:

1. **Per-server YAML is the source of truth.** One file per server
   at `config/servers/<name>.yaml`. The deploy workflow reads it
   directly. No env-var-as-source.
2. **`config/endpoints.yaml` is the in-repo registry** of where each
   server lives, updated by `update-endpoints.yml` after each
   deploy. The OpenClaw gateway reads this — not env vars.
3. **The artifact mechanism** (`mcp-endpoint-<server>-<env>`) is the
   time-sensitive complement to the registry. Both work; clients
   pick the one that fits.
4. **Shape is a field on the YAML**, not a separate config tree.
   `shape: self_hosted` is the default (existing YAMLs unchanged);
   `shape: remote_mcp` opts into the no-VM path. Shape 3-5 will
   add new auth/transport fields without changing this structure.
5. **Per-env overrides** route through the GitHub Actions
   environment, the same way dat-contract secrets do. Not through
   the YAML itself — `config/servers/<name>.yaml` is the same file
   across envs, with environment-specific values coming from
   `secrets.env`.
6. **The OpenClaw gateway doesn't read env vars** for server config.
   It reads `config/endpoints.yaml` (or the artifact). This is the
   shared contract between mcp-tooling and the gateway.

## Open questions

(Resolved questions moved to [Decisions captured](#decisions-captured).)

- **Shape 3 (bearer/API-key):** where does the key live? Likely
  `secrets.env` (already in the dat-contract) + a secret *reference*
  in the YAML (`auth_token_secret: VENDOR_API_KEY`), so the registry
  carries the reference name not the value. Same shape as
  google-workspace's OAuth tokens today.
- **Shape 4 (OAuth):** if the gateway refreshes the upstream token
  at runtime, where does the new refresh token go? Back to
  `secrets.env` via the same secret-store writeback path the gateway
  already uses for `GOOGLE_WORKSPACE_REFRESH_TOKEN`. Worth designing
  up front, not after the first Shape 4 server.
- **Shape 5 vs Shape 1:** is the subprocess wrap worth its own row
  in the taxonomy? It's Shape 1 with a `subprocess_cmd` field.
  Collapsing them keeps the schema simpler; keeping them separate
  matches the "Shape N = config cost in mcp-tooling" framing.
- **Per-env URL overrides for Shape 2:** some vendors have
  test/prod endpoints at different URLs. The current pattern
  (same YAML, different env vars) doesn't quite fit — we'd need
  either per-env YAMLs or a `${ENV}` interpolation in the URL. The
  dat-contract side already supports per-env secrets; mirror that.
- **Registry write contention on `config/endpoints.yaml`:** the
  `update-endpoints` workflow opens a PR; humans merge. If two
  deploys finish close together, the second's PR is a fast-forward
  or a trivial merge. If the human bottleneck becomes a problem,
  the open question is auto-merge with concurrency safety — not
  solved yet.

## What this doc deliberately doesn't do

- Doesn't pick a gateway-side implementation. That's
  `openclaw-gateway`'s call; this doc only defines the contract
  mcp-tooling produces.
- Doesn't lock in a final env-var naming convention for the
  internal wire format. The wire format is internal to mcp-tooling
  + the gateway; not user-facing. Per-server YAML is the
  user-facing surface.
- Doesn't propose vendor-specific scope policies or rate-limit
  handling. Those are per-server decisions, not shape decisions.