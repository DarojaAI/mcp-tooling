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

## Future work

- A small `config/endpoints.yaml` checked into the repo, written by the
  manifest job, that maps `server → url` for clients that prefer a static
  config file over the artifact stream.
- Optional DNS (Hetzner doesn't manage DNS; would be Cloudflare / Route53).
  Not needed today — the artifact covers the discovery problem without
  adding infra.