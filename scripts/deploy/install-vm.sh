#!/usr/bin/env bash
# =============================================================================
# mcp-tooling - VM install script (run on Hetzner VM as root)
# =============================================================================
# Sets up the Duffel MCP server as a systemd service.
# Idempotent: safe to re-run on every deploy.
#
# Required env vars (passed from workflow):
#   DUFFEL_API_KEY            - Duffel API key
#   MCPTOOLING_ALLOWED_TOKENS - Comma-separated bearer tokens for MCP clients
#                               (global tokens; per-agent tokens below are
#                               appended at install time)
#
# Optional per-agent bearer tokens (one secret per agent):
#   MCPTOOLING_AGENT_<AGENT>_TOKEN=***
#     e.g. MCPTOOLING_AGENT_TRIP_PLANNING_TOKEN=abc123
#     The "<AGENT>" portion is uppercased; non-alphanumeric chars become
#     underscores. Any env var matching this pattern is appended to the
#     allowlist.
#
# Optional per-agent binding cross-check (non-secret):
#   MCPTOOLING_AGENT_BINDINGS_JSON - JSON list of {agent, servers[]}; if set,
#                                    the install script warns (does NOT fail)
#                                    about any agent token whose name is not
#                                    listed. Use to detect typos like
#                                    TRIP_PLANNING vs trip_planning.
#
# Optional env vars (with defaults):
#   MCPTOOLING_PORT         - HTTP port (default: 8765)
#   MCPTOOLING_USER         - System user (default: mcptooling)
#   MCPTOOLING_HOME         - Install dir (default: /opt/mcp-tooling)
# =============================================================================

set -euo pipefail

MCPTOOLING_USER="${MCPTOOLING_USER:-mcptooling}"
MCPTOOLING_HOME="${MCPTOOLING_HOME:-/opt/mcp-tooling}"
MCPTOOLING_PORT="${MCPTOOLING_PORT:-8765}"
SECRETS_DIR="/etc/mcp-tooling"
SECRETS_FILE="${SECRETS_DIR}/secrets.env"
AGENT_TOKEN_MAP="${SECRETS_DIR}/agent-tokens.env"

if [ -z "${DUFFEL_API_KEY:-}" ]; then
  echo "ERROR: DUFFEL_API_KEY is required" >&2
  exit 1
fi
if [ -z "${MCPTOOLING_ALLOWED_TOKENS:-}" ]; then
  echo "ERROR: MCPTOOLING_ALLOWED_TOKENS is required" >&2
  exit 1
fi

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv python3-full \
  ca-certificates

echo "==> Creating system user ${MCPTOOLING_USER}"
if ! id "${MCPTOOLING_USER}" &>/dev/null; then
  useradd --system --home "${MCPTOOLING_HOME}" --shell /usr/sbin/nologin "${MCPTOOLING_USER}"
fi

echo "==> Setting up ${MCPTOOLING_HOME}"
mkdir -p "${MCPTOOLING_HOME}"
chown -R "${MCPTOOLING_USER}:${MCPTOOLING_USER}" "${MCPTOOLING_HOME}"

echo "==> Installing Python dependencies"
# Use a venv inside the install dir for clean isolation
sudo -u "${MCPTOOLING_USER}" python3 -m venv "${MCPTOOLING_HOME}/.venv"
sudo -u "${MCPTOOLING_USER}" "${MCPTOOLING_HOME}/.venv/bin/pip" install --upgrade pip wheel
sudo -u "${MCPTOOLING_USER}" "${MCPTOOLING_HOME}/.venv/bin/pip" install "${MCPTOOLING_HOME}"

# Per-agent bearer token enrollment.
#
# Discovers env vars matching MCPTOOLING_AGENT_<NAME>_TOKEN and appends
# their values to MCPTOOLING_ALLOWED_TOKENS. Also writes the
# (agent → token) map to ${AGENT_TOKEN_MAP} so the deploy workflow can
# upload it as an artifact for the gateway to pull.
#
# Done AFTER venv setup so secrets.env + agent-tokens.env both end up
# consistent for the service that's about to start.
echo "==> Enrolling per-agent bearer tokens from MCPTOOLING_AGENT_*_TOKEN"
declare -A AGENT_TOKEN_MAP_DECL
while IFS='=' read -r name value; do
  # Match MCPTOOLING_AGENT_<...>_TOKEN. Skip MCPTOOLING_AGENT_BINDINGS_JSON
  # (which has the same prefix but no _TOKEN suffix and isn't a token).
  if [[ "${name}" =~ ^MCPTOOLING_AGENT_(.+)_(TOKEN|token)$ ]]; then
    # Lowercase the agent name so MCPTOOLING_AGENT_TRIP_PLANNING_TOKEN
    # (GitHub secret naming convention is uppercase) enrolls as
    # "trip_planning" — matches the agent_id format used elsewhere.
    agent_name="$(echo "${BASH_REMATCH[1]}" | tr '[:upper:]' '[:lower:]')"
    if [ -z "${value}" ]; then
      echo "WARNING: ${name} is empty; skipping" >&2
      continue
    fi
    AGENT_TOKEN_MAP_DECL["${agent_name}"]="${value}"
  fi
done < <(env)

