"""Amadeus Hotels MCP tools.

Four tools, all read-only. Search-only by design — Hotel Booking is
deliberately not exposed (this server is for hotel discovery, not
reservation).
"""

from servers.amadeus_hotels.tools.autocomplete_hotel_name import AutocompleteHotelNameTool
from servers.amadeus_hotels.tools.get_hotel_ratings import GetHotelRatingsTool
from servers.amadeus_hotels.tools.list_hotels_by_city import ListHotelsByCityTool
from servers.amadeus_hotels.tools.search_hotels import SearchHotelsTool

__all__ = [
    "AutocompleteHotelNameTool",
    "GetHotelRatingsTool",
    "ListHotelsByCityTool",
    "SearchHotelsTool",
]
