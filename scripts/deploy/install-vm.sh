#!/usr/bin/env bash
# =============================================================================
# mcp-tooling - VM install script (run on Hetzner VM as root)
# =============================================================================
# Sets up the Duffel MCP server as a systemd service.
# Idempotent: safe to re-run on every deploy.
#
# Required env vars (passed from workflow):
#   DUFFEL_API_KEY          - Duffel API key
#   MCPTOOLING_ALLOWED_TOKENS - Comma-separated bearer tokens for MCP clients
#                               (may already include per-agent derived tokens
#                               from a previous merge step)
#
# Optional env vars for per-agent token minting (both required together):
#   MCPTOOLING_AGENT_TOKEN_SALT    - HMAC salt for deriving per-agent tokens
#   MCPTOOLING_AGENT_BINDINGS_JSON - JSON list of {agent, servers[]} entries
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

# Per-agent token minting. If BOTH the salt and the bindings JSON are
# set, mint one HMAC-SHA256 token per (server, agent) pair and merge
# them into MCPTOOLING_ALLOWED_TOKENS. Otherwise leave the global
# tokens list untouched (backwards compatible).
#
# Done AFTER venv setup so we can use the venv's python interpreter
# (matches how the server itself runs).
if [ -n "${MCPTOOLING_AGENT_TOKEN_SALT:-}" ] && [ -n "${MCPTOOLING_AGENT_BINDINGS_JSON:-}" ]; then
  echo "==> Minting per-agent bearer tokens from MCPTOOLING_AGENT_BINDINGS_JSON"
  MERGED=$(MCPTOOLING_AGENT_TOKEN_SALT="${MCPTOOLING_AGENT_TOKEN_SALT}" \
           MCPTOOLING_AGENT_BINDINGS_JSON="${MCPTOOLING_AGENT_BINDINGS_JSON}" \
           MCPTOOLING_ALLOWED_TOKENS="${MCPTOOLING_ALLOWED_TOKENS}" \
           "${MCPTOOLING_HOME}/.venv/bin/python" \
           "${MCPTOOLING_HOME}/scripts/ci/render-agent-tokens.py" \
           --out-merged-env 2>&1) || {
    echo "ERROR: failed to mint per-agent tokens (see above)" >&2
    exit 1
  }
  # Extract the MCPTOOLING_ALLOWED_TOKENS=... line from the helper output.
  NEW_TOKENS=$(echo "${MERGED}" | grep -E '^MCPTOOLING_ALLOWED_TOKENS=' | head -1 | cut -d= -f2-)
  if [ -z "${NEW_TOKENS}" ]; then
    echo "ERROR: render-agent-tokens.py did not emit MCPTOOLING_ALLOWED_TOKENS" >&2
    exit 1
  fi
  MCPTOOLING_ALLOWED_TOKENS="${NEW_TOKENS}"
  echo "==> Per-agent tokens merged; allowlist size = $(echo "${MCPTOOLING_ALLOWED_TOKENS}" | tr ',' '\n' | wc -l)"

  # Write the per-agent token JSON artifact so the gateway (linux-desktop-seed)
  # can pull it via SSH and wire per-agent Authorization headers into each
  # agent's openclaw config. Same mode as secrets.env (root:mcptooling 0640).
  echo "==> Writing per-agent token map to ${SECRETS_DIR}/agent-tokens.json"
  MCPTOOLING_AGENT_TOKEN_SALT="${MCPTOOLING_AGENT_TOKEN_SALT}" \
  MCPTOOLING_AGENT_BINDINGS_JSON="${MCPTOOLING_AGENT_BINDINGS_JSON}" \
  MCPTOOLING_ALLOWED_TOKENS="${MCPTOOLING_ALLOWED_TOKENS}" \
  "${MCPTOOLING_HOME}/.venv/bin/python" \
  "${MCPTOOLING_HOME}/scripts/ci/render-agent-tokens.py" \
  --out-agent-json "${SECRETS_DIR}/agent-tokens.json"
  chmod 640 "${SECRETS_DIR}/agent-tokens.json"
  chown root:"${MCPTOOLING_USER}" "${SECRETS_DIR}/agent-tokens.json"
elif [ -n "${MCPTOOLING_AGENT_TOKEN_SALT:-}" ] || [ -n "${MCPTOOLING_AGENT_BINDINGS_JSON:-}" ]; then
  echo "WARNING: only one of MCPTOOLING_AGENT_TOKEN_SALT / MCPTOOLING_AGENT_BINDINGS_JSON is set; skipping per-agent token minting" >&2
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
