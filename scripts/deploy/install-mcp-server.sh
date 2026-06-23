#!/usr/bin/env bash
# =============================================================================
# mcp-tooling - Generic MCP server install (run on VM as root)
# =============================================================================
# Single installer that handles any MCP server in mcp-tooling, driven by
# MCP_SERVER_* env vars. Replaces the per-server install-vm.sh /
# install-google-workspace-vm.sh with one script that the deploy workflow
# calls with the right env-var set.
#
# Required env vars:
#   MCP_SERVER_NAME            Server name (e.g. "duffel"). Used for
#                              systemd unit name + secrets file logging.
#   MCP_SERVER_PORT            HTTP port the server listens on.
#   MCP_SERVER_SECRETS         Space-separated required secret names
#                              (e.g. "DUFFEL_API_KEY MCPTOOLING_ALLOWED_TOKENS").
#
# Optional env vars:
#   MCP_SERVER_SCOPE_GUARD     "true" to enable the OAuth scope guard
#                              pre-validator (defense in depth). If set,
#                              MCP_SERVER_REQUIRED_SCOPES must also be set
#                              as a comma-separated list of full scope
#                              URLs.
#
# Secrets (passed by the deploy workflow as MCP_SERVER_SECRET_<KEY>=value):
#   Each key in MCP_SERVER_SECRETS is looked up in the environment, the
#   value is written to /etc/mcp-tooling/secrets.env under its own name,
#   and the installer's secrets allowlist is restricted to exactly that
#   set + any keys prefixed MCP_OPTIONAL_SECRET_.
#
# Optional secrets (read but not required):
#   MCP_OPTIONAL_SECRET_<KEY>  Optional secrets that may be written into
#                              secrets.env if present. Useful for keys
#                              like MCPTOOLING_ALLOWED_TOOLS that some
#                              servers honor when set.
#
# After install:
#   - /etc/mcp-tooling/secrets.env is rendered (mode 640, chown root:mcptooling)
#   - /etc/systemd/system/mcp-tooling-<name>.service is rendered
#   - The service is enabled + restarted
#   - /healthz on the configured port is polled for up to 40 seconds
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Required input validation
# ---------------------------------------------------------------------------

if [ -z "${MCP_SERVER_NAME:-}" ]; then
  echo "ERROR: MCP_SERVER_NAME is required" >&2
  exit 1
fi
if [ -z "${MCP_SERVER_PORT:-}" ]; then
  echo "ERROR: MCP_SERVER_PORT is required" >&2
  exit 1
fi
if [ -z "${MCP_SERVER_SECRETS:-}" ]; then
  echo "ERROR: MCP_SERVER_SECRETS is required (space-separated list of secret keys)" >&2
  exit 1
fi

MCPTOOLING_USER="${MCPTOOLING_USER:-mcptooling}"
MCPTOOLING_HOME="${MCPTOOLING_HOME:-/opt/mcp-tooling}"
SECRETS_DIR="/etc/mcp-tooling"
SECRETS_FILE="${SECRETS_DIR}/secrets.env"
SERVICE_NAME="mcp-tooling-${MCP_SERVER_NAME}"

# ---------------------------------------------------------------------------
# Scope guard (defense in depth — server also validates on startup)
#
# The installer can pre-validate the OAuth scopes the server will be
# configured with, against an allowlist. This is useful when:
#   1. The operator is sending a non-default set of scopes via the
#      per-server env var (e.g. GOOGLE_WORKSPACE_SCOPES).
#   2. We want to fail fast — before apt/systemd runs — if a misconfigured
#      scope list would cause the server to refuse to start anyway.
#
# Env vars when MCP_SERVER_SCOPE_GUARD=true:
#   MCP_SERVER_SCOPE_ENV_VAR     Name of the env var that holds the
#                                configured scopes (e.g. "GOOGLE_WORKSPACE_SCOPES").
#                                The installer reads this var from the
#                                environment and validates it.
#   MCP_SERVER_ALLOWED_SCOPES    Comma-separated list of allowed scopes.
#                                Anything in the configured list outside
#                                this allowlist fails the installer.
# ---------------------------------------------------------------------------

