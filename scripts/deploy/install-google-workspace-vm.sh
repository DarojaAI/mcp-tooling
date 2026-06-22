#!/usr/bin/env bash
# =============================================================================
# mcp-tooling - Google Workspace MCP server install (run on VM as root)
# =============================================================================
# Mirrors scripts/deploy/install-vm.sh (the duffel installer) so the two
# servers coexist on one host with the same operational shape.
#
# Required env vars (passed from workflow):
#   GOOGLE_WORKSPACE_CLIENT_ID       - Google OAuth client ID
#   GOOGLE_WORKSPACE_CLIENT_SECRET   - Google OAuth client secret
#   GOOGLE_WORKSPACE_REFRESH_TOKEN   - OAuth refresh token (one-time bootstrap)
#   MCPTOOLING_ALLOWED_TOKENS        - Comma-separated bearer tokens for MCP clients
#
# Optional env vars (with defaults):
#   GOOGLE_WORKSPACE_SCOPES          - Override scopes (must be in narrow allowlist)
#   MCPTOOLING_PORT                  - HTTP port (default: 8766)
#   MCPTOOLING_USER                  - System user (default: mcptooling)
#   MCPTOOLING_HOME                  - Install dir (default: /opt/mcp-tooling)
#
# Scope policy is enforced via the server's own scope_guard, but the
# installer ALSO pre-validates GOOGLE_WORKSPACE_SCOPES here so a misconfig
# fails before systemd is even touched. This is defense in depth.
# =============================================================================

set -euo pipefail

MCPTOOLING_USER="${MCPTOOLING_USER:-mcptooling}"
MCPTOOLING_HOME="${MCPTOOLING_HOME:-/opt/mcp-tooling}"
MCPTOOLING_PORT="${MCPTOOLING_PORT:-8766}"
SECRETS_DIR="/etc/mcp-tooling"
SECRETS_FILE="${SECRETS_DIR}/secrets.env"
SERVICE_NAME="mcp-tooling-google-workspace"

# ---------------------------------------------------------------------------
# Required input validation
# ---------------------------------------------------------------------------

missing=()
[ -z "${GOOGLE_WORKSPACE_CLIENT_ID:-}" ] && missing+=("GOOGLE_WORKSPACE_CLIENT_ID")
[ -z "${GOOGLE_WORKSPACE_CLIENT_SECRET:-}" ] && missing+=("GOOGLE_WORKSPACE_CLIENT_SECRET")
[ -z "${GOOGLE_WORKSPACE_REFRESH_TOKEN:-}" ] && missing+=("GOOGLE_WORKSPACE_REFRESH_TOKEN")
[ -z "${MCPTOOLING_ALLOWED_TOKENS:-}" ] && missing+=("MCPTOOLING_ALLOWED_TOKENS")
if [ ${#missing[@]} -gt 0 ]; then
  echo "ERROR: missing required env vars:" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Scope guard (defense in depth — server also validates on startup)
# ---------------------------------------------------------------------------

ALLOWED_SCOPE_DRIVE_FILE="https://www.googleapis.com/auth/drive.file"
ALLOWED_SCOPE_DOCUMENTS="https://www.googleapis.com/auth/documents"

if [ -n "${GOOGLE_WORKSPACE_SCOPES:-}" ]; then
  echo "==> Pre-validating GOOGLE_WORKSPACE_SCOPES against narrow allowlist"
  IFS=',' read -r -a _scopes <<< "${GOOGLE_WORKSPACE_SCOPES}"
  for s in "${_scopes[@]}"; do
    s_trimmed="$(echo "${s}" | xargs)"
    case "${s_trimmed}" in
      "${ALLOWED_SCOPE_DRIVE_FILE}"|"${ALLOWED_SCOPE_DOCUMENTS}")
        ;;
      *)
        echo "ERROR: Disallowed OAuth scope in GOOGLE_WORKSPACE_SCOPES: ${s_trimmed}" >&2
        echo "  Narrow allowlist:" >&2
        echo "    - ${ALLOWED_SCOPE_DRIVE_FILE}" >&2
        echo "    - ${ALLOWED_SCOPE_DOCUMENTS}" >&2
        echo "  Broader scopes (gmail, calendar, full drive, etc.) must be" >&2
        echo "  added to ALLOWED_SCOPES via a deliberate code change, not via" >&2
        echo "  runtime config. Refusing to install." >&2
        exit 2
        ;;
    esac
  done
