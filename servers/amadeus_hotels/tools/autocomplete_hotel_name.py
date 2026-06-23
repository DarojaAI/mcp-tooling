"""Hotel name autocomplete tool."""

from typing import Any

from runtime.base import BaseTool
from servers.amadeus_hotels.client import AmadeusClient, AmadeusError


class AutocompleteHotelNameTool(BaseTool):
    """Type-ahead search for hotels by partial name."""

    def __init__(self, client: AmadeusClient) -> None:
        self._client = client

    @property
    def tool_name(self) -> str:
        return "autocomplete_hotel_name"

    @property
    def description(self) -> str:
        return (
            "Type-ahead hotel search. Returns up to 20 hotels whose names "
            "most closely match the given keyword. Use for disambiguation "
            "before calling list_hotels_by_city or search_hotels."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Partial hotel name (min 2 chars).",
                    "minLength": 2,
                    "maxLength": 50,
                },
            },
            "required": ["keyword"],
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.autocomplete_hotel_name(keyword=args["keyword"])
        except AmadeusError as e:
            return {"error": "Amadeus API error", "details": str(e)}

        hotels = response.get("data", [])
        simplified = [
            {
                "hotel_id": h.get("hotelId"),
                "name": h.get("name"),
                "iata_code": h.get("iataCode"),
                "address": h.get("address", {}),
            }
            for h in hotels
        ]
        return {
            "result": {
                "keyword": args["keyword"],
                "hotel_count": len(simplified),
                "hotels": simplified,
            }
        }
