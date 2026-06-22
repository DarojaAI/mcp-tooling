#!/usr/bin/env bats
# =============================================================================
# BATS tests for the google-workspace MCP install script.
#
# These tests exercise the installer's scope guard and structural
# properties. They DO NOT run the full installer (which would create a
# real systemd service, venv, and secrets file). The reusable deploy
# workflow's post-deploy verifier handles the end-to-end smoke test on
# a real VM.
#
# Run:  bats tests/bats/install-google-workspace.bats
# =============================================================================

setup() {
    INSTALL_SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/deploy/install-google-workspace-vm.sh"
    # Sanity: the script must exist at the documented path.
    [ -f "${INSTALL_SCRIPT}" ] || skip "install script not found at ${INSTALL_SCRIPT}"
}

@test "install script is executable" {
    [ -x "${INSTALL_SCRIPT}" ]
}

@test "install script has strict mode (set -euo pipefail)" {
    # Search the first 30 lines — strict-mode declaration lives in the
    # script header preamble (after the docblock) but before any logic.
    head -30 "${INSTALL_SCRIPT}" | grep -q "set -euo pipefail"
}

@test "install script is bash, not sh" {
    head -1 "${INSTALL_SCRIPT}" | grep -q "^#!/usr/bin/env bash"
}

@test "install script declares narrow allowlist scopes (defense in depth)" {
    # The installer's scope guard must reference both allowlist scopes
    # by their full URL. This guards against silent allowlist drift.
    grep -q "https://www.googleapis.com/auth/drive.file" "${INSTALL_SCRIPT}"
    grep -q "https://www.googleapis.com/auth/documents" "${INSTALL_SCRIPT}"
}

# ---------------------------------------------------------------------------
# Scope-guard exit-code tests.
#
# We invoke the installer via `bash -c` so the exit code of the script
# propagates correctly to bats' [ "$status" -eq N ] assertion. Running
# with an env-var prefix on a bare command in bats doesn't propagate
# the exit status the way you'd expect from a shell.
# ---------------------------------------------------------------------------

@test "install script refuses gmail scope (exit code 2)" {
    run env \
        GOOGLE_WORKSPACE_CLIENT_ID="test.apps.googleusercontent.com" \
        GOOGLE_WORKSPACE_CLIENT_SECRET="***" \
        GOOGLE_WORKSPACE_REFRESH_TOKEN="***" \
        MCPTOOLING_ALLOWED_TOKENS="tok1" \
        GOOGLE_WORKSPACE_SCOPES="https://www.googleapis.com/auth/gmail.readonly" \
        bash "${INSTALL_SCRIPT}"
    [ "$status" -eq 2 ]
}

@test "install script refuses full drive scope (exit code 2)" {
    run env \
        GOOGLE_WORKSPACE_CLIENT_ID="test.apps.googleusercontent.com" \
        GOOGLE_WORKSPACE_CLIENT_SECRET="***" \
        GOOGLE_WORKSPACE_REFRESH_TOKEN="***" \
        MCPTOOLING_ALLOWED_TOKENS="tok1" \
        GOOGLE_WORKSPACE_SCOPES="https://www.googleapis.com/auth/drive" \
        bash "${INSTALL_SCRIPT}"
    [ "$status" -eq 2 ]
}

@test "install script refuses calendar scope (exit code 2)" {
    run env \
        GOOGLE_WORKSPACE_CLIENT_ID="test.apps.googleusercontent.com" \
        GOOGLE_WORKSPACE_CLIENT_SECRET="***" \
        GOOGLE_WORKSPACE_REFRESH_TOKEN="***" \
        MCPTOOLING_ALLOWED_TOKENS="tok1" \
        GOOGLE_WORKSPACE_SCOPES="https://www.googleapis.com/auth/calendar" \
        bash "${INSTALL_SCRIPT}"
    [ "$status" -eq 2 ]
}

@test "install script refuses empty required vars (exit code 1)" {
    run env bash "${INSTALL_SCRIPT}"
    [ "$status" -eq 1 ]
}

@test "install script declares narrow-scope policy in its header comment" {
    # The header comment must mention the narrow scope policy, so anyone
    # reading the script knows why it has a scope guard.
    head -30 "${INSTALL_SCRIPT}" | grep -qi "scope"
}

@test "scope_guard.py is the single source of truth for ALLOWED_SCOPES" {
    # The installer should defer to scope_guard.py as the canonical
    # reference. The installer's own list is defense-in-depth, not a
    # duplicate definition.
    SCOPE_GUARD="${BATS_TEST_DIRNAME}/../../servers/google_workspace/scope_guard.py"
    [ -f "${SCOPE_GUARD}" ]
    grep -q "ALLOWED_SCOPES" "${SCOPE_GUARD}"
}