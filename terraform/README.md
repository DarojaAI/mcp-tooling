# mcp-tooling Terraform

Provisions a Hetzner VM to host the MCP servers (Duffel, etc.).

## Layout

- `main.tf` — Hetzner server + firewall, delegates VM to `terraform-hcloud-linux-vm`
- `outputs.tf` — server IP, ID, and connection info
- `backend.tfvars.example` — S3 backend config (HCX)
- `terraform.tfvars.example` — consumer variables

## Local usage

```bash
cp backend.tfvars.example backend.tfvars
cp terraform.tfvars.example terraform.tfvars
# fill in real values
terraform init -backend-config=backend.tfvars
terraform plan
terraform apply
```

In CI, the deploy workflow injects backend config and tfvars at `init` time — no `*.tfvars` files in the repo.

## Module source

Uses the shared `terraform-hcloud-linux-vm` module from `DarojaAI/terraform-hcloud-linux-vm` (pinned by ref). Update the `ref` in `main.tf` to roll forward.

## Firewalls

Default rules:
- SSH (22) from anywhere
- TCP ports listed in `inbound_ports` (default `[8765]`) from anywhere
- All outbound

Add a port to `inbound_ports` in `terraform.tfvars` when introducing a new MCP server (e.g. `8766` for google-workspace, `8767` for amadeus-hotels). The variable lives in `main.tf`; the example is in `terraform.tfvars.example`. Hetzner firewall does not accept port ranges here — list each port individually.

## MCP endpoint discovery

`outputs.tf` exposes `mcp_endpoints` (one entry per inbound port) and `mcp_endpoint` (the first entry, for single-server VMs). Each entry has the shape:

```hcl
{
  port     = 8765
  base_url = "http://203.0.113.10:8765"
  mcp_url  = "http://203.0.113.10:8765/mcp"
  health   = "http://203.0.113.10:8765/healthz"
}
```

These outputs are the contract that the deploy workflow's `endpoint-manifest` job reads, and that the install script writes to `/etc/mcp-tooling/endpoint.json` on the VM. See `docs/integrations/mcp-endpoint-discovery.md` for the full flow.
