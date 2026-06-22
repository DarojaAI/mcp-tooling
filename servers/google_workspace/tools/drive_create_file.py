"""Drive create file tool."""

from typing import Any

from runtime.base import BaseTool
from servers.google_workspace.client import GoogleWorkspaceClient, GoogleWorkspaceError


class DriveCreateFileTool(BaseTool):
    """Create a new file the application owns."""

    def __init__(self, client: GoogleWorkspaceClient) -> None:
        self._client = client

    @property
    def tool_name(self) -> str:
        return "drive_create_file"

    @property
    def description(self) -> str:
        return (
            "Create a new file in the application's Drive. Defaults to a "
            "Google Doc (mimeType=application/vnd.google-apps.document). "
            "For text/* mime types, the optional content is uploaded as the "
            "file body. Created files are owned by the application (drive.file)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "File name.",
                    "minLength": 1,
                    "maxLength": 256,
                },
                "mime_type": {
                    "type": "string",
                    "description": "MIME type for the new file.",
                    "default": "application/vnd.google-apps.document",
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Optional file body (UTF-8 text). Ignored for native "
                        "Google Workspace mime types (Docs/Sheets/Slides)."
                    ),
                },
            },
            "required": ["name"],
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.create_file(
                name=args["name"],
                mime_type=args.get("mime_type", "application/vnd.google-apps.document"),
                content=args.get("content"),
            )
        except GoogleWorkspaceError as e:
            return {"error": "Google API error", "details": str(e)}

        return {
            "result": {
                "file_id": response.get("id"),
                "name": response.get("name"),
                "mime_type": response.get("mimeType"),
                "web_view_link": response.get("webViewLink"),
            }
        }
