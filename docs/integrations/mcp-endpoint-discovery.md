# MCP endpoint discovery

How clients (the OpenClaw gateway, peer MCP servers, ad-hoc scripts) find the
public URL of an MCP server deployed by `deploy-mcp-server.yml`.

## The problem

Hetzner Cloud VMs get a public IPv4 at provision time, but no DNS and no
fixed hostname. Before this change, the only way for a client to reach an
MCP server was to know the IPv4 out-of-band (manually copy it from the
Hetzner console) and hope the firewall had the right port open. Two real
gaps:

1. The firewall in `terraform/main.tf` hardcoded port `8765` for Duffel.
   Adding a second server (google-workspace on 8766, amadeus-hotels on
   8767) left the port closed at the firewall layer even if the server
   itself was listening.
2. There was no machine-readable "this MCP server lives here" artifact
   anywhere in the deploy pipeline. The Terraform output wasn't wired
   through to anything that would write it to a file the gateway could
   read.

This document describes the fix.

## The shape

Every MCP server deployed by `deploy-mcp-server.yml` exposes one public
endpoint of the form:

```
http://<ipv4>:<port>/mcp
```

with a sibling health probe at `/healthz` on the same port. The full
shape (returned by the Terraform output `mcp_endpoints` and written to
`/etc/mcp-tooling/endpoint.json` on the VM) is:

```json
{
  "name": "google-workspace",
  "port": 8766,
  "ipv4": "203.0.113.42",
  "base_url": "http://203.0.113.42:8766",
  "mcp_url": "http://203.0.113.42:8766/mcp",
  "health": "http://203.0.113.42:8766/healthz",
  "deployed_at": "2026-06-23T20:35:12Z"
}
```

## The three layers

### 1. Firewall (`terraform/main.tf`)

The firewall now reads an `inbound_ports` variable (default `[8765]`).
For each port in the list, it opens a TCP ingress rule from
`0.0.0.0/0` and `::/0`. SSH (22) is always open via a dedicated rule.
The variable is validated to reject empty lists and the reserved port 22.

To host more than one MCP server on the same VM, set:

```hcl
# terraform.tfvars
inbound_ports = [8765, 8766, 8767]
```

`terraform.tfvars.example` shows the canonical three-server layout.

### 2. Terraform outputs (`terraform/outputs.tf`)

Two new outputs:

- `mcp_endpoints` — one entry per inbound port, shape
  `{port, base_url, mcp_url, health}`.
- `mcp_endpoint` — the first entry of `mcp_endpoints`, for the common
  single-server-per-VM case.

These are the source of truth for the URL. The deploy workflow reads
`ipv4_address` + `port` from them to publish the manifest.

### 3. Install script (`scripts/deploy/install-mcp-server.sh`)

After `/healthz` succeeds, the install script writes
`/etc/mcp-tooling/endpoint.json` on the VM (mode 644, root-owned). The
script discovers its own IPv4 by walking `ip -o addr show scope global`
— preferred IPv4, falling back to IPv6. The file contains no secrets,
only public network addresses, so the open mode is intentional.

The install script never exits with status 0 unless `/healthz` returns
200, so a missing or stale `endpoint.json` means the install actually
failed (not just that the manifest step was skipped).

### 4. Deploy workflow artifact (`.github/workflows/deploy-mcp-server.yml`)

The `endpoint-manifest` job runs after `deploy`, SSHes back into the VM
using `SSH_PRIVATE_KEY` from secrets, copies
`/etc/mcp-tooling/endpoint.json` to the runner, validates the JSON shape
(`name`, `port`, `ipv4`, `mcp_url`, `health`, `deployed_at` all present;
`name` matches the server that was just deployed), and uploads it as a
GitHub Actions artifact:

```
mcp-endpoint-<server>-<env>   (e.g. mcp-endpoint-google-workspace-dev)
```

Artifact retention is 90 days. The job is skipped on `action=destroy`.

## How clients consume it

### From an OpenClaw gateway

The OpenClaw host can pull the latest artifact with
`actions/download-artifact@v4` in its own workflow, or fetch it from the
last successful run via the GitHub REST API:

```bash
gh api repos/DarojaAI/mcp-tooling/actions/artifacts \
  --jq '.artifacts[] | select(.name | startswith("mcp-endpoint-google-workspace-")) | .archive_download_url' \
  | head -n1 \
  | xargs -I{} curl -L -H "Authorization: token ${GH_TOKEN}" -o endpoint.zip {}
unzip -p endpoint.zip endpoint.json
```

The resulting `endpoint.json` is the file to feed into the gateway's
per-agent MCP config.

### From a peer MCP server

Inside the Hetzner VPC, an MCP server can fetch another server's
manifest directly via SSH:

