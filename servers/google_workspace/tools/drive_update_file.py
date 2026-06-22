"""Drive update file tool (rename only, under drive.file scope)."""

from typing import Any

from runtime.base import BaseTool
from servers.google_workspace.client import GoogleWorkspaceClient, GoogleWorkspaceError


class DriveUpdateFileTool(BaseTool):
    """Update metadata of a file the application owns."""

    def __init__(self, client: GoogleWorkspaceClient) -> None:
        self._client = client

    @property
    def tool_name(self) -> str:
        return "drive_update_file"

    @property
    def description(self) -> str:
        return (
            "Update metadata (currently: name) of a file the application owns. "
            "drive.file scope only permits updates to files the app created or "
            "opened — calls against other files will fail with 404."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "ID of the file to update.",
                    "minLength": 1,
                },
                "name": {
                    "type": "string",
                    "description": "New name for the file.",
                    "minLength": 1,
                    "maxLength": 256,
                },
            },
            "required": ["file_id", "name"],
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.update_file(
                file_id=args["file_id"],
                name=args["name"],
            )
        except GoogleWorkspaceError as e:
            return {"error": "Google API error", "details": str(e)}

        return {
            "result": {
                "file_id": response.get("id"),
                "name": response.get("name"),
                "mime_type": response.get("mimeType"),
                "modified_time": response.get("modifiedTime"),
                "web_view_link": response.get("webViewLink"),
            }
        }
