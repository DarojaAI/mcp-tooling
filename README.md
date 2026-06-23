# mcp-tooling

**MCP tool servers for OpenClaw agents: capability layer wrapping external APIs and host operations**

## What is this?

This repo provides **MCP (Model Context Protocol) servers** that expose external capabilities to OpenClaw agents:

- **Travel booking** (Duffel API) — search flights, book, manage bookings
- **VM operations** (planned) — host diagnostics, log tailing, process control
- **Calendar/scheduling** (planned) — Cal.com integration
- **Payments** (planned) — Stripe integration

Each server is a **capability adapter**: it wraps a third-party API with tool-calling interfaces that agents can use.

## Architecture

See [dev-nexus architectural boundaries](https://github.com/DarojaAI/dev-nexus/blob/main/docs/architecture/architectural-boundaries.md) for the separation of concerns:

- **mcp-tooling** (this repo): **Capability Layer** — adapts external APIs
- **dev-nexus**: **Analysis Layer** — repository intelligence, code/data analysis
- **openclaw-gateway**: **Orchestration Layer** — agent runtime, multi-step workflows

### Directory structure

```
mcp-tooling/
├── runtime/           # Shared framework (BaseTool, registry, stdio/HTTP servers)
├── servers/           # Per-capability servers (duffel/, vm-ops/, cal/, etc.)
├── terraform/         # Hetzner VM provisioning
├── scripts/ci/        # CI validation scripts
├── scripts/deploy/    # In-VM install script (called by deploy workflow)
├── config/            # Data contract (GitHub Actions vars/secrets)
├── docs/              # Architecture decisions, authoring guides
└── tests/             # Framework + server tests
```

## Quick start

### Running a server locally (stdio)

```bash
# Install dependencies
pip install -e .

# Set up secrets
cp servers/duffel/config.example.env /etc/mcp-tooling/secrets.env
# Edit secrets.env with your Duffel API key

# Run the Duffel server
python -m servers.duffel
```

The server speaks MCP over stdio. Connect with any MCP client (e.g., openclaw-gateway).

### Running a server locally (HTTP)

```bash
python -m servers.duffel --http --port 8765
curl http://localhost:8765/healthz
```

### Deploying to Hetzner

The deploy workflow is in `.github/workflows/deploy-duffel-hetzner.yml` and provisions a Hetzner VM via `terraform/` (using the shared `terraform-hcloud-linux-vm` module), then runs `scripts/deploy/install-vm.sh` on the VM to install the Duffel MCP server as a systemd service.

**Prerequisites** (one-time, per environment):
1. Create a GitHub environment at `Settings → Environments` (e.g. `dev`, `prod`).
2. Configure the [required secrets and environment variables](.env.example) on that environment.
3. Create the HCX S3 bucket (e.g. `terraform-state-mcp-tooling`).
4. Register an SSH key in your Hetzner project.

**To deploy:**
1. GitHub Actions → "Deploy Duffel to Hetzner" → Run workflow
2. Choose environment (dropdown is auto-populated from your GitHub envs via `sync-environment-options.yml`)
3. Choose action: `plan` (preview) or `apply` (execute)
4. Review plan output, then re-run with `apply`

**To tear down:** Run the workflow with action `destroy`. The next `apply` will re-create the VM.

## Adding a new server

See [docs/authoring-server.md](docs/authoring-server.md) for the step-by-step guide.

**TL;DR:**
1. Create `servers/<name>/`
2. Write tools that inherit from `runtime/base.py:BaseTool`
3. Register them in `servers/<name>/server.py`
4. Add tests in `servers/<name>/tests/`

The runtime handles stdio/HTTP, health checks, allowlists, and secrets loading — you just write the tool logic.

## Data contract

**All GitHub Actions environment variables and secrets are documented in `config/dat-contract.yaml`.**

See [docs/github-actions-secrets.md](docs/github-actions-secrets.md) for the rendered reference (auto-generated from the contract).

## Endpoint discovery

Deployed MCP servers expose a public `mcp_url` (and a sibling `health`
probe). Two complementary mechanisms:

- **Workflow artifact** (`mcp-endpoint-<server>-<env>`) — time-sensitive,
  per-run, fetched via the GitHub REST API.
- **`config/endpoints.yaml`** — in-repo registry, updated by the
  `update-endpoints` workflow after each deploy. Stable, no auth, easy
  for humans and local dev.

Both are documented in [docs/integrations/mcp-endpoint-discovery.md](docs/integrations/mcp-endpoint-discovery.md). The CLI at `scripts/ci/print-endpoint.py` reads the registry:

```bash
scripts/ci/print-endpoint.py --server google-workspace --env dev --field mcp_url
# → http://203.0.113.20:8766/mcp
```

## Contributing

- **Boundary check:** If adding code to `runtime/` or `servers/<name>/tools/`, confirm it doesn't belong in dev-nexus (analysis) or openclaw-gateway (orchestration) per [architectural boundaries](https://github.com/DarojaAI/dev-nexus/blob/main/docs/architecture/architectural-boundaries.md).
- **Contract changes:** If editing `config/dat-contract.yaml`, update `.env.example` and `docs/github-actions-secrets.md` to match.
- **Tests:** CI runs `pytest tests/` — keep it green.

## License

MIT