```bash
scp root@<other-vm>:/etc/mcp-tooling/endpoint.json /tmp/endpoint.json
```

Then read `mcp_url` from the JSON and use it as the upstream base.

### Ad-hoc

```bash
ssh root@<vm> 'cat /etc/mcp-tooling/endpoint.json' | jq .
```

## Rollout

This change is backwards compatible:

- `inbound_ports` defaults to `[8765]`, so existing single-server Duffel
  deploys keep working without any `tfvars` change.
- `endpoint.json` is a new file; nothing reads it yet.
- The `endpoint-manifest` job is additive; failures there do not fail the
  `deploy` job (the server is up regardless). A failed manifest is
  visible in the GitHub Actions UI for that run.

When adding a new MCP server to a fresh VM:

1. Add a port to `inbound_ports` in the env's `terraform.tfvars`.
2. Add the server to `config/servers/`.
3. Run `deploy-mcp-server.yml` with the new `server_name`. The VM gets
   the port opened, the install script writes `endpoint.json`, and the
   workflow publishes the manifest artifact.

## Static registry: `config/endpoints.yaml`

The artifact mechanism above answers "where is the server *right now*?"
— time-sensitive, per-run, requires GitHub auth. For "what servers
exist in this repo, and where do they live in steady state?",
`config/endpoints.yaml` is the complement: a checked-in registry
updated by the `update-endpoints` workflow after each successful deploy.

### Why both

|                          | artifact                              | `config/endpoints.yaml`        |
| ------------------------ | ------------------------------------- | ------------------------------ |
| Time-sensitivity         | per-run                               | last-seen                      |
| Auth required            | GitHub token                          | none (in repo)                 |
| Offline-friendly         | no (needs GitHub API)                 | yes (file in working copy)      |
| Concurrency model        | n/a (each run has its own artifact)   | last-writer-wins via PR race   |
| Best for                 | gateway resolving "what's live now"   | humans + local dev + CI config |

### Shape

```yaml
servers:
  duffel:
    dev:
      mcp_url: http://203.0.113.10:8765/mcp
      health: http://203.0.113.10:8765/healthz
      last_deployed: 2026-06-23T20:35:12Z
      last_run: https://github.com/DarojaAI/mcp-tooling/actions/runs/12345
  google-workspace:
    dev:
      mcp_url: http://203.0.113.20:8766/mcp
      health: http://203.0.113.20:8766/healthz
      last_deployed: 2026-06-23T20:40:01Z
      last_run: https://github.com/DarojaAI/mcp-tooling/actions/runs/12346
```

The schema is enforced by `scripts/ci/endpoint_registry.py`. Each
`(server, env)` entry carries the URL, the health probe, when it was
last deployed, and a link back to the deploy run.

### How it stays current

`update-endpoints.yml` is a `workflow_dispatch` workflow. After a
`deploy-mcp-server.yml` run completes successfully, an operator runs
`update-endpoints.yml` with the deploy run's ID, the server name, and
the environment. The workflow:

1. Downloads the deploy's `mcp-endpoint-<server>-<env>` artifact.
2. Validates the JSON against the manifest contract.
3. Reads `config/endpoints.yaml` from main.
4. Calls `endpoint_registry.update(...)` to merge the new entry
   (existing entries for other `(server, env)` pairs are preserved).
5. Opens a PR; auto-merge lands it on main once checks pass.

### Using it from clients

The `scripts/ci/print-endpoint.py` CLI is the simplest interface:

```bash
# One MCP URL, no auth, no API calls.
scripts/ci/print-endpoint.py --server google-workspace --env dev --field mcp_url
# → http://203.0.113.20:8766/mcp

# List what's in the registry.
scripts/ci/print-endpoint.py --list-servers

# JSON for piping into other tools.
scripts/ci/print-endpoint.py --json | jq '.servers.google_workspace.dev'
```

The CLI exits non-zero when an entry is missing (exit 2) or the file
is unparseable (exit 3), so it's safe to use in shell pipelines.

### Concurrency safety

If two deploys land within seconds of each other (different servers,
or same server / different envs), both PRs check out main, merge their
own entry, and push. Whichever PR merges second sees the first PR's
entry on its own run because `update-endpoints.yml` always reads from
fresh main. The merge logic in `endpoint_registry.update` does a
read-modify-write on the dict, so concurrent edits on disjoint keys
never lose data — only edits on the same `(server, env)` key race,
and that race is resolved by GitHub's PR merge order.

## Future work

- Optional DNS (Hetzner doesn't manage DNS; would be Cloudflare /
  Route53). Not needed today — the artifact + the registry file cover
  the discovery problem without adding infra.
- Auto-trigger `update-endpoints.yml` from `deploy-mcp-server.yml` so
  the registry stays current without operator action. Defer until the
  manual flow proves itself in production.