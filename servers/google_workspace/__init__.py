"""Google Workspace MCP server - documents + drive.file capability adapter.

This server exposes a narrow, deliberate slice of the Google Workspace API
to OpenClaw agents:

- documents.read (Google Docs read)
- documents.write (Google Docs create/update)
- drive.list (list files the app has access to)
- drive.create_file (create a new file the app owns)
- drive.update_file (update a file the app owns)

OAuth scopes are pinned to a narrow allowlist by default
(see ALLOWED_SCOPES). The server refuses to start if broader scopes
(gmail, calendar, full drive, etc.) are configured. This guard lives in
servers/google_workspace/scope_guard.py and is enforced in __main__.setup().

The server is a capability adapter, not a vendored fork of
google_workspace_mcp. It uses google-api-python-client + refresh-token OAuth,
matching the duffel pattern of a thin async httpx-style client per server.
"""

__version__ = "0.1.0"
