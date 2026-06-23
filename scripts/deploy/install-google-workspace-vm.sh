#!/usr/bin/env bash
# =============================================================================
# mcp-tooling - Google Workspace server install shim
# (delegates to install-mcp-server.sh)
# =============================================================================
# Thin wrapper that preserves the original install-google-workspace-vm.sh
# contract while routing the actual work through the generic
# install-mcp-server.sh. The OAuth scope guard pre-validation that was
# inlined here is now in install-mcp-server.sh (called via the shim).
#
# This shim is the canonical installer for google-workspace; it is what
# BATS tests + the deploy-mcp-server.yml workflow call.
# =============================================================================

set -euo pipefail

export MCP_SERVER_NAME="google-workspace"
export MCP_SERVER_PORT="${MCPTOOLING_PORT:-8766}"
export MCP_SERVER_SECRETS="GOOGLE_WORKSPACE_CLIENT_ID GOOGLE_WORKSPACE_CLIENT_SECRET GOOGLE_WORKSPACE_REFRESH_TOKEN MCPTOOLING_ALLOWED_TOKENS"
# OAuth scope guard: if the operator passes GOOGLE_WORKSPACE_SCOPES, the
# installer validates each scope against the narrow allowlist BEFORE
# touching apt/systemd. The server's own scope_guard.py is the source of
# truth for the allowlist (defense in depth — installer is just early-fail).
export MCP_SERVER_SCOPE_GUARD="true"
export MCP_SERVER_SCOPE_ENV_VAR="GOOGLE_WORKSPACE_SCOPES"
export MCP_SERVER_ALLOWED_SCOPES="https://www.googleapis.com/auth/drive.file,https://www.googleapis.com/auth/documents"

exec "$(dirname "$0")/install-mcp-server.sh"