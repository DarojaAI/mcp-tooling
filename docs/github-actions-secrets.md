# GitHub Actions Environment Variables and Secrets

This document lists all environment variables and secrets required by mcp-tooling's GitHub Actions workflows.

**Source of truth:** See [`.env.example`](../.env.example) in the repository root.

## Environment Variables

Set these in: **Settings → Environments → `<environment>` → Environment variables**

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `SERVER_NAME` | Hetzner server hostname for the duffel MCP server | ✅ | `mcp-duffel-dev` |
| `HETZNER_LOCATION` | Hetzner datacenter location (hel1, fsn1, nbg1) | ✅ | `hel1` |
| `SERVER_TYPE` | Hetzner server type (cx22 = 2 vCPU, 4GB RAM) | ✅ | `cx22` |
| `HETZNER_SSH_KEY_NAME` | SSH key name registered in Hetzner project | ✅ | — |
| `HCX_STORAGE_URL` | S3-compatible endpoint for Terraform state (e.g., s3.us-west-1.amazonaws.com) | ✅ | — |
| `TERRAFORM_STATE_BUCKET` | S3 bucket name for Terraform state | ✅ | — |
| `TERRAFORM_STATE_KEY` | S3 key path for Terraform state file | ✅ | `mcp-tooling/duffel/terraform.tfstate` |

## Secrets

Set these in: **Settings → Secrets and variables → Actions → Repository secrets**

| Secret | Description | Required |
|--------|-------------|----------|
| `HETZNER_API_TOKEN` | Hetzner Cloud API token (used by terraform + hcloud-cli) | ✅ |
| `HCX_ACCESS_KEY` | S3 access key for Terraform state backend | ✅ |
| `HCX_SECRET_KEY` | S3 secret key for Terraform state backend | ✅ |
| `SSH_PRIVATE_KEY` | ED25519 private key (no passphrase) for SSH access to the VM | ✅ |
| `DUFFEL_API_KEY` | Duffel API key (sandbox or production) | ✅ |
| `MCPTOOLING_ALLOWED_TOKENS` | Comma-separated bearer tokens for MCP client allowlist | ✅ |

---

**Tip:** When adding a new secret or environment variable, update both [`.env.example`](../.env.example) and this document.
