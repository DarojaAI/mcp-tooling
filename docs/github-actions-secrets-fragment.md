## Secrets Reference

Set these in: **Settings → Secrets and variables → Actions → Repository secrets**

| Secret | Description | Required |
|--------|-------------|----------|
| `HETZNER_API_TOKEN` | Hetzner Cloud API token (used by terraform + hcloud-cli) | ✅ |
| `HCX_ACCESS_KEY` | S3 access key for Terraform state backend | ✅ |
| `HCX_SECRET_KEY` | S3 secret key for Terraform state backend | ✅ |
| `SSH_PRIVATE_KEY` | ED25519 private key (no passphrase) for SSH access to the VM | ✅ |
| `DUFFEL_API_KEY` | Duffel API key (sandbox or production) | ✅ |
| `MCPTOOLING_ALLOWED_TOKENS` | Comma-separated bearer tokens for MCP client allowlist | ✅ |

> **When adding a new secret:** update this file manually. The CI doc-generator
> does *not* read `config/dat-contract.yaml`'s `secrets:` block on purpose — see
> `scripts/ci/generate-secrets-doc.py` for the rationale.
