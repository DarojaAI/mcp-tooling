#!/usr/bin/env bash
# =============================================================================
# mcp-tooling - vm-ops server install shim
# (delegates to install-mcp-server.sh)
# =============================================================================
# Thin wrapper that captures the per-server env vars (name, port,
# required secrets) and delegates the real work to the generic
# install-mcp-server.sh. Same pattern as install-duffel-vm.sh /
# install-google-workspace-vm.sh / install-amadeus-hotels-vm.sh.
#
# vm-ops runs on the same VM it manages; no SSH-to-others.
# =============================================================================

set -euo pipefail

export MCP_SERVER_NAME="vm-ops"
export MCP_SERVER_PORT="${MCPTOOLING_PORT:-8768}"
export MCP_SERVER_SECRETS="MCPTOOLING_ALLOWED_TOKENS"
# MCPTOOLING_CONFIRM_DESTRUCTIVE is optional — when unset, the two
# destructive tools (restart_service, kill_process) refuse to act.
export MCP_SERVER_SCOPE_GUARD="false"

exec "$(dirname "$0")/install-mcp-server.sh"
