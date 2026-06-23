#!/usr/bin/env bash
# =============================================================================
# mcp-tooling - Amadeus Hotels server install shim
# (delegates to install-mcp-server.sh)
# =============================================================================

set -euo pipefail

export MCP_SERVER_NAME="amadeus-hotels"
export MCP_SERVER_PORT="${MCPTOOLING_PORT:-8767}"
export MCP_SERVER_SECRETS="AMADEUS_CLIENT_ID AMADEUS_CLIENT_SECRET MCPTOOLING_ALLOWED_TOKENS"
export MCP_SERVER_SCOPE_GUARD="false"

exec "$(dirname "$0")/install-mcp-server.sh"