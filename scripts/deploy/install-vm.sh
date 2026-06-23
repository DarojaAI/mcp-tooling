#!/usr/bin/env bash
# =============================================================================
# mcp-tooling - Duffel server install shim (delegates to install-mcp-server.sh)
# =============================================================================
# Thin wrapper that preserves the original install-vm.sh contract while
# routing the actual work through the generic install-mcp-server.sh. New
# servers should be added by writing a config/servers/<name>.yaml + a
# shim like this one (or by calling install-mcp-server.sh directly from
# the deploy workflow).
#
# This shim is the canonical installer for duffel; it is what BATS tests
# + the deploy-mcp-server.yml workflow call.
# =============================================================================

set -euo pipefail

export MCP_SERVER_NAME="duffel"
export MCP_SERVER_PORT="${MCPTOOLING_PORT:-8765}"
export MCP_SERVER_SECRETS="DUFFEL_API_KEY MCPTOOLING_ALLOWED_TOKENS"
export MCP_SERVER_SCOPE_GUARD="false"

exec "$(dirname "$0")/install-mcp-server.sh"