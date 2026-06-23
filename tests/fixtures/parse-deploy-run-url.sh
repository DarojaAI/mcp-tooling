#!/usr/bin/env bash
# =============================================================================
# Parser for deploy_run_url input to .github/workflows/update-endpoints.yml.
#
# Mirrors the bash in the "Validate + parse run URL" step. Lives outside
# the workflow so BATS can exercise it directly.
#
# If you change the parser logic, also update the matching step in
# .github/workflows/update-endpoints.yml.
# =============================================================================

set -euo pipefail

INPUT_URL="${1:-}"
REPO="${REPO:-DarojaAI/mcp-tooling}"
SERVER_URL="${SERVER_URL:-https://github.com}"

url="${INPUT_URL}"

if [[ "${url}" =~ ^[0-9]+$ ]]; then
    run_id="${url}"
    run_url="${SERVER_URL}/${REPO}/actions/runs/${run_id}"
elif [[ "${url}" =~ /actions/runs/([0-9]+) ]]; then
    run_id="${BASH_REMATCH[1]}"
    if [[ "${url}" =~ ^https?:// ]]; then
        run_url="${url}"
    else
        run_url="${SERVER_URL}${url}"
    fi
else
    echo "ERROR: input must be a numeric run ID or a URL containing '/actions/runs/<id>'" >&2
    echo "ERROR: got: ${url}" >&2
    exit 1
fi

echo "run_id=${run_id} run_url=${run_url}"