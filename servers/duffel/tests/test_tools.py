"""Tests for Duffel tools."""

import httpx
import pytest

from servers.duffel.client import DuffelClient
from servers.duffel.tools import (
    BookFlightTool,
    CancelBookingTool,
    GetBookingTool,
    GetOfferTool,
    SearchFlightsTool,
)


@pytest.fixture
def mock_client():
    """Mock Duffel client for testing."""
    client = DuffelClient(api_key="test_key")
    
    # Mock transport (same as test_client.py)
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/air/offer_requests":
            return httpx.Response(200, json={"data": {"offers": [
                {
                    "id": "off_123",
                    "total_amount": "250.00",
                    "total_currency": "USD",
                    "owner": {"name": "Test Air"},
                    "slices": [{
                        "origin": {"iata_code": "JFK"},
                        "destination": {"iata_code": "SFO"},
                        "duration": "PT6H",
                        "segments": [{
                            "departing_at": "2026-07-15T08:00:00Z",
                            "arriving_at": "2026-07-15T14:00:00Z",
                        }],
                    }],
                }
            ]}})
        
        if "/air/offers/" in request.url.path:
            return httpx.Response(200, json={"data": {
                "id": "off_123",
                "total_amount": "250.00",
                "total_currency": "USD",
                "owner": {"name": "Test Air"},
                "expires_at": "2026-07-14T00:00:00Z",
                "slices": [{
                    "origin": {"iata_code": "JFK", "name": "JFK Airport"},
                    "destination": {"iata_code": "SFO", "name": "SFO Airport"},
                    "duration": "PT6H",
                    "segments": [{
                        "departing_at": "2026-07-15T08:00:00Z",
                        "arriving_at": "2026-07-15T14:00:00Z",
                        "marketing_carrier": {"iata_code": "AA"},
                        "marketing_carrier_flight_number": "100",
                        "aircraft": {"name": "Boeing 737"},
                        "origin": {"iata_code": "JFK"},
                        "destination": {"iata_code": "SFO"},
                    }],
                }],
                "passengers": [{"type": "adult"}],
                "conditions": {},
            }})
        
        if request.url.path == "/air/orders" and request.method == "POST":
            return httpx.Response(201, json={"data": {
                "id": "ord_123",
                "booking_reference": "ABC123",
                "total_amount": "250.00",
                "total_currency": "USD",
                "passengers": [{"given_name": "John", "family_name": "Doe", "type": "adult"}],
                "slices": [{
                    "origin": {"iata_code": "JFK"},
                    "destination": {"iata_code": "SFO"},
                    "segments": [{
                        "departing_at": "2026-07-15T08:00:00Z",
                        "arriving_at": "2026-07-15T14:00:00Z",
                    }],
                }],
            }})
        
        if "/air/orders/" in request.url.path and request.method == "GET":
            return httpx.Response(200, json={"data": {
                "id": "ord_123",
                "booking_reference": "ABC123",
                "total_amount": "250.00",
                "total_currency": "USD",
                "created_at": "2026-07-14T10:00:00Z",
                "passengers": [{"given_name": "John", "family_name": "Doe", "type": "adult"}],
                "slices": [{
                    "origin": {"iata_code": "JFK", "name": "JFK Airport"},
                    "destination": {"iata_code": "SFO", "name": "SFO Airport"},
                    "duration": "PT6H",
                    "segments": [{
                        "departing_at": "2026-07-15T08:00:00Z",
                        "arriving_at": "2026-07-15T14:00:00Z",
                    }],
                }],
                "documents": [],
            }})
        
        if request.url.path == "/air/order_cancellations":
            return httpx.Response(201, json={"data": {
                "id": "can_123",
                "order_id": "ord_123",
                "refund_amount": "200.00",
                "refund_currency": "USD",
                "confirmed_at": "2026-07-14T11:00:00Z",
            }})
        
        return httpx.Response(404)
    
    client.client._transport = httpx.MockTransport(handler)
    return client


@pytest.mark.asyncio
async def test_search_flights_tool(mock_client):
    """Test search_flights tool."""
    tool = SearchFlightsTool(mock_client)
    
    result = await tool.call({
        "origin": "jfk",
        "destination": "sfo",
        "departure_date": "2026-07-15",
        "passengers": 1,
        "cabin_class": "economy",
    })
    
    assert "result" in result
    assert result["result"]["offer_count"] >= 1
    assert len(result["result"]["offers"]) >= 1
    assert result["result"]["offers"][0]["offer_id"] == "off_123"


@pytest.mark.asyncio
async def test_get_offer_tool(mock_client):
    """Test get_offer tool."""
    tool = GetOfferTool(mock_client)
    
    result = await tool.call({"offer_id": "off_123"})
    
    assert "result" in result
    assert result["result"]["offer_id"] == "off_123"
    assert result["result"]["total_amount"] == "250.00"


@pytest.mark.asyncio
async def test_book_flight_tool_without_confirmation(mock_client, monkeypatch):
    """Test book_flight tool without confirmation flag."""
    monkeypatch.delenv("MCPTOOLING_CONFIRM_BOOKING", raising=False)
    
    tool = BookFlightTool(mock_client)
    
    result = await tool.call({
        "offer_id": "off_123",
        "passengers": [{
            "given_name": "John",
            "family_name": "Doe",
            "born_on": "1990-01-01",
        }],
        "payment": {"type": "balance", "amount": "250.00", "currency": "USD"},
    })
    
    assert "error" in result
    assert "not confirmed" in result["error"]


@pytest.mark.asyncio
async def test_book_flight_tool_with_confirmation(mock_client, monkeypatch):
    """Test book_flight tool with confirmation flag."""
    monkeypatch.setenv("MCPTOOLING_CONFIRM_BOOKING", "true")
    
    tool = BookFlightTool(mock_client)
    
    result = await tool.call({
        "offer_id": "off_123",
        "passengers": [{
            "given_name": "John",
            "family_name": "Doe",
            "born_on": "1990-01-01",
        }],
        "payment": {"type": "balance", "amount": "250.00", "currency": "USD"},
    })
    
    assert "result" in result
    assert result["result"]["order_id"] == "ord_123"
    assert result["result"]["status"] == "booked"


@pytest.mark.asyncio
async def test_get_booking_tool(mock_client):
    """Test get_booking tool."""
    tool = GetBookingTool(mock_client)
    
    result = await tool.call({"order_id": "ord_123"})
    
    assert "result" in result
    assert result["result"]["order_id"] == "ord_123"
    assert result["result"]["booking_reference"] == "ABC123"


@pytest.mark.asyncio
async def test_cancel_booking_tool_without_confirmation(mock_client, monkeypatch):
    """Test cancel_booking tool without confirmation flag."""
    monkeypatch.delenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", raising=False)
    
    tool = CancelBookingTool(mock_client)
    
    result = await tool.call({"order_id": "ord_123"})
    
    assert "error" in result
    assert "not confirmed" in result["error"]


@pytest.mark.asyncio
async def test_cancel_booking_tool_with_confirmation(mock_client, monkeypatch):
    """Test cancel_booking tool with confirmation flag."""
    monkeypatch.setenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", "true")
    
    tool = CancelBookingTool(mock_client)
    
    result = await tool.call({"order_id": "ord_123"})
    
    assert "result" in result
    assert result["result"]["order_id"] == "ord_123"
    assert result["result"]["status"] == "cancelled"