if [ "${MCP_SERVER_SCOPE_GUARD:-false}" = "true" ]; then
  if [ -z "${MCP_SERVER_SCOPE_ENV_VAR:-}" ]; then
    echo "ERROR: MCP_SERVER_SCOPE_GUARD=true but MCP_SERVER_SCOPE_ENV_VAR is unset" >&2
    echo "       This is the name of the env var holding the configured scopes" >&2
    echo "       (e.g. GOOGLE_WORKSPACE_SCOPES)." >&2
    exit 2
  fi
  if [ -z "${MCP_SERVER_ALLOWED_SCOPES:-}" ]; then
    echo "ERROR: MCP_SERVER_SCOPE_GUARD=true but MCP_SERVER_ALLOWED_SCOPES is unset" >&2
    exit 2
  fi
  echo "==> Pre-validating OAuth scopes against allowlist"
  # Read the configured scopes from the env var named by MCP_SERVER_SCOPE_ENV_VAR.
  raw_configured="${!MCP_SERVER_SCOPE_ENV_VAR:-}"
  if [ -n "${raw_configured}" ]; then
    IFS=',' read -r -a _configured_scopes <<< "${raw_configured}"
    for s in "${_configured_scopes[@]}"; do
      s_trimmed="$(echo "${s}" | xargs)"
      if [ -z "${s_trimmed}" ]; then continue; fi
      # Check if this scope is in the allowlist (linear scan; the
      # allowlist is small — 2-3 entries — so this is fine).
      _in_allowlist=false
      IFS=',' read -r -a _allowed_scopes <<< "${MCP_SERVER_ALLOWED_SCOPES}"
      for a in "${_allowed_scopes[@]}"; do
        a_trimmed="$(echo "${a}" | xargs)"
        if [ "${s_trimmed}" = "${a_trimmed}" ]; then
          _in_allowlist=true
          break
        fi
      done
      if [ "${_in_allowlist}" != "true" ]; then
        echo "ERROR: Disallowed OAuth scope in ${MCP_SERVER_SCOPE_ENV_VAR}: ${s_trimmed}" >&2
        echo "  Allowlist: ${MCP_SERVER_ALLOWED_SCOPES}" >&2
        echo "  Refusing to install." >&2
        exit 2
      fi
    done
  fi
fi

# ---------------------------------------------------------------------------
# Build secrets file from MCP_SERVER_SECRETS env vars
# ---------------------------------------------------------------------------

echo "==> Rendering secrets file from MCP_SERVER_SECRETS"
mkdir -p "${SECRETS_DIR}"
SECRETS_CONTENT="# Managed by mcp-tooling deploy workflow — do not edit by hand
"
missing_secrets=()
IFS=' ' read -r -a secret_keys <<< "${MCP_SERVER_SECRETS}"
for key in "${secret_keys[@]}"; do
  # The deploy workflow passes secrets as env vars with their canonical
  # names (e.g. DUFFEL_API_KEY=*** We look them up under those names.
  value="${!key:-}"
  if [ -z "${value}" ]; then
    missing_secrets+=("${key}")
    continue
  fi
  SECRETS_CONTENT+="${key}=${value}
"  # literal secret value — not interpolated by the shell above
done

# Also pick up any optional secrets the deploy workflow passed.
for env_var in $(env | grep '^MCP_OPTIONAL_SECRET_' | cut -d= -f1); do
  key="${env_var#MCP_OPTIONAL_SECRET_}"
  value="${!env_var:-}"
  if [ -n "${value}" ]; then
    SECRETS_CONTENT+="${key}=${value}
"
  fi
done

