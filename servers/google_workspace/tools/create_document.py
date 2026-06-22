"""Create document tool."""

from typing import Any

from runtime.base import BaseTool
from servers.google_workspace.client import GoogleWorkspaceClient, GoogleWorkspaceError


class CreateDocumentTool(BaseTool):
    """Create a new Google Doc."""

    def __init__(self, client: GoogleWorkspaceClient) -> None:
        self._client = client

    @property
    def tool_name(self) -> str:
        return "create_document"

    @property
    def description(self) -> str:
        return (
            "Create a new empty Google Doc with the given title. Returns the "
            "new document's ID and webViewLink. Requires the 'documents' OAuth "
            "scope. The created doc is owned by the application (drive.file)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title for the new document.",
                    "minLength": 1,
                    "maxLength": 256,
                },
            },
            "required": ["title"],
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        title = args["title"]
        try:
            response = await self._client.create_document(title=title)
        except GoogleWorkspaceError as e:
            return {"error": "Google API error", "details": str(e)}

        # Google Docs API returns the created document at the top level.
        document_id = response.get("documentId", "")
        return {
            "result": {
                "document_id": document_id,
                "title": response.get("title", title),
                "web_view_link": (f"https://docs.google.com/document/d/{document_id}/edit" if document_id else None),
            }
        }
