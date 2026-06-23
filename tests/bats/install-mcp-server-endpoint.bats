#!/usr/bin/env bats
# =============================================================================
# BATS tests for the endpoint manifest block in install-mcp-server.sh.
#
# The install script writes /etc/mcp-tooling/endpoint.json after the
# /healthz check succeeds. These tests verify the block is present and
# shapes the JSON correctly so the deploy workflow's endpoint-manifest
# job has a stable contract.
#
# Full integration testing of the install script is out of scope here —
# it runs as root against a real VM and depends on systemd. These are
# static + targeted source tests.
# =============================================================================

setup() {
    INSTALL_SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/deploy/install-mcp-server.sh"
    [ -f "${INSTALL_SCRIPT}" ] || skip "install script not found at ${INSTALL_SCRIPT}"
}

@test "install script is executable" {
    [ -x "${INSTALL_SCRIPT}" ]
}

@test "install script passes bash -n syntax check" {
    bash -n "${INSTALL_SCRIPT}"
}

@test "install script writes endpoint.json to /etc/mcp-tooling" {
    grep -q '/etc/mcp-tooling/endpoint.json' "${INSTALL_SCRIPT}"
}

@test "install script endpoint.json contains all required keys" {
    # The contract for the deploy workflow's endpoint-manifest job.
    for key in '"name"' '"port"' '"ipv4"' '"base_url"' '"mcp_url"' '"health"' '"deployed_at"'; do
        grep -q "${key}" "${INSTALL_SCRIPT}"
    done
}

@test "install script endpoint.json uses /mcp path" {
    grep -q '/mcp"' "${INSTALL_SCRIPT}"
}

@test "install script endpoint.json uses /healthz path" {
    grep -q '/healthz"' "${INSTALL_SCRIPT}"
}

@test "install script endpoint.json is mode 644 (no secrets in file)" {
    grep -q 'chmod 644' "${INSTALL_SCRIPT}"
}

@test "install script discovers IPv4 via ip -o addr show scope global" {
    grep -q "ip -4 -o addr show scope global" "${INSTALL_SCRIPT}"
}

@test "install script falls back to IPv6 if no global IPv4" {
    grep -q "ip -6 -o addr show scope global" "${INSTALL_SCRIPT}"
}

@test "install script health-check loop breaks instead of exiting" {
    # The old loop had `exit 0` inside, which meant a flaky first
    # /healthz success skipped the manifest write entirely. The new
    # loop uses `break` and re-checks after the loop so a partial
    # success does not skip the manifest.
    awk '/for _ in \{1..20\}/,/^done$/' "${INSTALL_SCRIPT}" | grep -q 'break'
    ! awk '/for _ in \{1..20\}/,/^done$/' "${INSTALL_SCRIPT}" | grep -q 'exit 0'
}

@test "install script health-check loop re-checks after falling through" {
    # After the loop, there must be a single re-check curl. If that
    # re-check fails, the script exits 1 and the manifest is not written.
    awk '
        BEGIN { recheck=0 }
        /for _ in \{1..20\}/ { inloop=1; next }
        inloop && /^done$/ { inloop=0; next }
        !inloop && /curl -fsS "http:\/\/localhost:.*\/healthz"/ { recheck++ }
        END { exit (recheck >= 1 ? 0 : 1) }
    ' "${INSTALL_SCRIPT}"
}

@test "install script writes endpoint.json only after /healthz succeeds" {
    # The manifest block must come AFTER the health-check loop in the
    # script, not before. Use awk to find the line number of each and
    # assert ordering.
    awk '
        /for _ in \{1..20\}/ { health=NR }
        /Writing endpoint manifest/ { manifest=NR }
        END {
            if (health == 0) { exit 1 }
            if (manifest == 0) { exit 1 }
            if (manifest <= health) { exit 1 }
        }
    ' "${INSTALL_SCRIPT}"
}

@test "install script embeds MCP_SERVER_PORT into the manifest, not a hardcoded port" {
    # Defensive: if someone hardcoded 8765 in the JSON template, this
    # would break for google-workspace (8766) and amadeus-hotels (8767).
    grep -q '\${MCP_SERVER_PORT}' "${INSTALL_SCRIPT}"
    ! grep -E '"port": *[0-9]+' "${INSTALL_SCRIPT}"
}

@test "install script embeds MCP_SERVER_NAME into the manifest" {
    grep -q '\${_server_name_json}' "${INSTALL_SCRIPT}"
}

@test "install script writes endpoint.json with owner root (no mcptooling group needed)" {
    # The endpoint file has no secrets, so it should be readable by
    # any client that lands on the VM. Confirm it is NOT chowned to
    # mcptooling (unlike secrets.env).
    awk '/Writing endpoint manifest/,/^exit 0/' "${INSTALL_SCRIPT}" | grep -q 'chown root:root'
}

@test "install script exit 0 comes after the manifest write" {
    awk '
        /Writing endpoint manifest/ { manifest=NR }
        /^exit 0/ { exit_line=NR }
        END {
            if (manifest == 0 || exit_line == 0) { exit 1 }
            if (exit_line <= manifest) { exit 1 }
        }
    ' "${INSTALL_SCRIPT}"
}