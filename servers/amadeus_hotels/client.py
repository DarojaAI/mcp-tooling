"""
Async client for the Amadeus Self-Service Hotel APIs.

Auth model:
- OAuth2 client credentials. Client sends AMADEUS_CLIENT_ID +
  AMADEUS_CLIENT_SECRET to the OAuth endpoint, gets a short-lived access
  token (~30 min), and uses it as a Bearer token on subsequent requests.
- Access tokens are auto-refreshed when expired or within 60s of expiring.
- Token exchange is sync (httpx) wrapped in asyncio.to_thread.

Endpoints used:
- /v1/security/oauth2/token — token exchange
- /v1/reference-data/locations/hotels/by-city — Hotel List (by city)
- /v3/shopping/hotel-offers — Hotel Search (v3)
- /v1/reference-data/locations/hotel — Hotel Name Autocomplete
- /v2/e-reputation/hotel-sentiments — Hotel Ratings

The base URL switches between test (test.api.amadeus.com) and production
(api.amadeus.com) via the AMADEUS_ENV env var.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from runtime.secrets import load_secrets  # noqa: F401  -- for consistency with other servers


class AmadeusError(RuntimeError):
    """Raised on any non-recoverable Amadeus API error."""


class AmadeusAuthError(AmadeusError):
    """Raised when OAuth token exchange fails."""


class AmadeusClient:
    """
    Async client for the narrow hotel-search surface this server exposes.

    Usage:
        client = AmadeusClient(
            client_id="...",
            client_secret="***",
            env="test",  # or "production"
        )
        hotels = await client.search_hotels(city_code="PAR")
    """

    TOKEN_URL_TEST = "https://test.api.amadeus.com/v1/security/oauth2/token"
    TOKEN_URL_PROD = "https://v1.api.amadeus.com/v1/security/oauth2/token"
    BASE_URL_TEST = "https://test.api.amadeus.com"
    BASE_URL_PROD = "https://api.amadeus.com"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        env: str = "test",
        timeout_seconds: float = 30.0,
    ) -> None:
        if not client_id or not client_secret:
            raise AmadeusError(
                "AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET are required. "
                "Get free credentials at https://developers.amadeus.com"
            )

        self._client_id = client_id
        self._client_secret = client_secret
        self._env = env.lower() if env else "test"
        if self._env not in ("test", "production"):
            raise AmadeusError(f"AMADEUS_ENV must be 'test' or 'production', got '{env}'")

        self._base_url = self.BASE_URL_PROD if self._env == "production" else self.BASE_URL_TEST
        self._token_url = self.TOKEN_URL_PROD if self._env == "production" else self.TOKEN_URL_TEST

        self._timeout = httpx.Timeout(timeout_seconds)
        self._access_token: str | None = None
        self._expires_at: float = 0.0  # epoch seconds
        # Lock for token refresh — multiple coroutines may call concurrently.
        self._token_lock = asyncio.Lock()

    @property
    def env(self) -> str:
        return self._env

    # -- token management --------------------------------------------------

    async def _fetch_token(self) -> tuple[str, int]:
        """Exchange client credentials for an access token. Returns (token, expires_in_seconds)."""
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            response = await http.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if response.status_code != 200:
            raise AmadeusAuthError(
                f"Amadeus OAuth token exchange failed: status={response.status_code} body={response.text[:200]}"
            )
        data = response.json()
        return data["access_token"], int(data.get("expires_in", 1800))

    async def _get_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        # Fast path: token still valid and not about to expire.
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token

        async with self._token_lock:
            # Re-check inside the lock (another coroutine may have refreshed).
            if self._access_token and time.time() < self._expires_at - 60:
                return self._access_token

            token, expires_in = await self._fetch_token()
            self._access_token = token
            self._expires_at = time.time() + expires_in
            return self._access_token

    # -- HTTP helpers ------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Authenticated GET against the Amadeus API."""
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            response = await http.get(
                f"{self._base_url}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code != 200:
            raise AmadeusError(
                f"Amadeus API error: status={response.status_code} path={path} body={response.text[:300]}"
            )
        return response.json()

    # -- Hotel APIs --------------------------------------------------------

    async def list_hotels_by_city(
        self,
        city_code: str,
        *,
        radius: int | None = None,
        radius_unit: str | None = None,
        amenities: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Hotel List API — by city code (e.g. "PAR" for Paris).

        Optional filters: radius (with radius_unit), amenities (list of codes).
        """
        params: dict[str, Any] = {"cityCode": city_code}
        if radius is not None:
            params["radius"] = radius
        if radius_unit:
            params["radiusUnit"] = radius_unit
        if amenities:
            params["amenities"] = ",".join(amenities)
        return await self._get("/v1/reference-data/locations/hotels/by-city", params)

    async def search_hotels(
        self,
        *,
        city_code: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius: int | None = None,
        radius_unit: str | None = None,
        check_in_date: str | None = None,
        check_out_date: str | None = None,
        adults: int | None = None,
        room_quantity: int | None = None,
        price_range: str | None = None,
        currency: str | None = None,
        amenities: list[str] | None = None,
        max_results: int | None = None,
    ) -> dict[str, Any]:
        """
        Hotel Search API v3 — cheapest hotels in a location with filters.

        Either city_code OR (latitude + longitude) must be provided.
        """
        if not city_code and (latitude is None or longitude is None):
            raise AmadeusError("search_hotels requires either city_code or (latitude AND longitude)")

        params: dict[str, Any] = {}
        if city_code:
            params["cityCode"] = city_code
        else:
            params["latitude"] = latitude
            params["longitude"] = longitude
            if radius is not None:
                params["radius"] = radius
            if radius_unit:
                params["radiusUnit"] = radius_unit
        if check_in_date:
            params["checkInDate"] = check_in_date
        if check_out_date:
            params["checkOutDate"] = check_out_date
        if adults is not None:
            params["adults"] = adults
        if room_quantity is not None:
            params["roomQuantity"] = room_quantity
        if price_range:
            params["priceRange"] = price_range
        if currency:
            params["currency"] = currency
        if amenities:
            params["amenities"] = ",".join(amenities)
        if max_results is not None:
            params["max"] = min(max(1, max_results), 100)

        return await self._get("/v3/shopping/hotel-offers", params)

    async def autocomplete_hotel_name(self, keyword: str) -> dict[str, Any]:
        """
        Hotel Name Autocomplete API — up to 20 hotels matching the keyword.
        """
        return await self._get("/v1/reference-data/locations/hotel", {"keyword": keyword})

    async def get_hotel_ratings(self, hotel_ids: list[str]) -> dict[str, Any]:
        """
        Hotel Ratings API — sentiment-based ratings for a list of hotel IDs.

        hotel_ids is capped at 100 per call.
        """
        if not hotel_ids:
            raise AmadeusError("get_hotel_ratings requires at least one hotel_id")
        capped = hotel_ids[:100]
        return await self._get(
            "/v2/e-reputation/hotel-sentiments",
            {"hotelIds": ",".join(capped)},
        )


__all__ = ["AmadeusClient", "AmadeusError", "AmadeusAuthError"]
