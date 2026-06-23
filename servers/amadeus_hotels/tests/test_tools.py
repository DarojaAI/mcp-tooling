"""Tests for the Amadeus Hotels tools.

Strategy: build an AmadeusClient and monkeypatch httpx.AsyncClient to
return canned responses, then call each tool's .call() and assert on
the structured result.
"""

from __future__ import annotations

import pytest

from servers.amadeus_hotels.client import AmadeusClient
from servers.amadeus_hotels.tools import (
    AutocompleteHotelNameTool,
    GetHotelRatingsTool,
    ListHotelsByCityTool,
    SearchHotelsTool,
)


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


def _client():
    return AmadeusClient(client_id="test", client_secret="***")


def _patch(monkeypatch, response_body):
    """Patch httpx.AsyncClient to return the given response body for all non-token requests."""

    def route(method, url, *, data=None, params=None, headers=None):
        if "oauth2/token" in url:
            return _MockResponse(200, {"access_token": "t", "expires_in": 1800})
        return _MockResponse(200, response_body)

    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **kw: _MockAsyncClient(route, **kw),
    )


# ---------------------------------------------------------------------------
# list_hotels_by_city tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_hotels_by_city_tool(monkeypatch):
    body = {
        "data": [
            {
                "hotelId": "HTLPAR001",
                "name": "Hotel Lutetia",
                "iataCode": "PAR",
                "address": {"cityName": "Paris", "countryCode": "FR"},
                "geoCode": {"latitude": 48.842, "longitude": 2.327},
                "chainCode": "LT",
            },
            {
                "hotelId": "HTLPAR002",
                "name": "Hotel Rivoli",
                "iataCode": "PAR",
                "address": {"cityName": "Paris", "countryCode": "FR"},
                "geoCode": {"latitude": 48.857, "longitude": 2.351},
            },
        ]
    }
    tool = ListHotelsByCityTool(_client())
    _patch(monkeypatch, body)
    result = await tool.call({"city_code": "PAR"})

    assert "result" in result
    assert result["result"]["city_code"] == "PAR"
    assert result["result"]["hotel_count"] == 2
    assert result["result"]["hotels"][0]["hotel_id"] == "HTLPAR001"
    assert result["result"]["hotels"][0]["name"] == "Hotel Lutetia"


# ---------------------------------------------------------------------------
# search_hotels tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_hotels_tool(monkeypatch):
    body = {
        "data": [
            {
                "hotel": {
                    "hotelId": "HTLPAR001",
                    "name": "Hotel Lutetia",
                    "rating": "5",
                    "cityCode": "PAR",
                    "latitude": 48.842,
                    "longitude": 2.327,
                },
                "offers": [
                    {
                        "id": "OFF001",
                        "price": {"total": "250.00", "currency": "EUR"},
                    }
                ],
            }
        ]
    }
    tool = SearchHotelsTool(_client())
    _patch(monkeypatch, body)
    result = await tool.call(
        {"city_code": "PAR", "adults": 2, "check_in_date": "2026-08-01", "check_out_date": "2026-08-03"}
    )

    assert "result" in result
    assert result["result"]["hotel_count"] == 1
    hotel = result["result"]["hotels"][0]
    assert hotel["hotel_id"] == "HTLPAR001"
    assert hotel["price_total"] == "250.00"
    assert hotel["price_currency"] == "EUR"


@pytest.mark.asyncio
async def test_search_hotels_tool_with_coordinates(monkeypatch):
    """lat/lon path must work without city_code."""
    tool = SearchHotelsTool(_client())
    _patch(monkeypatch, {"data": []})
    result = await tool.call({"latitude": 48.8566, "longitude": 2.3522, "radius": 5, "radius_unit": "KM"})

    assert result["result"]["hotel_count"] == 0


# ---------------------------------------------------------------------------
# autocomplete_hotel_name tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autocomplete_hotel_name_tool(monkeypatch):
    body = {
        "data": [
            {
                "hotelId": "HTLHLT01",
                "name": "Hilton Paris Opera",
                "iataCode": "PAR",
                "address": {"cityName": "Paris"},
            }
        ]
    }
    tool = AutocompleteHotelNameTool(_client())
    _patch(monkeypatch, body)
    result = await tool.call({"keyword": "hilton"})

    assert result["result"]["keyword"] == "hilton"
    assert result["result"]["hotel_count"] == 1
    assert result["result"]["hotels"][0]["name"] == "Hilton Paris Opera"


# ---------------------------------------------------------------------------
# get_hotel_ratings tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_hotel_ratings_tool(monkeypatch):
    body = {
        "data": [
            {"hotelId": "HTLPAR001", "overallRating": 92, "categories": {"location": 95, "service": 88}},
        ]
    }
    tool = GetHotelRatingsTool(_client())
    _patch(monkeypatch, body)
    result = await tool.call({"hotel_ids": ["HTLPAR001"]})

    assert result["result"]["rating_count"] == 1
    assert result["result"]["ratings"][0]["hotelId"] == "HTLPAR001"


@pytest.mark.asyncio
async def test_get_hotel_ratings_dict_response(monkeypatch):
    """Some API versions return ratings keyed by hotelId, not in an array. Normalize."""
    body = {
        "data": {
            "HTLPAR001": {"overallRating": 92, "categories": {"location": 95}},
            "HTLPAR002": {"overallRating": 78, "categories": {"location": 80}},
        }
    }
    tool = GetHotelRatingsTool(_client())
    _patch(monkeypatch, body)
    result = await tool.call({"hotel_ids": ["HTLPAR001", "HTLPAR002"]})

    assert result["result"]["rating_count"] == 2
    ids = sorted(r["hotel_id"] for r in result["result"]["ratings"])
    assert ids == ["HTLPAR001", "HTLPAR002"]
