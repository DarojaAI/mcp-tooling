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
- Duffel MCP HTTP (8765) from anywhere
- All outbound

Add rules to `main.tf` when introducing new servers (e.g. a new port for a new MCP server).
