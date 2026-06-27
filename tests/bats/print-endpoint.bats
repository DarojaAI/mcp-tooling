#!/usr/bin/env bats
# =============================================================================
# BATS tests for scripts/ci/print-endpoint.py — the CLI wrapper around
# scripts/ci/endpoint_registry.py. Mirrors the pytest tests but as a
# shell-level smoke test so the workflow that runs `print-endpoint.py`
# (currently nothing, but a likely future use) and humans running it by
# hand both get coverage.
#
# What these tests cover (the python tests cover the same surface, but
# BATS exercises the actual executable + the real --help / --list-* exit
# paths without needing Python imports):
#   - script is executable
#   - script exits 0 on --help
#   - script exits non-zero with a clear error message on bad args
#   - script prints the registry when given a populated file
#   - script returns exit 2 for missing entries
# =============================================================================

setup() {
    SCRIPT="${BATS_TEST_DIRNAME}/../../scripts/ci/print-endpoint.py"
    WORK="$(mktemp -d)"
    REGISTER="${WORK}/endpoints.yaml"

    cat > "${REGISTER}" <<'YAML'
# mcp-tooling - MCP endpoint registry
# =============================================================================
# Static discovery complement to the workflow-artifact mechanism in
# docs/integrations/mcp-endpoint-discovery.md. Each (server, env) entry
# is updated by .github/workflows/deploy-mcp-server.yml's
# endpoint-manifest job after a successful deploy.
#
# This file is auto-generated. Do not edit by hand — open an issue if
# a key is wrong or stale.
# =============================================================================

servers:
  google-workspace:
    dev:
      shape: self_hosted
      mcp_url: http://203.0.113.20:8766/mcp
      health: http://203.0.113.20:8766/healthz
      last_deployed: 2026-06-23T20:35:12Z
      last_run: https://github.com/DarojaAI/mcp-tooling/actions/runs/12345
YAML
}

teardown() {
    rm -rf "${WORK}"
}

@test "print-endpoint.py is executable" {
    [ -x "${SCRIPT}" ]
}

@test "print-endpoint.py --help exits 0 and prints usage" {
    run python3 "${SCRIPT}" --help
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Print MCP endpoint info"* ]]
}

@test "print-endpoint.py prints registry contents by default" {
    run python3 "${SCRIPT}" --path "${REGISTER}"
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"google-workspace"* ]]
    [[ "${output}" == *"http://203.0.113.20:8766/mcp"* ]]
    # last_deployed may be quoted or unquoted depending on YAML
    # emitter; just check the timestamp is present.
    [[ "${output}" == *"2026-06-23T20:35:12Z"* ]]
}

@test "print-endpoint.py --field mcp_url prints just the URL" {
    run python3 "${SCRIPT}" --path "${REGISTER}" \
        --server google-workspace --env dev --field mcp_url
    [ "${status}" -eq 0 ]
    [ "${output}" = "http://203.0.113.20:8766/mcp" ]
}

@test "print-endpoint.py --list-servers prints server names" {
    run python3 "${SCRIPT}" --path "${REGISTER}" --list-servers
    [ "${status}" -eq 0 ]
    [ "${output}" = "google-workspace" ]
}

@test "print-endpoint.py --list-servers --json emits JSON" {
    run python3 "${SCRIPT}" --path "${REGISTER}" --list-servers --json
    [ "${status}" -eq 0 ]
    [ "${output}" = '["google-workspace"]' ]
}

@test "print-endpoint.py exits 2 when entry is missing" {
    run python3 "${SCRIPT}" --path "${REGISTER}" \
        --server google-workspace --env prod --field mcp_url
    [ "${status}" -eq 2 ]
    [[ "${output}" == *"no entry"* ]]
}

@test "print-endpoint.py treats missing file as empty registry" {
    run python3 "${SCRIPT}" --path "${WORK}/does-not-exist.yaml" --list-servers
    [ "${status}" -eq 0 ]
    [ -z "${output}" ]
}

@test "print-endpoint.py exits 3 on unparseable YAML" {
    echo "not: [valid" > "${WORK}/bad.yaml"
    run python3 "${SCRIPT}" --path "${WORK}/bad.yaml"
    [ "${status}" -eq 3 ]
    [[ "${output}" == *"failed to parse"* ]]
}

@test "print-endpoint.py --field without --env is rejected" {
    run python3 "${SCRIPT}" --path "${REGISTER}" \
        --server google-workspace --field mcp_url
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"--field requires --env"* ]]
}

@test "print-endpoint.py --env without --server is rejected" {
    run python3 "${SCRIPT}" --path "${REGISTER}" --env dev
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"--env/--field require --server"* ]]
}

@test "print-endpoint.py --list-envs without --server is rejected" {
    run python3 "${SCRIPT}" --path "${REGISTER}" --list-envs
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"--list-envs requires --server"* ]]
}

@test "endpoint_registry.py passes python -m py_compile" {
    # Catches syntax errors before they reach a workflow.
    python3 -m py_compile "${BATS_TEST_DIRNAME}/../../scripts/ci/endpoint_registry.py"
}