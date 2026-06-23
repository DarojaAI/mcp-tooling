"""Amadeus Hotels MCP server — search-only capability adapter.

This server exposes a deliberately narrow slice of the Amadeus Self-Service
Hotel APIs to OpenClaw agents:

- hotel_list (Hotel List API) — by city code, geographic coords, or hotel IDs
- hotel_search (Hotel Search API v3) — cheapest hotels in a location with
  filtering by chain, facilities, budget range
- hotel_name_autocomplete (Hotel Name Autocomplete API) — type-ahead
- hotel_ratings (Hotel Ratings API) — sentiment-based ratings for a list of hotel IDs

Hotel Booking is deliberately NOT exposed. This is a search-only server.

OAuth model:
- Amadeus Self-Service uses OAuth2 client credentials, NOT refresh tokens.
- Client sends AMADEUS_CLIENT_ID + AMADEUS_CLIENT_SECRET to
  https://test.api.amadeus.com/v1/security/oauth2/token to get a short-lived
  access token (~30 min).
- The client refreshes the token transparently before each request if it's
  expired or within 60s of expiring.

This is the third auth shape in mcp-tooling:
  - Duffel:    static API key (no auth refresh)
  - GW:        refresh token (long-lived; rotated via bootstrap)
  - Amadeus:   client credentials (short-lived access tokens; auto-refreshed)

The ServerSpec extraction (PR #44) supports all three shapes uniformly.
This server is the proof that ServerSpec handles the third auth model.
"""

__version__ = "0.1.0"
