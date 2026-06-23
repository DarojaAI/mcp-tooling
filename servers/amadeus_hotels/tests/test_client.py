"""Tests for AmadeusClient.

Strategy: monkeypatch httpx.AsyncClient to use a mock transport that
returns canned responses based on request URL + method. This avoids
real network calls and keeps tests fast.
"""

from __future__ import annotations

import pytest

from servers.amadeus_hotels.client import (
    AmadeusAuthError,
    AmadeusClient,
    AmadeusError,
)

# ---------------------------------------------------------------------------
# Token exchange mocking
# ---------------------------------------------------------------------------


class _MockAsyncClient:
    """Stand-in for httpx.AsyncClient that uses a routing function."""

    def __init__(self, routing_fn, **kwargs):
        self._routing_fn = routing_fn
        self._kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, *, data=None, headers=None):
        return self._routing_fn("POST", url, data=data, headers=headers)

    async def get(self, url, *, params=None, headers=None):
        return self._routing_fn("GET", url, params=params, headers=headers)


class _MockResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = body if isinstance(body, str) else str(body)

    def json(self):
        if isinstance(self._body, (dict, list)):
            return self._body
        raise ValueError(self.text)


@pytest.fixture(autouse=True)
def patch_async_client(monkeypatch):
    """Replace httpx.AsyncClient with the mock for every test."""
    patches = {"patches": []}
    yield patches


def _make_token_route():
    """Build a routing fn that handles the OAuth token exchange + canned API responses."""

    def factory(responses: dict):
        token_response = {
            "access_token": "fake_token_xyz",
            "expires_in": 1800,
        }

        def route(method, url, *, data=None, params=None, headers=None):
            # OAuth token endpoint
            if "oauth2/token" in url:
                return _MockResponse(200, token_response)
            # Otherwise, match by path
            for path, body in responses.items():
                if path in url:
                    return _MockResponse(200, body)
            return _MockResponse(404, {"error": "not_found", "path": url})

        return route

    return factory


@pytest.mark.asyncio
async def test_client_rejects_empty_credentials():
    with pytest.raises(AmadeusError, match="AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET are required"):
        AmadeusClient(client_id="", client_secret="***")


@pytest.mark.asyncio
async def test_client_rejects_invalid_env():
    with pytest.raises(AmadeusError, match="AMADEUS_ENV must be"):
        AmadeusClient(client_id="x", client_secret="***", env="staging")


@pytest.mark.asyncio
async def test_client_default_env_is_test():
    c = AmadeusClient(client_id="x", client_secret="***")
    assert c.env == "test"


@pytest.mark.asyncio
async def test_client_env_set_to_production():
    c = AmadeusClient(client_id="x", client_secret="***", env="production")
    assert c.env == "production"


@pytest.mark.asyncio
async def test_search_hotels_requires_city_or_coords():
    c = AmadeusClient(client_id="x", client_secret="***")
    with pytest.raises(AmadeusError, match="requires either city_code"):
        await c.search_hotels()


@pytest.mark.asyncio
async def test_search_hotels_requires_both_lat_and_lon():
    c = AmadeusClient(client_id="x", client_secret="***")
    with pytest.raises(AmadeusError):
        await c.search_hotels(latitude=48.8566)  # no longitude


@pytest.mark.asyncio
async def test_get_hotel_ratings_requires_at_least_one_id():
    c = AmadeusClient(client_id="x", client_secret="***")
    with pytest.raises(AmadeusError, match="at least one hotel_id"):
        await c.get_hotel_ratings([])


@pytest.mark.asyncio
async def test_get_hotel_ratings_caps_at_100(monkeypatch):
    """hotel_ids > 100 must be silently capped (Amadeus API limit)."""
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _MockAsyncClient(_make_token_route()({}), **kw),
    )
    captured = {}

    def _capturing_route(method, url, *, data=None, params=None, headers=None):
        if "oauth2/token" in url:
            return _MockResponse(200, {"access_token": "t", "expires_in": 1800})
        captured.update(params or {})
        return _MockResponse(200, {"data": []})

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _MockAsyncClient(_capturing_route, **kw),
    )
    c = AmadeusClient(client_id="x", client_secret="***")
    # 150 ids → should be capped to 100 in the request.
    long_ids = [f"HTL{i:04d}" for i in range(150)]
    await c.get_hotel_ratings(long_ids)
    sent_ids = captured["hotelIds"].split(",")
    assert len(sent_ids) == 100