if [ "${#AGENT_TOKEN_MAP_DECL[@]}" -gt 0 ]; then
  # Append per-agent tokens to the allowlist (comma-join).
  EXTRA_TOKENS=""
  for token in "${AGENT_TOKEN_MAP_DECL[@]}"; do
    EXTRA_TOKENS="${EXTRA_TOKENS:+${EXTRA_TOKENS},}${token}"
  done
  MCPTOOLING_ALLOWED_TOKENS="${MCPTOOLING_ALLOWED_TOKENS:+${MCPTOOLING_ALLOWED_TOKENS},}${EXTRA_TOKENS}"
  echo "==> Enrolled ${#AGENT_TOKEN_MAP_DECL[@]} agent token(s); allowlist size = $(echo "${MCPTOOLING_ALLOWED_TOKENS}" | tr ',' '\n' | wc -l)"

  # Optional binding cross-check. Warn (don't fail) on agents with a
  # token but no binding entry.
  if [ -n "${MCPTOOLING_AGENT_BINDINGS_JSON:-}" ] && [ "${MCPTOOLING_AGENT_BINDINGS_JSON}" != "[]" ]; then
    if command -v python3 >/dev/null 2>&1; then
      python3 - "$MCPTOOLING_AGENT_BINDINGS_JSON" <<'PY' || echo "WARNING: binding cross-check failed" >&2
import json, sys
try:
    bindings = json.loads(sys.argv[1])
except Exception as exc:
    print(f"WARNING: MCPTOOLING_AGENT_BINDINGS_JSON invalid ({exc}); skipping cross-check", file=sys.stderr)
    sys.exit(0)
bound_agents = {b.get("agent") for b in bindings if isinstance(b, dict)}
import os
for env_name in sorted(os.environ):
    m = __import__("re").match(r"^MCPTOOLING_AGENT_(.+)_(?:TOKEN|token)$", env_name)
    if m and m.group(1) not in bound_agents:
        print(f"WARNING: token env var {env_name} has no entry in MCPTOOLING_AGENT_BINDINGS_JSON", file=sys.stderr)
PY
    fi
  fi

  # Write the agent → token map so the deploy workflow can pull it.
  # Format: simple shell-sourceable KEY=VALUE (tokens are bearer strings,
  # not shell metacharacters). Mode 0600 root:root — the systemd service
  # does NOT read this file (only the deploy workflow's root SSH session
  # does, to fetch it as a workflow artifact for the gateway).
  mkdir -p "${SECRETS_DIR}"
  : > "${AGENT_TOKEN_MAP}"
  for agent in $(printf '%s\n' "${!AGENT_TOKEN_MAP_DECL[@]}" | sort); do
    echo "MCPTOOLING_AGENT_${agent^^}_TOKEN=${AGENT_TOKEN_MAP_DECL[${agent}]}" >> "${AGENT_TOKEN_MAP}"
  done
  chmod 600 "${AGENT_TOKEN_MAP}"
  chown root:root "${AGENT_TOKEN_MAP}"
else
  echo "==> No per-agent tokens enrolled; allowlist is the global MCPTOOLING_ALLOWED_TOKENS only"
fi

echo "==> Writing secrets file"
mkdir -p "${SECRETS_DIR}"
cat > "${SECRETS_FILE}" <<EOF
# Managed by mcp-tooling deploy workflow — do not edit by hand
DUFFEL_API_KEY=${DUFFEL_API_KEY}
DUFFEL_API_URL=${DUFFEL_API_URL:-https://api.duffel.com}
MCPTOOLING_ALLOWED_TOKENS=${MCPTOOLING_ALLOWED_TOKENS}
MCPTOOLING_CONFIRM_BOOKING=${MCPTOOLING_CONFIRM_BOOKING:-false}
MCPTOOLING_CONFIRM_DESTRUCTIVE=${MCPTOOLING_CONFIRM_DESTRUCTIVE:-false}
EOF
# Mode 640: root writes/manages, mcptooling (group) can read at runtime.
# 600 would lock out the systemd service, which runs as the unprivileged user.
chmod 640 "${SECRETS_FILE}"
chown root:"${MCPTOOLING_USER}" "${SECRETS_FILE}"

echo "==> Writing systemd unit"
cat > /etc/systemd/system/mcp-tooling-duffel.service <<EOF
[Unit]
Description=Duffel MCP Server
After=network.target

[Service]
Type=simple
User=${MCPTOOLING_USER}
Group=${MCPTOOLING_USER}
WorkingDirectory=${MCPTOOLING_HOME}
Environment="MCPTOOLING_SECRETS_PATH=${SECRETS_FILE}"
Environment="PATH=${MCPTOOLING_HOME}/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=${MCPTOOLING_HOME}/.venv/bin/python -m servers.duffel --http --port ${MCPTOOLING_PORT}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${MCPTOOLING_HOME}
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
RestrictRealtime=true
LockPersonality=true
MemoryDenyWriteExecute=true

[Install]
WantedBy=multi-user.target
EOF

echo "==> Reloading systemd"
systemctl daemon-reload
systemctl enable mcp-tooling-duffel.service

echo "==> Restarting service"
systemctl restart mcp-tooling-duffel.service

echo "==> Waiting for health endpoint"
for _ in {1..20}; do
  if curl -fsS "http://localhost:${MCPTOOLING_PORT}/healthz" > /dev/null 2>&1; then
    echo "✅ Healthy on port ${MCPTOOLING_PORT}"
    curl -sS "http://localhost:${MCPTOOLING_PORT}/healthz"
    exit 0
  fi
  sleep 2
done

echo "ERROR: Service did not become healthy" >&2
echo "--- last 50 lines of service log ---" >&2
journalctl -u mcp-tooling-duffel.service -n 50 --no-pager >&2
exit 1