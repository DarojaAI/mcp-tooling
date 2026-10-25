#!/usr/bin/env bats
# =============================================================================
# BATS tests for the vm-ops MCP server install shim.
#
# Mirrors install-duffel.bats / install-amadeus-hotels.bats. Verifies
# the shim's structural properties; the reusable deploy workflow's
# post-deploy verifier handles the end-to-end smoke test on a real VM.
#
# Run:  bats tests/bats/install-vm-ops.bats
# =============================================================================

setup() {
    INSTALL_SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/deploy/install-vm-ops-vm.sh"
    [ -f "${INSTALL_SCRIPT}" ] || skip "install script not found at ${INSTALL_SCRIPT}"
}

@test "install script is executable" {
    [ -x "${INSTALL_SCRIPT}" ]
}

@test "install script delegates to install-mcp-server.sh" {
    grep -q 'install-mcp-server.sh' "${INSTALL_SCRIPT}"
}

@test "install script sets MCP_SERVER_NAME=vm-ops" {
    grep -q 'MCP_SERVER_NAME="vm-ops"' "${INSTALL_SCRIPT}"
}

@test "install script defaults to port 8768" {
    # Port 8765 = duffel, 8766 = google-workspace, 8767 = amadeus-hotels,
    # 8768 = vm-ops (next free).
    grep -q 'MCPTOOLING_PORT:-8768' "${INSTALL_SCRIPT}"
}

@test "install script does not enable OAuth scope guard" {
    grep -q 'MCP_SERVER_SCOPE_GUARD="false"' "${INSTALL_SCRIPT}"
}

@test "install script declares required secrets (MCPTOOLING_ALLOWED_TOKENS only)" {
    grep -q 'MCP_SERVER_SECRETS="MCPTOOLING_ALLOWED_TOKENS"' "${INSTALL_SCRIPT}"
}

@test "config/servers/vm-ops.yaml exists and is well-formed" {
    YAML="${BATS_TEST_DIRNAME}/../../config/servers/vm-ops.yaml"
    [ -f "${YAML}" ]
    grep -q "^name: vm-ops" "${YAML}"
    grep -q "^package: servers.vm_ops" "${YAML}"
    grep -q "^port: 8768" "${YAML}"
    grep -q "MCPTOOLING_ALLOWED_TOKENS" "${YAML}"
    grep -q "MCPTOOLING_CONFIRM_DESTRUCTIVE" "${YAML}"
    grep -q "oauth_scope_guard: false" "${YAML}"
}

@test "vm-ops package has an __main__.py entrypoint" {
    MAIN="${BATS_TEST_DIRNAME}/../../servers/vm_ops/__main__.py"
    [ -f "${MAIN}" ]
    grep -q "ServerSpec" "${MAIN}"
    grep -q 'name="vm_ops"' "${MAIN}"
}

@test "vm-ops declares both destructive tools" {
    TOOLS="${BATS_TEST_DIRNAME}/../../servers/vm_ops/tools/__init__.py"
    [ -f "${TOOLS}" ]
    grep -q "RestartServiceTool" "${TOOLS}"
    grep -q "KillProcessTool" "${TOOLS}"
}

@test "vm-ops README pointer exists" {
    # The README must list vm-ops as an expected sibling server.
    README="${BATS_TEST_DIRNAME}/../../README.md"
    grep -q "vm-ops" "${README}"
}