fi

# ---------------------------------------------------------------------------
# System setup (mirror of duffel installer)
# ---------------------------------------------------------------------------

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv python3-full \
  ca-certificates

echo "==> Ensuring system user ${MCPTOOLING_USER}"
if ! id "${MCPTOOLING_USER}" &>/dev/null; then
  useradd --system --home "${MCPTOOLING_HOME}" --shell /usr/sbin/nologin "${MCPTOOLING_USER}"
fi

echo "==> Setting up ${MCPTOOLING_HOME}"
mkdir -p "${MCPTOOLING_HOME}"
chown -R "${MCPTOOLING_USER}:${MCPTOOLING_USER}" "${MCPTOOLING_HOME}"

echo "==> Installing Python dependencies"
sudo -u "${MCPTOOLING_USER}" python3 -m venv "${MCPTOOLING_HOME}/.venv"
sudo -u "${MCPTOOLING_USER}" "${MCPTOOLING_HOME}/.venv/bin/pip" install --upgrade pip wheel
sudo -u "${MCPTOOLING_USER}" "${MCPTOOLING_HOME}/.venv/bin/pip" install "${MCPTOOLING_HOME}"

# ---------------------------------------------------------------------------
# Secrets file
# ---------------------------------------------------------------------------

echo "==> Writing secrets file"
mkdir -p "${SECRETS_DIR}"
cat > "${SECRETS_FILE}" <<EOF
# Managed by mcp-tooling deploy workflow — do not edit by hand
GOOGLE_WORKSPACE_CLIENT_ID=${GOOGLE_WORKSPACE_CLIENT_ID}
GOOGLE_WORKSPACE_CLIENT_SECRET=${GOOGLE_WORKSPACE_CLIENT_SECRET}
GOOGLE_WORKSPACE_REFRESH_TOKEN=${GOOGLE_WORKSPACE_REFRESH_TOKEN}
${GOOGLE_WORKSPACE_SCOPES:+GOOGLE_WORKSPACE_SCOPES=${GOOGLE_WORKSPACE_SCOPES}}
MCPTOOLING_ALLOWED_TOKENS=${MCPTOOLING_ALLOWED_TOKENS}
EOF
# Mode 640: root writes/manages, mcptooling (group) can read at runtime.
chmod 640 "${SECRETS_FILE}"
chown root:"${MCPTOOLING_USER}" "${SECRETS_FILE}"

# ---------------------------------------------------------------------------
# systemd unit
# ---------------------------------------------------------------------------

echo "==> Writing systemd unit"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Google Workspace MCP Server
After=network.target

[Service]
Type=simple
User=${MCPTOOLING_USER}
Group=${MCPTOOLING_USER}
WorkingDirectory=${MCPTOOLING_HOME}
Environment="MCPTOOLING_SECRETS_PATH=${SECRETS_FILE}"
Environment="PATH=${MCPTOOLING_HOME}/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=${MCPTOOLING_HOME}/.venv/bin/python -m servers.google_workspace --http --port ${MCPTOOLING_PORT}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Hardening (mirror of duffel unit)
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
systemctl enable "${SERVICE_NAME}.service"

echo "==> Restarting service"
systemctl restart "${SERVICE_NAME}.service"

# ---------------------------------------------------------------------------
# Health check (same shape as duffel: curl /healthz, then fail loud)
# ---------------------------------------------------------------------------

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
journalctl -u "${SERVICE_NAME}.service" -n 50 --no-pager >&2
exit 1