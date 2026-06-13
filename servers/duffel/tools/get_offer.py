"""Get offer details tool."""

from typing import Any
from runtime.base import BaseTool
from servers.duffel.client import DuffelClient
import httpx


class GetOfferTool(BaseTool):
    """Get detailed information about a specific flight offer."""
    
    def __init__(self, client: DuffelClient):
        self.client = client
    
    @property
    def tool_name(self) -> str:
        return "get_offer"
    
    @property
    def description(self) -> str:
        return "Get detailed information about a specific flight offer by ID"
    
    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "offer_id": {
                    "type": "string",
                    "description": "Duffel offer ID (from search_flights result)",
                },
            },
            "required": ["offer_id"],
        }
    
    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        """Get offer details."""
        try:
            response = await self.client.get_offer(args["offer_id"])
            offer = response.get("data", {})
            
            return {
                "result": {
                    "offer_id": offer["id"],
                    "total_amount": offer["total_amount"],
                    "total_currency": offer["total_currency"],
                    "airline": offer["owner"]["name"],
                    "expires_at": offer["expires_at"],
                    "slices": [
                        {
                            "origin": s["origin"]["iata_code"],
                            "origin_name": s["origin"]["name"],
                            "destination": s["destination"]["iata_code"],
                            "destination_name": s["destination"]["name"],
                            "departure_time": s["segments"][0]["departing_at"],
                            "arrival_time": s["segments"][-1]["arriving_at"],
                            "duration": s["duration"],
                            "segments": [
                                {
                                    "flight_number": seg["marketing_carrier"]["iata_code"] + seg["marketing_carrier_flight_number"],
                                    "aircraft": seg["aircraft"]["name"],
                                    "origin": seg["origin"]["iata_code"],
                                    "destination": seg["destination"]["iata_code"],
                                    "departing_at": seg["departing_at"],
                                    "arriving_at": seg["arriving_at"],
                                }
                                for seg in s["segments"]
                            ],
                        }
                        for s in offer["slices"]
                    ],
                    "passenger_count": len(offer["passengers"]),
                    "conditions": offer.get("conditions", {}),
                }
            }
        
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Duffel API error: {e.response.status_code}",
                "details": e.response.text[:500],
            }
        except Exception as e:
            return {
                "error": "Internal error fetching offer",
                "details": str(e)[:500],
            }
