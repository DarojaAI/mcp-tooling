"""Search flights tool."""

from typing import Any

import httpx

from runtime.base import BaseTool
from servers.duffel.client import DuffelClient


class SearchFlightsTool(BaseTool):
    """Search for flight offers."""
    
    def __init__(self, client: DuffelClient):
        self.client = client
    
    @property
    def tool_name(self) -> str:
        return "search_flights"
    
    @property
    def description(self) -> str:
        return "Search for flight offers between two airports on a specific date"
    
    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin airport IATA code (e.g., JFK, LHR)",
                    "minLength": 3,
                    "maxLength": 3,
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code (e.g., SFO, CDG)",
                    "minLength": 3,
                    "maxLength": 3,
                },
                "departure_date": {
                    "type": "string",
                    "description": "Departure date in YYYY-MM-DD format",
                    "pattern": r"^\d{4}-\d{2}-\d{2}$",
                },
                "return_date": {
                    "type": "string",
                    "description": "Optional return date for round-trip in YYYY-MM-DD format",
                    "pattern": r"^\d{4}-\d{2}-\d{2}$",
                },
                "passengers": {
                    "type": "integer",
                    "description": "Number of adult passengers",
                    "minimum": 1,
                    "maximum": 9,
                    "default": 1,
                },
                "cabin_class": {
                    "type": "string",
                    "description": "Cabin class preference",
                    "enum": ["economy", "premium_economy", "business", "first"],
                    "default": "economy",
                },
            },
            "required": ["origin", "destination", "departure_date"],
        }
    
    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        """Search for flights."""
        try:
            # Build passengers list
            num_passengers = args.get("passengers", 1)
            passengers = [{"type": "adult"} for _ in range(num_passengers)]
            
            # Search offers
            response = await self.client.search_offers(
                origin=args["origin"].upper(),
                destination=args["destination"].upper(),
                departure_date=args["departure_date"],
                passengers=passengers,
                cabin_class=args.get("cabin_class", "economy"),
                return_date=args.get("return_date"),
            )
            
            # Extract simplified offer summary
            offers = response.get("data", {}).get("offers", [])
            
            simplified_offers = []
            for offer in offers[:10]:  # Limit to top 10
                simplified_offers.append({
                    "offer_id": offer["id"],
                    "total_amount": offer["total_amount"],
                    "total_currency": offer["total_currency"],
                    "airline": offer["owner"]["name"],
                    "slices": [
                        {
                            "origin": s["origin"]["iata_code"],
                            "destination": s["destination"]["iata_code"],
                            "departure_time": s["segments"][0]["departing_at"],
                            "arrival_time": s["segments"][-1]["arriving_at"],
                            "duration": s["duration"],
                        }
                        for s in offer["slices"]
                    ],
                })
            
            return {
                "result": {
                    "offer_count": len(offers),
                    "offers": simplified_offers,
                    "search_params": {
                        "origin": args["origin"].upper(),
                        "destination": args["destination"].upper(),
                        "departure_date": args["departure_date"],
                        "return_date": args.get("return_date"),
                        "passengers": num_passengers,
                        "cabin_class": args.get("cabin_class", "economy"),
                    },
                }
            }
        
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Duffel API error: {e.response.status_code}",
                "details": e.response.text[:500],
            }
        except Exception as e:
            return {
                "error": "Internal error during flight search",
                "details": str(e)[:500],
            }
