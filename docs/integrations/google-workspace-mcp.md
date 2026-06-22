# Google Workspace MCP Server

Narrow-scope Google Workspace adapter for the `mcp_tooling` OpenClaw agent
in TEST. Implements a deliberately small tool surface (Docs read/create,
Drive.file list/create/update) over a deliberately small OAuth scope set
(`drive.file` + `documents`).

This document covers:

1. [Scope policy](#scope-policy) — what the server can and can't do.
2. [OAuth bootstrap](#oauth-bootstrap) — how the refresh token gets onto the VM.
3. [Token rotation](#token-rotation) — when and how to refresh.
4. [Audit expectations](#audit-expectations) — what gets logged, what to review.

## Scope policy

The server is bound to the `mcp_tooling` agent in TEST only. It is **not**
bound to head/prod agents.

OAuth scopes are pinned to a narrow allowlist:

- `https://www.googleapis.com/auth/drive.file` — per-file access to files
  the application has created/opened. Notably **not** the full `drive`
  scope (which is account-wide and far too broad for a TEST-bound agent).
- `https://www.googleapis.com/auth/documents` — Google Docs read/write.

The allowlist lives in
[`servers/google_workspace/scope_guard.py`](../../servers/google_workspace/scope_guard.py)
as a `frozenset`. The guard is enforced in three places:

1. **Server startup** — `servers/google_workspace/__main__.setup()` runs
   `validate_scopes()` *before* any tool is registered. A misconfigured
   scope set causes `SystemExit(2)` and the systemd unit refuses to start.
2. **Client construction** — `GoogleWorkspaceClient.__init__` calls
   `validate_scopes()` again. So even programmatic callers can't bypass
   the guard.
3. **Installer** — `scripts/deploy/install-google-workspace-vm.sh`
   pre-validates `GOOGLE_WORKSPACE_SCOPES` against the allowlist before
   writing the secrets file or registering the systemd unit. Misconfigured
   deploys exit with code 2 before systemd is touched.

### Adding a scope

**Don't.** Wider scopes are a deliberate policy decision and require a
follow-up PR with explicit approval. To widen scope:

1. Edit `ALLOWED_SCOPES` in `scope_guard.py` (add the new scope).
2. Add tests covering the new tool that needs the new scope.
3. Update this document to list the new capability.
4. Get explicit sign-off before merging.

Runtime config (`GOOGLE_WORKSPACE_SCOPES` in `secrets.env`) is **not** the
right place to widen scope — that's the whole point of code-listing it.

## OAuth bootstrap

This server uses a **per-agent, one-time interactive OAuth flow**. The
refresh token is the long-lived credential; access tokens are auto-refreshed
by `google-auth` as needed.

### Prerequisites

- A Google Cloud project with the Google Docs API and Google Drive API
  enabled.
- An OAuth 2.0 Client (type: Web application) with at least one authorized
  redirect URI. For local bootstrap, `http://localhost:8080/` works.
- The OAuth consent screen configured for the narrow scopes this server
  allows (drive.file + documents).

### One-time bootstrap procedure

Run this on the VM as the `desktopuser` (not as root):

```bash
# 1. Install the server package (already in /opt/mcp-tooling from deploy).
cd /opt/mcp-tooling
.venv/bin/pip install --upgrade google-auth-oauthlib

# 2. Run the interactive flow. The browser opens; sign in as the
#    account that owns the TEST docs the mcp_tooling agent should touch.
.venv/bin/python - <<'PY'
from google_auth_oauthlib.flow import InstalledAppFlow

# Use the narrow allowlist — anything broader will be rejected by the
# scope guard anyway, but failing here is clearer than failing in
# /opt/mcp-tooling's systemd unit.
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
]

flow = InstalledAppFlow.from_client_secrets_file(
    "/etc/mcp-tooling/google-workspace-client.json",  # OAuth client JSON
    scopes=SCOPES,
)
creds = flow.run_local_server(port=8080)

# 3. Write the refresh token to the secrets file.
print(f"REFRESH_TOKEN={creds.refresh_token}")
PY
```

Capture the printed `REFRESH_TOKEN=` line and:

1. Set `GOOGLE_WORKSPACE_REFRESH_TOKEN` as a GitHub secret on the
   `mcp-tooling` repo, scoped to the TEST environment.
2. Re-run the **Deploy Google Workspace to Hetzner** workflow for TEST
   with `action=apply` (or `force=true` if no terraform changes are
   pending).

### Why per-agent and not org-wide

The refresh token is tied to a specific Google account. If the agent
should touch the user's docs, the user signs in once and grants only
the narrow scopes. If we later want a separate agent (e.g., a
`mcp_analytics` agent) to touch a different doc set, it gets its own
refresh token and its own scope allowlist (which would need a code
change to expand).

## Token rotation

Refresh tokens for installed apps don't expire by default, but Google
may revoke them in specific cases:

- The user revoked access from their Google account settings.
- The refresh token hasn't been used for 6 months.
- The user changed their password.
- The OAuth consent screen was reconfigured with new scopes and the
  user re-consented.

Rotation procedure:

1. Re-run the bootstrap flow above. The new `REFRESH_TOKEN` will replace
   the old one (Google issues a new refresh token each time the user
   re-consents).
2. Update the `GOOGLE_WORKSPACE_REFRESH_TOKEN` GitHub secret.
3. Re-deploy.

The deploy workflow forwards the secret to the installer, which
overwrites `/etc/mcp-tooling/secrets.env` (mode 640, chown
`root:mcptooling`).

### Audit signals that warrant rotation

- Service log shows `invalid_grant` errors repeatedly.
- Drive operations return 401/403 from Google.
- The user reports they removed the app from
  <https://myaccount.google.com/permissions>.

## Audit expectations

The server is designed to be auditable. Specifically:

### What's logged

- **Stdout/stderr** — captured by systemd's journal. Every tool call
  emits the tool name and the validated scope set on startup. Errors
  include `GoogleWorkspaceError` messages with HTTP status + reason +
  URL (no request bodies or refresh tokens).
- **Google Workspace audit log** — the admin of the Google Cloud
  project can see OAuth grants and Drive/Docs API calls under
  *Google Workspace Admin Console → Audit → Drive audit log* /
  *Docs audit log*. Filter by the OAuth client ID to see only this
  server's activity.

### What's NOT logged

- The refresh token. Never log it, never put it in error messages.
  The `client.py` error path includes only status/reason/URL.
- Document *contents*. The `get_document` tool returns the full body
  to the caller but the server doesn't persist it.

### Review checklist (for the agent operator)

On a weekly cadence, review:

1. `journalctl -u mcp-tooling-google-workspace --since '7 days ago'`
   for unexpected `GoogleWorkspaceError` spikes or auth failures.
2. The Google Workspace audit log for the OAuth client ID. Watch for
   access to files outside the expected TEST doc set.
3. The `ALLOWED_SCOPES` set in `scope_guard.py` — confirm it still
   matches what's listed above. Any drift warrants investigation.

## File reference

| Path | Purpose |
| --- | --- |
| `servers/google_workspace/__main__.py` | Entrypoint + scope guard + registry setup |
| `servers/google_workspace/scope_guard.py` | `ALLOWED_SCOPES` + `validate_scopes()` |
| `servers/google_workspace/client.py` | Async wrapper around google-api-python-client |
| `servers/google_workspace/tools/` | The 5 BaseTool subclasses (one per capability) |
| `servers/google_workspace/tests/` | 41 tests covering scope guard, client, tools, setup |
| `scripts/deploy/install-google-workspace-vm.sh` | In-VM installer (mirror of duffel installer) |
| `.github/workflows/deploy-google-workspace-hetzner.yml` | GitHub Actions deploy |
| `config/dat-contract.yaml` | Declares the 4 new secrets (client_id, client_secret, refresh_token, optional scopes) |
| `docs/integrations/google-workspace-mcp.md` | This document |