# GitHub Actions Environment Variables and Secrets

This document lists all environment variables and secrets required by mcp-tooling's GitHub Actions workflows.

**Source of truth:** [`config/dat-contract.yaml`](../config/dat-contract.yaml). The contract is validated by [`scripts/ci/validate-workflow-contract.py`](../scripts/ci/validate-workflow-contract.py) in CI; this file is the human-readable rendering.

## Environment Variables

Set these in: **Settings → Environments → `<environment>` → Environment variables**

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `SERVER_NAME` | Hetzner server hostname for the duffel MCP server | ✅ | `mcp-duffel-dev` |
| `HETZNER_LOCATION` | Hetzner datacenter location (hel1, fsn1, nbg1) | ✅ | `hel1` |
| `SERVER_TYPE` | Hetzner server type (cx22 = 2 vCPU, 4GB RAM) | ✅ | `cx22` |
| `HETZNER_SSH_KEY_NAME` | SSH key name registered in Hetzner project | ✅ | — |
| `HCX_STORAGE_URL` | Hetzner Object Storage endpoint URL (e.g., `https://hel1.your-objectstorage.com/`). The deploy workflow extracts the region (e.g., `hel1`) from this URL. | ✅ | — |

> Terraform state bucket and key are derived inside the `infra-actions` reusable from `repo_name` + `HCX_STORAGE_URL`. No environment variables are required for them.

## Secrets

Set these in: **Settings → Secrets and variables → Actions → Repository secrets**

| Secret | Description | Required |
|--------|-------------|----------|
| `HETZNER_API_TOKEN` | Hetzner Cloud API token (used by terraform + hcloud-cli) | ✅ |
| `HCX_ACCESS_KEY` | S3-compatible access key for Hetzner Object Storage (Terraform state backend) | ✅ |
| `HCX_SECRET_KEY` | S3-compatible secret key for Hetzner Object Storage (Terraform state backend) | ✅ |
| `SSH_PRIVATE_KEY` | ED25519 private key (no passphrase) for SSH access to the VM | ✅ |
| `DUFFEL_API_KEY` | Duffel API key (sandbox or production) | ✅ |
| `MCPTOOLING_ALLOWED_TOKENS` | Comma-separated bearer tokens for MCP client allowlist | ✅ |

---

**Note:** When adding a new secret or environment variable, update [`config/dat-contract.yaml`](../config/dat-contract.yaml) and this document. The CI workflow-contract check will fail if a workflow references a name that isn't declared in the contract.
