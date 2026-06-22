"""
Async wrapper around the Google Workspace REST APIs.

This client is intentionally narrow: only the operations needed for
drive.file + documents scope are exposed. Adding new operations requires
also adding the corresponding scope to ALLOWED_SCOPES in scope_guard.py.

The Google API client library (googleapiclient) is synchronous and uses
httplib2, which blocks. We push those calls to a thread pool via
asyncio.to_thread so the FastMCP tool surface stays async and the
streamable-http server can handle concurrent requests.

Credential model:
- Refresh token is loaded once at startup from GOOGLE_WORKSPACE_REFRESH_TOKEN.
- Access tokens are auto-refreshed by google-auth as needed.
- Client ID / secret / project metadata come from GOOGLE_WORKSPACE_CLIENT_ID /
  GOOGLE_WORKSPACE_CLIENT_SECRET / GOOGLE_WORKSPACE_PROJECT_ID (optional).
"""

from __future__ import annotations

import asyncio
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from servers.google_workspace.scope_guard import ALLOWED_SCOPES, ScopePolicyError, validate_scopes


class GoogleWorkspaceError(RuntimeError):
    """Raised on any non-recoverable Google Workspace API error."""


class GoogleWorkspaceClient:
    """
    Async client for the narrow Google Workspace surface this server exposes.

    Construction validates scopes up-front so a misconfigured server
    cannot register any tools at all.

    Usage:
        client = GoogleWorkspaceClient(
            client_id="...apps.googleusercontent.com",
            client_secret="...",
            refresh_token="1//...",
        )
        docs = await client.create_document(title="Hello")
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        scopes: list[str] | tuple[str, ...] | None = None,
        project_id: str | None = None,
    ) -> None:
        if not refresh_token:
            raise GoogleWorkspaceError(
                "GOOGLE_WORKSPACE_REFRESH_TOKEN is empty. The server cannot "
                "authenticate to Google APIs without a refresh token. "
                "Run the OAuth bootstrap (see docs/integrations/google-workspace-mcp.md) "
                "and write the token to /etc/mcp-tooling/secrets.env."
            )

        # Default to the full narrow allowlist if the operator didn't specify.
        # validate_scopes will refuse to start if anyone tried to widen this.
        effective_scopes = list(scopes) if scopes else sorted(ALLOWED_SCOPES)
        self._scopes = validate_scopes(effective_scopes)

        self._credentials = Credentials(
            token=None,  # Will be auto-refreshed from refresh_token
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=self._scopes,
        )
        self._project_id = project_id

    @property
    def scopes(self) -> list[str]:
        return list(self._scopes)

    # -- internal helpers -------------------------------------------------

    def _build_docs(self) -> Any:
        """Build the Google Docs API client (sync)."""
        return build("docs", "v1", credentials=self._credentials, cache_discovery=False)

    def _build_drive(self) -> Any:
        """Build the Google Drive API client (sync)."""
        return build("drive", "v3", credentials=self._credentials, cache_discovery=False)

    async def _run(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a sync Google API call in a thread.

        Google API client methods return a Request object that needs
        .execute() to be called to actually fetch the response. We wrap
        that here so callers get the parsed payload dict back.
        """

        def _call() -> Any:
            request = func(*args, **kwargs)
            return request.execute()

        try:
            return await asyncio.to_thread(_call)
        except HttpError as e:
            raise GoogleWorkspaceError(
                f"Google API error: status={e.resp.status} reason={e.resp.reason} url={e.uri}"
            ) from e

    # -- documents (Google Docs) -----------------------------------------

    async def get_document(self, document_id: str) -> dict[str, Any]:
        """Fetch a Google Doc by ID. Returns the full Docs resource."""
        service = self._build_docs()
        return await self._run(service.documents().get, documentId=document_id)

    async def create_document(self, title: str) -> dict[str, Any]:
        """Create a new empty Google Doc. Returns the new doc resource."""
        service = self._build_docs()
        body = {"title": title}
        return await self._run(service.documents().create, body=body)

    async def batch_update_document(
        self,
        document_id: str,
        requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply a batchUpdate to a Google Doc."""
        if not requests:
            raise GoogleWorkspaceError("batch_update_document requires at least one request")
        service = self._build_docs()
        body = {"requests": requests}
        return await self._run(
            service.documents().batchUpdate,
            documentId=document_id,
            body=body,
        )

    # -- drive.file ------------------------------------------------------

    async def list_files(
        self,
        page_size: int = 20,
        page_token: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        """
        List files the app has access to (drive.file scope, not full drive).

        page_size is capped at 100 to bound response size.
        query is passed through to Drive's q parameter (e.g.,
        "name contains 'foo' and mimeType='application/vnd.google-apps.document'").
        """
        capped_page_size = min(max(1, page_size), 100)
        service = self._build_drive()
        kwargs: dict[str, Any] = {
            "pageSize": capped_page_size,
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size,webViewLink)",
        }
        if page_token:
            kwargs["pageToken"] = page_token
        if query:
            kwargs["q"] = query
        return await self._run(service.files().list, **kwargs)

    async def create_file(
        self,
        name: str,
        mime_type: str = "application/vnd.google-apps.document",
        content: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new file owned by this app.

        For Google Docs/Sheets/Slides, content is ignored (the native
        app creates an empty doc). For text/plain or text/markdown, content
        is uploaded as the file body.
        """
        service = self._build_drive()
        metadata: dict[str, Any] = {"name": name, "mimeType": mime_type}
        if content is not None and mime_type not in (
            "application/vnd.google-apps.document",
            "application/vnd.google-apps.spreadsheet",
            "application/vnd.google-apps.presentation",
        ):
            # Media body upload
            from io import BytesIO

            from googleapiclient.http import MediaIoBaseUpload

            media = MediaIoBaseUpload(BytesIO(content.encode("utf-8")), mimetype=mime_type)
            return await self._run(
                service.files().create,
                body=metadata,
                media_body=media,
                fields="id,name,mimeType,webViewLink",
            )
        return await self._run(
            service.files().create,
            body=metadata,
            fields="id,name,mimeType,webViewLink",
        )

    async def update_file(self, file_id: str, name: str | None = None) -> dict[str, Any]:
        """
        Update file metadata (rename). drive.file scope permits updates
        to files the app has created/opened — we don't try to update
        arbitrary user files.
        """
        service = self._build_drive()
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if not body:
            raise GoogleWorkspaceError("update_file requires at least one field to update")
        return await self._run(
            service.files().update,
            fileId=file_id,
            body=body,
            fields="id,name,mimeType,modifiedTime,webViewLink",
        )

    # -- scope introspection (for tests + diagnostics) ------------------

    @staticmethod
    def allowed_scope_set() -> frozenset[str]:
        """Expose the narrow allowlist for tests and the health endpoint."""
        return ALLOWED_SCOPES

    @staticmethod
    def check_scopes(scopes: list[str]) -> list[str]:
        """Public wrapper around scope_guard.validate_scopes for reuse."""
        return validate_scopes(scopes)


# Re-export ScopePolicyError so callers can catch it from one place.
__all__ = [
    "GoogleWorkspaceClient",
    "GoogleWorkspaceError",
    "ScopePolicyError",
    "ALLOWED_SCOPES",
]
