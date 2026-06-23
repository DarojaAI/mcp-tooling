# Amadeus Hotels MCP Server

Search-only hotel discovery adapter using Amadeus Self-Service APIs.
Mirrors the duffel + google-workspace pattern but with a third auth
shape: OAuth2 **client credentials** (short-lived access tokens, no
refresh token).

This server is the **proof of ServerSpec**: it demonstrates that the
runtime abstraction from PR #44 handles a third auth model without
modification — the per-server `__main__.py` is ~70 lines, the same
shape as duffel and google-workspace.

## Scope policy

The server is bound to the `mcp_tooling` agent in TEST only.

**Tool surface (search-only, no booking):**

- `list_hotels_by_city` — Hotel List API by IATA city code
- `search_hotels` — Hotel Search API v3 (cheapest hotels with pricing)
- `autocomplete_hotel_name` — type-ahead hotel name search
- `get_hotel_ratings` — sentiment-based ratings (per-hotel or batch)

`Hotel Booking` is **deliberately not exposed**. This is a search-only
server.

## Auth model

Amadeus Self-Service uses OAuth2 client credentials, NOT refresh tokens:

1. POST `https://test.api.amadeus.com/v1/security/oauth2/token` with
   `grant_type=client_credentials` + client_id + client_secret.
2. Receive a short-lived access token (~30 min).
3. Use it as Bearer on subsequent API calls.
4. Refresh when expired or within 60s of expiring.

This is the third auth shape in mcp-tooling:

| Server            | Auth                              |
|-------------------|-----------------------------------|
| Duffel            | Static API key                    |
| Google Workspace  | Refresh token (long-lived)        |
| Amadeus Hotels    | Client credentials (short-lived)  |

The ServerSpec extraction (PR #44) supports all three uniformly. The
per-server `__main__.py` declares its auth via `build_client`; the
runtime doesn't care which model.

## Setup

### 1. Get free Amadeus Self-Service credentials

1. Sign up at <https://developers.amadeus.com> (Self-Service offer).
2. Create an application, select **Hotel APIs** category.
3. Note the **Client ID** and **Client Secret** from the dashboard.

The free tier gives ~1,000-10,000 calls/month per API; the test
environment uses fixed datasets (LON, NYC for hotels).

### 2. Set GitHub secrets (TEST environment)

- `AMADEUS_CLIENT_ID`
- `AMADEUS_CLIENT_SECRET`
- `MCPTOOLING_ALLOWED_TOKENS`

### 3. Deploy

Run **Deploy MCP server to Hetzner** with:
- `server_name`: `amadeus-hotels`
- `environment`: TEST

The generic deploy workflow (PR #47) reads
`config/servers/amadeus-hotels.yaml` and forwards the right secrets to
the generic installer.

## Token rotation

Amadeus OAuth client credentials don't expire, but you may want to
rotate the client secret:

1. Generate a new client secret in the Amadeus dashboard.
2. Update the `AMADEUS_CLIENT_SECRET` GitHub secret.
3. Re-deploy.

Access tokens auto-refresh at runtime — there's no refresh token to
manage.

## Audit expectations

- **Stdout/stderr** captured by journald. Every tool call emits the
  tool name on startup; errors include `AmadeusError` messages with
  HTTP status + path (no request bodies or client secrets).
- **Amadeus dashboard** shows call volume + rate-limit usage. Filter
  by the OAuth client ID to see only this server's activity.

## File reference

| Path | Purpose |
| --- | --- |
| `servers/amadeus_hotels/__main__.py` | Entrypoint + SPEC declaration |
| `servers/amadeus_hotels/client.py` | Async client + OAuth token management |
| `servers/amadeus_hotels/tools/` | 4 BaseTool subclasses |
| `servers/amadeus_hotels/tests/` | 24 tests (client, tools, setup) |
| `scripts/deploy/install-amadeus-hotels-vm.sh` | Shim → install-mcp-server.sh |
| `config/servers/amadeus-hotels.yaml` | Per-server config for deploy workflow |
| `servers/amadeus_hotels/config.example.env` | Example secrets file |