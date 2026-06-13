"""Get booking details tool."""

from typing import Any
from runtime.base import BaseTool
from servers.duffel.client import DuffelClient
import httpx


class GetBookingTool(BaseTool):
    """Get details of an existing booking/order."""
    
    def __init__(self, client: DuffelClient):
        self.client = client
    
    @property
    def tool_name(self) -> str:
        return "get_booking"
    
    @property
    def description(self) -> str:
        return "Get details of an existing flight booking by order ID"
    
    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Duffel order ID",
                },
            },
            "required": ["order_id"],
        }
    
    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get booking details."""
        try:
            response = await self.client.get_order(args["order_id"])
            order = response.get("data", {})
            
            return {
                "result": {
                    "order_id": order["id"],
                    "booking_reference": order.get("booking_reference"),
                    "total_amount": order["total_amount"],
                    "total_currency": order["total_currency"],
                    "created_at": order["created_at"],
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
                            "origin_name": s["origin"]["name"],
                            "destination": s["destination"]["iata_code"],
                            "destination_name": s["destination"]["name"],
                            "departure_time": s["segments"][0]["departing_at"],
                            "arrival_time": s["segments"][-1]["arriving_at"],
                            "duration": s["duration"],
                        }
                        for s in order["slices"]
                    ],
                    "documents": [
                        {
                            "type": doc["type"],
                            "passenger_id": doc.get("passenger_id"),
                        }
                        for doc in order.get("documents", [])
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
                "error": "Internal error fetching booking",
                "details": str(e)[:500],
            }
