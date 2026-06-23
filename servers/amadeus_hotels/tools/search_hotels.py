"""Search hotels tool — Hotel Search API v3."""

from typing import Any

from runtime.base import BaseTool
from servers.amadeus_hotels.client import AmadeusClient, AmadeusError


class SearchHotelsTool(BaseTool):
    """Search for hotels in a location with availability + pricing."""

    def __init__(self, client: AmadeusClient) -> None:
        self._client = client

    @property
    def tool_name(self) -> str:
        return "search_hotels"

    @property
    def description(self) -> str:
        return (
            "Search for hotels in a city (by IATA city code) or near "
            "(latitude, longitude) coordinates. Returns offers with pricing "
            "for the requested dates. Optional filters: radius, amenities, "
            "price range, currency, adults/rooms. This is search/pricing "
            "only — does not create a booking."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "city_code": {
                    "type": "string",
                    "description": "IATA city code (mutually exclusive with lat/lon).",
                    "minLength": 3,
                    "maxLength": 3,
                },
                "latitude": {
                    "type": "number",
                    "description": "Latitude (mutually exclusive with city_code).",
                    "minimum": -90,
                    "maximum": 90,
                },
                "longitude": {
                    "type": "number",
                    "description": "Longitude (mutually exclusive with city_code).",
                    "minimum": -180,
                    "maximum": 180,
                },
                "radius": {
                    "type": "integer",
                    "description": "Search radius (with radius_unit). Used with lat/lon.",
                    "minimum": 1,
                    "maximum": 100,
                },
                "radius_unit": {
                    "type": "string",
                    "enum": ["KM", "MI"],
                    "description": "Unit for the radius parameter.",
                },
                "check_in_date": {
                    "type": "string",
                    "description": "Check-in date (YYYY-MM-DD).",
                    "pattern": r"^\d{4}-\d{2}-\d{2}$",
                },
                "check_out_date": {
                    "type": "string",
                    "description": "Check-out date (YYYY-MM-DD).",
                    "pattern": r"^\d{4}-\d{2}-\d{2}$",
                },
                "adults": {
                    "type": "integer",
                    "description": "Number of adults per room.",
                    "minimum": 1,
                    "maximum": 9,
                },
                "room_quantity": {
                    "type": "integer",
                    "description": "Number of rooms.",
                    "minimum": 1,
                    "maximum": 9,
                },
                "price_range": {
                    "type": "string",
                    "description": "Price range filter (e.g. '100-200' in the requested currency).",
                },
                "currency": {
                    "type": "string",
                    "description": "ISO 4217 currency code (e.g. 'EUR', 'USD').",
                    "minLength": 3,
                    "maxLength": 3,
                },
                "amenities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of amenity codes.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of hotels to return (1-100, default 20).",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                },
            },
            "required": [],
            "anyOf": [
                {"required": ["city_code"]},
                {"required": ["latitude", "longitude"]},
            ],
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.search_hotels(
                city_code=args.get("city_code"),
                latitude=args.get("latitude"),
                longitude=args.get("longitude"),
                radius=args.get("radius"),
                radius_unit=args.get("radius_unit"),
                check_in_date=args.get("check_in_date"),
                check_out_date=args.get("check_out_date"),
                adults=args.get("adults"),
                room_quantity=args.get("room_quantity"),
                price_range=args.get("price_range"),
                currency=args.get("currency"),
                amenities=args.get("amenities"),
                max_results=args.get("max_results"),
            )
        except AmadeusError as e:
            return {"error": "Amadeus API error", "details": str(e)}

        offers = response.get("data", [])
        # Slim each offer down — the full structure can be huge.
        simplified = []
        for offer in offers:
            hotel = offer.get("hotel", {})
            hotel_offers = offer.get("offers", [])
            cheapest = hotel_offers[0] if hotel_offers else {}
            price = cheapest.get("price", {})
            simplified.append(
                {
                    "hotel_id": hotel.get("hotelId"),
                    "name": hotel.get("name"),
                    "rating": hotel.get("rating"),
                    "city_code": hotel.get("cityCode"),
                    "latitude": hotel.get("latitude"),
                    "longitude": hotel.get("longitude"),
                    "offer_count": len(hotel_offers),
                    "price_total": price.get("total"),
                    "price_currency": price.get("currency"),
                }
            )
        return {
            "result": {
                "hotel_count": len(simplified),
                "hotels": simplified,
            }
        }
