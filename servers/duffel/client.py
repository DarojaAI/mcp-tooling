"""
Duffel API client wrapper.

Thin async wrapper over the Duffel REST API. No business logic - just SDK calls.
"""

from typing import Any

import httpx


class DuffelClient:
    """
    Async HTTP client for Duffel API.
    
    Usage:
        client = DuffelClient(api_key="duffel_test_...", base_url="https://api.duffel.com")
        offers = await client.search_offers(origin="JFK", destination="SFO", departure_date="2026-07-15")
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.duffel.com",
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Duffel-Version": "v2",
            },
            timeout=timeout,
        )
    
    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def search_offers(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        passengers: list[dict[str, Any]] | None = None,
        cabin_class: str = "economy",
        return_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Search for flight offers.
        
        Args:
            origin: IATA airport code (e.g., "JFK")
            destination: IATA airport code (e.g., "SFO")
            departure_date: ISO date string (YYYY-MM-DD)
            passengers: List of passenger dicts (default: 1 adult)
            cabin_class: "economy", "premium_economy", "business", or "first"
            return_date: Optional return date for round-trip
        
        Returns:
            Duffel offer request response
        """
        if passengers is None:
            passengers = [{"type": "adult"}]
        
        slices = [
            {
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date,
            }
        ]
        
        if return_date:
            slices.append(
                {
                    "origin": destination,
                    "destination": origin,
                    "departure_date": return_date,
                }
            )
        
        payload = {
            "data": {
                "slices": slices,
                "passengers": passengers,
                "cabin_class": cabin_class,
            }
        }
        
        response = await self.client.post("/air/offer_requests", json=payload)
        response.raise_for_status()
        return response.json()
    
    async def get_offer(self, offer_id: str) -> dict[str, Any]:
        """
        Get details for a specific offer.
        
        Args:
            offer_id: Duffel offer ID
        
        Returns:
            Offer details
        """
        response = await self.client.get(f"/air/offers/{offer_id}")
        response.raise_for_status()
        return response.json()
    
    async def create_order(
        self,
        offer_id: str,
        passengers: list[dict[str, Any]],
        payment: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Create an order (book a flight).
        
        Args:
            offer_id: Duffel offer ID to book
            passengers: List of passenger details (name, email, phone, etc.)
            payment: Payment details
        
        Returns:
            Order details
        """
        payload = {
            "data": {
                "selected_offers": [offer_id],
                "passengers": passengers,
                "payments": [payment],
            }
        }
        
        response = await self.client.post("/air/orders", json=payload)
        response.raise_for_status()
        return response.json()
    
    async def get_order(self, order_id: str) -> dict[str, Any]:
        """
        Get order details.
        
        Args:
            order_id: Duffel order ID
        
        Returns:
            Order details
        """
        response = await self.client.get(f"/air/orders/{order_id}")
        response.raise_for_status()
        return response.json()
    
    async def cancel_order(
        self,
        order_id: str,
    ) -> dict[str, Any]:
        """
        Cancel an order.
        
        Args:
            order_id: Duffel order ID
        
        Returns:
            Cancellation details
        """
        payload = {
            "data": {
                "order_id": order_id,
            }
        }
        
        response = await self.client.post("/air/order_cancellations", json=payload)
        response.raise_for_status()
        return response.json()