@pytest.mark.asyncio
async def test_token_refresh_on_first_call(monkeypatch):
    """First authenticated call must trigger a token exchange."""
    token_calls = {"count": 0}

    def route(method, url, *, data=None, params=None, headers=None):
        if "oauth2/token" in url:
            token_calls["count"] += 1
            return _MockResponse(200, {"access_token": "t", "expires_in": 1800})
        # Verify Bearer token was sent.
        assert headers["Authorization"] == "Bearer t"
        return _MockResponse(200, {"data": []})

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _MockAsyncClient(route, **kw),
    )
    c = AmadeusClient(client_id="x", client_secret="***")
    await c.list_hotels_by_city(city_code="PAR")
    assert token_calls["count"] == 1


@pytest.mark.asyncio
async def test_token_reused_within_lifetime(monkeypatch):
    """Multiple calls within the token lifetime must reuse the token (no re-exchange)."""
    token_calls = {"count": 0}

    def route(method, url, *, data=None, params=None, headers=None):
        if "oauth2/token" in url:
            token_calls["count"] += 1
            return _MockResponse(200, {"access_token": "t", "expires_in": 1800})
        return _MockResponse(200, {"data": []})

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _MockAsyncClient(route, **kw),
    )
    c = AmadeusClient(client_id="x", client_secret="***")
    await c.list_hotels_by_city(city_code="PAR")
    await c.search_hotels(city_code="PAR")
    await c.autocomplete_hotel_name(keyword="hilton")
    # Only the first call should have fetched a token.
    assert token_calls["count"] == 1


@pytest.mark.asyncio
async def test_token_refresh_when_expired(monkeypatch):
    """Token near expiry should trigger a refresh."""
    token_calls = {"count": 0}

    def route(method, url, *, data=None, params=None, headers=None):
        if "oauth2/token" in url:
            token_calls["count"] += 1
            return _MockResponse(200, {"access_token": "t", "expires_in": 1800})
        return _MockResponse(200, {"data": []})

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _MockAsyncClient(route, **kw),
    )
    c = AmadeusClient(client_id="x", client_secret="***")
    await c.list_hotels_by_city(city_code="PAR")  # first call → token #1
    # Force-expire the token by setting expires_at to the past.
    c._expires_at = 0  # epoch 0 = 1970, well past expiry
    await c.search_hotels(city_code="PAR")  # should refresh
    assert token_calls["count"] == 2


@pytest.mark.asyncio
async def test_auth_error_on_token_failure(monkeypatch):
    """A 401 from the OAuth endpoint must raise AmadeusAuthError."""

    def route(method, url, *, data=None, params=None, headers=None):
        if "oauth2/token" in url:
            return _MockResponse(401, {"error": "invalid_client"})
        return _MockResponse(200, {"data": []})

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _MockAsyncClient(route, **kw),
    )
    c = AmadeusClient(client_id="x", client_secret="***")
    with pytest.raises(AmadeusAuthError):
        await c.list_hotels_by_city(city_code="PAR")


@pytest.mark.asyncio
async def test_api_error_propagated(monkeypatch):
    """A non-200 from the API must raise AmadeusError."""

    def route(method, url, *, data=None, params=None, headers=None):
        if "oauth2/token" in url:
            return _MockResponse(200, {"access_token": "t", "expires_in": 1800})
        return _MockResponse(500, {"error": "internal"})

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _MockAsyncClient(route, **kw),
    )
    c = AmadeusClient(client_id="x", client_secret="***")
    with pytest.raises(AmadeusError):
        await c.list_hotels_by_city(city_code="PAR")