if [ ${#missing_secrets[@]} -gt 0 ]; then
  echo "ERROR: required secrets are missing from environment:" >&2
  printf '  - %s\n' "${missing_secrets[@]}" >&2
  exit 1
fi

printf '%s' "${SECRETS_CONTENT}" > "${SECRETS_FILE}"
# Mode 640: root writes/manages, mcptooling (group) can read at runtime.
chmod 640 "${SECRETS_FILE}"
chown root:"${MCPTOOLING_USER}" "${SECRETS_FILE}"

# ---------------------------------------------------------------------------
# System setup (systemd unit)
# ---------------------------------------------------------------------------

echo "==> Ensuring system user ${MCPTOOLING_USER}"
if ! id "${MCPTOOLING_USER}" &>/dev/null; then
  useradd --system --home "${MCPTOOLING_HOME}" --shell /usr/sbin/nologin "${MCPTOOLING_USER}"
fi

echo "==> Setting up ${MCPTOOLING_HOME}"
mkdir -p "${MCPTOOLING_HOME}"
chown -R "${MCPTOOLING_USER}:${MCPTOOLING_USER}" "${MCPTOOLING_HOME}"

# Install pip deps from the source tree. This is idempotent — re-running
# pip install against an already-satisfied venv is a no-op.
if [ ! -d "${MCPTOOLING_HOME}/.venv" ]; then
  echo "==> Installing Python dependencies (first install)"
  sudo -u "${MCPTOOLING_USER}" python3 -m venv "${MCPTOOLING_HOME}/.venv"
  sudo -u "${MCPTOOLING_USER}" "${MCPTOOLING_HOME}/.venv/bin/pip" install --upgrade pip wheel
  sudo -u "${MCPTOOLING_USER}" "${MCPTOOLING_HOME}/.venv/bin/pip" install "${MCPTOOLING_HOME}"
fi

echo "==> Writing systemd unit"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=${MCP_SERVER_NAME} MCP Server
After=network.target

[Service]
Type=simple
User=${MCPTOOLING_USER}
Group=${MCPTOOLING_USER}
WorkingDirectory=${MCPTOOLING_HOME}
Environment="MCPTOOLING_SECRETS_PATH=${SECRETS_FILE}"
Environment="PATH=${MCPTOOLING_HOME}/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=${MCPTOOLING_HOME}/.venv/bin/python -m servers.${MCP_SERVER_NAME//-/_} --http --port ${MCP_SERVER_PORT}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Hardening (mirror of duffel + google-workspace units)
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
# Health check
# ---------------------------------------------------------------------------

echo "==> Waiting for health endpoint on port ${MCP_SERVER_PORT}"
for _ in {1..20}; do
  if curl -fsS "http://localhost:${MCP_SERVER_PORT}/healthz" > /dev/null 2>&1; then
    echo "✅ ${MCP_SERVER_NAME} healthy on port ${MCP_SERVER_PORT}"
    curl -sS "http://localhost:${MCP_SERVER_PORT}/healthz"
    echo
    break
  fi
  sleep 2
done

# If the health check never succeeded, the loop above fell through.
# Verify before we declare success.
if ! curl -fsS "http://localhost:${MCP_SERVER_PORT}/healthz" > /dev/null 2>&1; then
  echo "ERROR: Service did not become healthy" >&2
  echo "--- last 50 lines of service log ---" >&2
  journalctl -u "${SERVICE_NAME}.service" -n 50 --no-pager >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Endpoint manifest
# ---------------------------------------------------------------------------
# Write /etc/mcp-tooling/endpoint.json so any code on the VM (and the
# deploy workflow's endpoint-manifest job) has a canonical
# "where does this server live" answer. The deploy workflow fetches this
# file via SSH and uploads it as a workflow artifact; external clients
# (OpenClaw gateway, peer MCP servers) read the artifact to discover
# the URL.
#
# IPv4 is preferred (matches Hetzner firewall source rules); fall back
# to IPv6 if the VM has no public IPv4 (uncommon — hel1/fsn1/nbg1 VMs
# always get one).
#
# Mode 644 is intentional — clients should be able to read this without
# mcptooling group membership. The file contains no secrets; it only
# names public network endpoints.
# ---------------------------------------------------------------------------

echo "==> Writing endpoint manifest"
ENDPOINT_FILE="${SECRETS_DIR}/endpoint.json"
_ipv4="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1)"
if [ -z "${_ipv4}" ]; then
  _ipv4="$(ip -6 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1)"
fi
# JSON-encode each field. The strings are ASCII (server name, IPv4/IPv6,
# paths) so a simple sed-quote is sufficient — no control chars or quotes
# to escape.
_server_name_json="${MCP_SERVER_NAME//\"/\\\"}"
_ipv4_json="${_ipv4//\"/\\\"}"
cat > "${ENDPOINT_FILE}" <<EOF
{
  "name": "${_server_name_json}",
  "port": ${MCP_SERVER_PORT},
  "ipv4": "${_ipv4_json}",
  "base_url": "http://${_ipv4_json}:${MCP_SERVER_PORT}",
  "mcp_url": "http://${_ipv4_json}:${MCP_SERVER_PORT}/mcp",
  "health": "http://${_ipv4_json}:${MCP_SERVER_PORT}/healthz",
  "deployed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
chmod 644 "${ENDPOINT_FILE}"
chown root:root "${ENDPOINT_FILE}"
echo "    ${ENDPOINT_FILE}:"
sed 's/^/      /' "${ENDPOINT_FILE}"

exit 0