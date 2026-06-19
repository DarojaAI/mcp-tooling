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