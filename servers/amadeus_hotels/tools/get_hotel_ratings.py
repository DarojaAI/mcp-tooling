"""Hotel ratings tool — sentiment-based ratings."""

from typing import Any

from runtime.base import BaseTool
from servers.amadeus_hotels.client import AmadeusClient, AmadeusError


class GetHotelRatingsTool(BaseTool):
    """Return sentiment-based ratings for a list of hotel IDs."""

    def __init__(self, client: AmadeusClient) -> None:
        self._client = client

    @property
    def tool_name(self) -> str:
        return "get_hotel_ratings"

    @property
    def description(self) -> str:
        return (
            "Return Amadeus sentiment-based ratings for up to 100 hotel IDs "
            "(overall + per-category: location, comfort, service, staff, "
            "internet, food, facilities, pool, sleep quality). Useful for "
            "sorting search results by quality after the basic search call."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hotel_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of Amadeus hotel IDs (max 100 per call).",
                    "minItems": 1,
                    "maxItems": 100,
                },
            },
            "required": ["hotel_ids"],
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.get_hotel_ratings(hotel_ids=args["hotel_ids"])
        except AmadeusError as e:
            return {"error": "Amadeus API error", "details": str(e)}

        # The Hotel Ratings API returns data keyed by hotelId, not in a
        # `data` array. Be defensive about the shape.
        ratings = response.get("data", []) if isinstance(response.get("data"), list) else []
        # If the API returns a dict-keyed response, normalize to a list.
        if not ratings and isinstance(response.get("data"), dict):
            ratings = [{"hotel_id": hid, **vals} for hid, vals in response["data"].items()]
        return {
            "result": {
                "rating_count": len(ratings),
                "ratings": ratings,
            }
        }
