"""List hotels by city code tool."""

from typing import Any

from runtime.base import BaseTool
from servers.amadeus_hotels.client import AmadeusClient, AmadeusError


class ListHotelsByCityTool(BaseTool):
    """Return the list of hotels bookable in Amadeus for a given city code."""

    def __init__(self, client: AmadeusClient) -> None:
        self._client = client

    @property
    def tool_name(self) -> str:
        return "list_hotels_by_city"

    @property
    def description(self) -> str:
        return (
            "List hotels in a city by IATA city code (e.g. 'PAR' for Paris, 'NYC' "
            "for New York). Returns hotel name, address, geoCode, and Amadeus "
            "hotel ID for each. Optional radius + amenities filter. This is "
            "discovery only — does not include pricing or availability."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "city_code": {
                    "type": "string",
                    "description": "IATA city code (3-letter).",
                    "minLength": 3,
                    "maxLength": 3,
                },
                "radius": {
                    "type": "integer",
                    "description": "Search radius (with radius_unit).",
                    "minimum": 1,
                    "maximum": 100,
                },
                "radius_unit": {
                    "type": "string",
                    "enum": ["KM", "MI"],
                    "description": "Unit for the radius parameter.",
                },
                "amenities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of amenity codes (e.g. ['SWIMING_POOL', 'FITNESS_CENTER']).",
                },
            },
            "required": ["city_code"],
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.list_hotels_by_city(
                city_code=args["city_code"],
                radius=args.get("radius"),
                radius_unit=args.get("radius_unit"),
                amenities=args.get("amenities"),
            )
        except AmadeusError as e:
            return {"error": "Amadeus API error", "details": str(e)}

        hotels = response.get("data", [])
        simplified = [
            {
                "hotel_id": h.get("hotelId"),
                "name": h.get("name"),
                "iata_code": h.get("iataCode"),
                "address": h.get("address", {}),
                "geo_code": h.get("geoCode", {}),
                "chain_code": h.get("chainCode"),
            }
            for h in hotels
        ]
        return {
            "result": {
                "city_code": args["city_code"],
                "hotel_count": len(simplified),
                "hotels": simplified,
            }
        }
