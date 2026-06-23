#!/usr/bin/env bats
# =============================================================================
# BATS tests for the deploy_run_url parser logic in
# .github/workflows/update-endpoints.yml.
#
# The workflow is a YAML file executed by GitHub Actions; we can't run
# it as a unit. But the URL-parsing regex is the most fragile part of
# the file (it has to handle three different input shapes) and is
# pure bash, so we extract it here and exercise it directly.
#
# If this test file is renamed or its parser function diverges from
# the workflow, the workflow will need updating too. The two stay in
# sync because they're both tiny and both reviewed together.
# =============================================================================

setup() {
    PARSER="${BATS_TEST_DIRNAME}/../fixtures/parse-deploy-run-url.sh"
    [ -f "${PARSER}" ] || skip "parser fixture not found at ${PARSER}"
}

@test "parser accepts a full https GitHub Actions run URL" {
    run bash "${PARSER}" "https://github.com/DarojaAI/mcp-tooling/actions/runs/12345"
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"run_id=12345"* ]]
    [[ "${output}" == *"https://github.com/DarojaAI/mcp-tooling/actions/runs/12345"* ]]
}

@test "parser accepts a path-only run URL" {
    run bash "${PARSER}" "/DarojaAI/mcp-tooling/actions/runs/12345"
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"run_id=12345"* ]]
}

@test "parser accepts a bare numeric run ID" {
    run bash "${PARSER}" "12345"
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"run_id=12345"* ]]
}

@test "parser accepts a run URL with a job fragment" {
    run bash "${PARSER}" "https://github.com/DarojaAI/mcp-tooling/actions/runs/12345/job/67890"
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"run_id=12345"* ]]
}

@test "parser rejects a non-URL, non-numeric input" {
    run bash "${PARSER}" "not-a-url"
    [ "${status}" -ne 0 ]
}

@test "parser rejects an empty input" {
    run bash "${PARSER}" ""
    [ "${status}" -ne 0 ]
}

@test "parser rejects a URL with no run ID" {
    run bash "${PARSER}" "https://github.com/DarojaAI/mcp-tooling"
    [ "${status}" -ne 0 ]
}

@test "parser rejects a URL where the run ID is non-numeric" {
    run bash "${PARSER}" "https://github.com/DarojaAI/mcp-tooling/actions/runs/abc"
    [ "${status}" -ne 0 ]
}