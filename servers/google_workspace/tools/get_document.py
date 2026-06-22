"""Get document tool (Google Docs read)."""

from typing import Any

from runtime.base import BaseTool
from servers.google_workspace.client import GoogleWorkspaceClient, GoogleWorkspaceError


class GetDocumentTool(BaseTool):
    """Fetch a Google Doc by ID and return its content structure."""

    def __init__(self, client: GoogleWorkspaceClient) -> None:
        self._client = client

    @property
    def tool_name(self) -> str:
        return "get_document"

    @property
    def description(self) -> str:
        return (
            "Fetch a Google Doc by its document ID. Returns the doc's title, "
            "body content structure, and revision ID. Requires the "
            "'documents' OAuth scope."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "Google Docs document ID (from the doc URL or list_files).",
                    "minLength": 1,
                },
            },
            "required": ["document_id"],
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        document_id = args["document_id"]
        try:
            response = await self._client.get_document(document_id=document_id)
        except GoogleWorkspaceError as e:
            return {"error": "Google API error", "details": str(e)}

        # Google Docs API returns the document at the top level (NOT wrapped
        # in {"body": ...}). Fields: documentId, title, body, revisionId, ...
        title = response.get("title", "")
        body = response.get("body", {})
        revision_id = response.get("revisionId", "")

        # Count text content without dumping the entire body (could be huge).
        content = body.get("content", [])
        paragraph_count = sum(1 for elem in content if elem.get("paragraph") is not None)
        table_count = sum(1 for elem in content if elem.get("table") is not None)

        return {
            "result": {
                "document_id": document_id,
                "title": title,
                "revision_id": revision_id,
                "paragraph_count": paragraph_count,
                "table_count": table_count,
                "body": body,
            }
        }
