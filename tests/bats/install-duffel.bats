#!/usr/bin/env bats
# =============================================================================
# BATS tests for the duffel MCP server install shim.
# =============================================================================

setup() {
    INSTALL_SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/deploy/install-vm.sh"
    [ -f "${INSTALL_SCRIPT}" ] || skip "install script not found at ${INSTALL_SCRIPT}"
}

@test "install script is executable" {
    [ -x "${INSTALL_SCRIPT}" ]
}

@test "install script delegates to install-mcp-server.sh" {
    # The shim's job is to forward to the generic installer; verify the
    # generic installer exists and is referenced.
    grep -q 'install-mcp-server.sh' "${INSTALL_SCRIPT}"
}

@test "install script sets MCP_SERVER_NAME=duffel" {
    grep -q 'MCP_SERVER_NAME="duffel"' "${INSTALL_SCRIPT}"
}

@test "install script sets default port to 8765" {
    grep -q 'MCPTOOLING_PORT:-8765' "${INSTALL_SCRIPT}"
}

@test "install script does not enable OAuth scope guard (Duffel uses API keys)" {
    grep -q 'MCP_SERVER_SCOPE_GUARD="false"' "${INSTALL_SCRIPT}"
}

@test "install script declares required secrets" {
    # DUFFEL_API_KEY + MCPTOOLING_ALLOWED_TOKENS are the canonical pair.
    grep -q 'DUFFEL_API_KEY' "${INSTALL_SCRIPT}"
    grep -q 'MCPTOOLING_ALLOWED_TOKENS' "${INSTALL_SCRIPT}"
}