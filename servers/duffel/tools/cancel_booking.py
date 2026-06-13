"""Cancel booking tool."""

from typing import Any
from runtime.base import BaseTool
from servers.duffel.client import DuffelClient
import httpx
import os


class CancelBookingTool(BaseTool):
    """
    Cancel a flight booking.
    
    REQUIRES confirmation: Set MCPTOOLING_CONFIRM_DESTRUCTIVE=true to enable.
    This is a safety gate to prevent accidental cancellations.
    """
    
    def __init__(self, client: DuffelClient):
        self.client = client
    
    @property
    def tool_name(self) -> str:
        return "cancel_booking"
    
    @property
    def description(self) -> str:
        return "Cancel a flight booking (requires MCPTOOLING_CONFIRM_DESTRUCTIVE=true)"
    
    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Duffel order ID to cancel",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for cancellation (optional)",
                },
            },
            "required": ["order_id"],
        }
    
    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        """Cancel a booking."""
        # Check confirmation flag
        confirm = os.getenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", "false").lower() == "true"
        
        if not confirm:
            return {
                "error": "Cancellation not confirmed",
                "details": "Set MCPTOOLING_CONFIRM_DESTRUCTIVE=true to enable booking cancellation. This is a safety gate to prevent accidental cancellations.",
            }
        
        try:
            response = await self.client.cancel_order(args["order_id"])
            cancellation = response.get("data", {})
            
            return {
                "result": {
                    "cancellation_id": cancellation["id"],
                    "order_id": cancellation["order_id"],
                    "status": "cancelled",
                    "refund_amount": cancellation.get("refund_amount"),
                    "refund_currency": cancellation.get("refund_currency"),
                    "confirmed_at": cancellation.get("confirmed_at"),
                }
            }
        
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Duffel API error: {e.response.status_code}",
                "details": e.response.text[:500],
            }
        except Exception as e:
            return {
                "error": "Internal error during cancellation",
                "details": str(e)[:500],
            }
