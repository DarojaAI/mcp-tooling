"""Tests for Duffel client."""

import httpx
import pytest

from servers.duffel.client import DuffelClient


@pytest.fixture
def mock_transport():
    """Mock httpx transport for testing."""
    def handler(request: httpx.Request) -> httpx.Response:
        # Mock search_offers
        if request.url.path == "/air/offer_requests" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "offers": [
                            {
                                "id": "off_test123",
                                "total_amount": "250.00",
                                "total_currency": "USD",
                                "owner": {"name": "Test Airlines"},
                                "slices": [
                                    {
                                        "origin": {"iata_code": "JFK", "name": "John F Kennedy Intl"},
                                        "destination": {"iata_code": "SFO", "name": "San Francisco Intl"},
                                        "duration": "PT6H",
                                        "segments": [
                                            {
                                                "departing_at": "2026-07-15T08:00:00Z",
                                                "arriving_at": "2026-07-15T14:00:00Z",
                                                "marketing_carrier": {"iata_code": "AA"},
                                                "marketing_carrier_flight_number": "100",
                                                "aircraft": {"name": "Boeing 737"},
                                                "origin": {"iata_code": "JFK"},
                                                "destination": {"iata_code": "SFO"},
                                            }
                                        ],
                                    }
                                ],
                                "passengers": [{"type": "adult"}],
                                "expires_at": "2026-07-14T00:00:00Z",
                                "conditions": {},
                            }
                        ]
                    }
                },
            )
        
        # Mock get_offer
        if request.url.path.startswith("/air/offers/") and request.method == "GET":
            offer_id = request.url.path.split("/")[-1]
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": offer_id,
                        "total_amount": "250.00",
                        "total_currency": "USD",
                        "owner": {"name": "Test Airlines"},
                        "slices": [],
                        "passengers": [{"type": "adult"}],
                        "expires_at": "2026-07-14T00:00:00Z",
                        "conditions": {},
                    }
                },
            )
        
        # Mock create_order
        if request.url.path == "/air/orders" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "ord_test123",
                        "booking_reference": "ABC123",
                        "total_amount": "250.00",
                        "total_currency": "USD",
                        "created_at": "2026-07-14T10:00:00Z",
                        "passengers": [
                            {
                                "given_name": "John",
                                "family_name": "Doe",
                                "type": "adult",
                            }
                        ],
                        "slices": [],
                    }
                },
            )
        
        # Mock get_order
        if request.url.path.startswith("/air/orders/") and request.method == "GET":
            order_id = request.url.path.split("/")[-1]
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": order_id,
                        "booking_reference": "ABC123",
                        "total_amount": "250.00",
                        "total_currency": "USD",
                        "created_at": "2026-07-14T10:00:00Z",
                        "passengers": [],
                        "slices": [],
                        "documents": [],
                    }
                },
            )
        
        # Mock cancel_order
        if request.url.path == "/air/order_cancellations" and request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "can_test123",
                        "order_id": "ord_test123",
                        "refund_amount": "200.00",
                        "refund_currency": "USD",
                        "confirmed_at": "2026-07-14T11:00:00Z",
                    }
                },
            )
        
        return httpx.Response(404, json={"error": "Not found"})
    
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_search_offers(mock_transport):
    """Test searching for flight offers."""
    client = DuffelClient(api_key="test_key")
    client.client._transport = mock_transport
    
    result = await client.search_offers(
        origin="JFK",
        destination="SFO",
        departure_date="2026-07-15",
    )
    
    assert "data" in result
    assert len(result["data"]["offers"]) > 0
    assert result["data"]["offers"][0]["id"] == "off_test123"
    
    await client.close()


@pytest.mark.asyncio
async def test_get_offer(mock_transport):
    """Test getting offer details."""
    client = DuffelClient(api_key="test_key")
    client.client._transport = mock_transport
    
    result = await client.get_offer("off_test123")
    
    assert result["data"]["id"] == "off_test123"
    assert result["data"]["total_amount"] == "250.00"
    
    await client.close()


@pytest.mark.asyncio
async def test_create_order(mock_transport):
    """Test creating an order."""
    client = DuffelClient(api_key="test_key")
    client.client._transport = mock_transport
    
    result = await client.create_order(
        offer_id="off_test123",
        passengers=[
            {
                "given_name": "John",
                "family_name": "Doe",
                "born_on": "1990-01-01",
            }
        ],
        payment={"type": "balance", "amount": "250.00", "currency": "USD"},
    )
    
    assert result["data"]["id"] == "ord_test123"
    assert result["data"]["booking_reference"] == "ABC123"
    
    await client.close()


@pytest.mark.asyncio
async def test_get_order(mock_transport):
    """Test getting order details."""
    client = DuffelClient(api_key="test_key")
    client.client._transport = mock_transport
    
    result = await client.get_order("ord_test123")
    
    assert result["data"]["id"] == "ord_test123"
    
    await client.close()


@pytest.mark.asyncio
async def test_cancel_order(mock_transport):
    """Test cancelling an order."""
    client = DuffelClient(api_key="test_key")
    client.client._transport = mock_transport
    
    result = await client.cancel_order("ord_test123")
    
    assert result["data"]["order_id"] == "ord_test123"
    assert result["data"]["refund_amount"] == "200.00"
    
    await client.close()
