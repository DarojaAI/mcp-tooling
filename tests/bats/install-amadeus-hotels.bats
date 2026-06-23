#!/usr/bin/env bats
# =============================================================================
# BATS tests for the Amadeus Hotels MCP install shim.
# =============================================================================

setup() {
    INSTALL_SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/deploy/install-amadeus-hotels-vm.sh"
    [ -f "${INSTALL_SCRIPT}" ] || skip "install script not found at ${INSTALL_SCRIPT}"
}

@test "install script is executable" {
    [ -x "${INSTALL_SCRIPT}" ]
}

@test "install script delegates to install-mcp-server.sh" {
    grep -q 'install-mcp-server.sh' "${INSTALL_SCRIPT}"
}

@test "install script sets MCP_SERVER_NAME=amadeus-hotels" {
    grep -q 'MCP_SERVER_NAME="amadeus-hotels"' "${INSTALL_SCRIPT}"
}

@test "install script sets default port to 8767" {
    grep -q 'MCPTOOLING_PORT:-8767' "${INSTALL_SCRIPT}"
}

@test "install script does not enable OAuth scope guard (Amadeus uses OAuth client credentials, not scopes)" {
    grep -q 'MCP_SERVER_SCOPE_GUARD="false"' "${INSTALL_SCRIPT}"
}

@test "install script declares required secrets" {
    grep -q 'AMADEUS_CLIENT_ID' "${INSTALL_SCRIPT}"
    grep -q 'AMADEUS_CLIENT_SECRET' "${INSTALL_SCRIPT}"
    grep -q 'MCPTOOLING_ALLOWED_TOKENS' "${INSTALL_SCRIPT}"
}