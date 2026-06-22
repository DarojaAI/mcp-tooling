"""Drive list files tool."""

from typing import Any

from runtime.base import BaseTool
from servers.google_workspace.client import GoogleWorkspaceClient, GoogleWorkspaceError


class DriveListFilesTool(BaseTool):
    """List files the application has access to (drive.file scope)."""

    def __init__(self, client: GoogleWorkspaceClient) -> None:
        self._client = client

    @property
    def tool_name(self) -> str:
        return "drive_list_files"

    @property
    def description(self) -> str:
        return (
            "List files the application has access to under drive.file scope. "
            "Supports pagination via page_token and filtering via a Drive "
            "query string (e.g., \"mimeType='application/vnd.google-apps.document'\"). "
            "page_size is capped at 100."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "page_size": {
                    "type": "integer",
                    "description": "Number of files to return (1-100, default 20).",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                },
                "page_token": {
                    "type": "string",
                    "description": "Continuation token from a previous call.",
                },
                "query": {
                    "type": "string",
                    "description": "Drive query string (q parameter).",
                },
            },
            "required": [],
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.list_files(
                page_size=args.get("page_size", 20),
                page_token=args.get("page_token"),
                query=args.get("query"),
            )
        except GoogleWorkspaceError as e:
            return {"error": "Google API error", "details": str(e)}

        files = response.get("files", [])
        simplified = [
            {
                "id": f["id"],
                "name": f.get("name"),
                "mime_type": f.get("mimeType"),
                "modified_time": f.get("modifiedTime"),
                "size": f.get("size"),
                "web_view_link": f.get("webViewLink"),
            }
            for f in files
        ]
        return {
            "result": {
                "file_count": len(simplified),
                "files": simplified,
                "next_page_token": response.get("nextPageToken"),
            }
        }
