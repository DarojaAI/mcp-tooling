"""Book flight tool."""

import os
from typing import Any

import httpx

from runtime.base import BaseTool
from servers.duffel.client import DuffelClient


class BookFlightTool(BaseTool):
    """
    Book a flight offer.
    
    REQUIRES confirmation: Set MCPTOOLING_CONFIRM_BOOKING=true to enable.
    This is a defensive two-step pattern to prevent accidental bookings.
    """
    
    def __init__(self, client: DuffelClient):
        self.client = client
    
    @property
    def tool_name(self) -> str:
        return "book_flight"
    
    @property
    def description(self) -> str:
        return "Book a flight offer (requires MCPTOOLING_CONFIRM_BOOKING=true)"
    
    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "offer_id": {
                    "type": "string",
                    "description": "Duffel offer ID to book",
                },
                "passengers": {
                    "type": "array",
                    "description": "List of passenger details",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "enum": ["mr", "ms", "mrs", "miss", "dr"]},
                            "given_name": {"type": "string"},
                            "family_name": {"type": "string"},
                            "born_on": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                            "email": {"type": "string", "format": "email"},
                            "phone_number": {"type": "string"},
                        },
                        "required": ["given_name", "family_name", "born_on"],
                    },
                },
                "payment": {
                    "type": "object",
                    "description": "Payment details",
                    "properties": {
                        "type": {"type": "string", "enum": ["balance"]},
                        "amount": {"type": "string"},
                        "currency": {"type": "string"},
                    },
                    "required": ["type", "amount", "currency"],
                },
            },
            "required": ["offer_id", "passengers", "payment"],
        }
    
    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        """Book a flight."""
        # Check confirmation flag
        confirm = os.getenv("MCPTOOLING_CONFIRM_BOOKING", "false").lower() == "true"
        
        if not confirm:
            return {
                "error": "Booking not confirmed",
                "details": "Set MCPTOOLING_CONFIRM_BOOKING=true to enable flight booking. This is a safety gate to prevent accidental bookings.",
            }
        
        try:
            response = await self.client.create_order(
                offer_id=args["offer_id"],
                passengers=args["passengers"],
                payment=args["payment"],
            )
            
            order = response.get("data", {})
            
            return {
                "result": {
                    "order_id": order["id"],
                    "booking_reference": order.get("booking_reference"),
                    "total_amount": order["total_amount"],
                    "total_currency": order["total_currency"],
                    "status": "booked",
                    "passengers": [
                        {
                            "name": f"{p['given_name']} {p['family_name']}",
                            "type": p["type"],
                        }
                        for p in order["passengers"]
                    ],
                    "slices": [
                        {
                            "origin": s["origin"]["iata_code"],
                            "destination": s["destination"]["iata_code"],
                            "departure_time": s["segments"][0]["departing_at"],
                            "arrival_time": s["segments"][-1]["arriving_at"],
                        }
                        for s in order["slices"]
                    ],
                }
            }
        
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Duffel API error: {e.response.status_code}",
                "details": e.response.text[:500],
            }
        except Exception as e:
            return {
                "error": "Internal error during booking",
                "details": str(e)[:500],
            }
