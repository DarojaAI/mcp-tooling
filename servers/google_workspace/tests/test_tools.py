"""Tests for the Google Workspace tools.

Strategy: build a GoogleWorkspaceClient with the mocked `build()` patch,
then call each tool's .call() and assert on the structured result. This
exercises the full tool surface against canned Google API responses
without ever talking to a real Google backend.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from servers.google_workspace.client import GoogleWorkspaceClient
from servers.google_workspace.tools import (
    CreateDocumentTool,
    DriveCreateFileTool,
    DriveListFilesTool,
    DriveUpdateFileTool,
    GetDocumentTool,
)


def _client() -> GoogleWorkspaceClient:
    return GoogleWorkspaceClient(
        client_id="test.apps.googleusercontent.com",
        client_secret="test-secret",
        refresh_token="1//fake",
    )


class _FakeExec:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _DocsResource:
    def get(self, documentId=None):  # noqa: N803
        # documents.get returns the doc at the top level (not wrapped in "body").
        return _FakeExec(
            {
                "documentId": documentId,
                "title": "Test Doc",
                "body": {
                    "content": [
                        {"paragraph": {"elements": [{"textRun": {"content": "Hi"}}]}},
                        {"paragraph": {"elements": [{"textRun": {"content": "There"}}]}},
                        {"table": {}},
                    ]
                },
                "revisionId": "rev_42",
            }
        )

    def create(self, body=None):
        # documents.create returns the doc at the top level.
        return _FakeExec({"documentId": "new_id", "title": body["title"]})

    def batchUpdate(self, documentId=None, body=None):  # noqa: N803
        return _FakeExec({"replies": [], "documentId": documentId})


class _FilesResource:
    def list(self, **kwargs):
        return _FakeExec(
            {
                "files": [
                    {
                        "id": "f1",
                        "name": "Doc One",
                        "mimeType": "application/vnd.google-apps.document",
                        "modifiedTime": "2026-06-22T07:00:00Z",
                        "size": "1234",
                        "webViewLink": "https://docs.google.com/document/d/f1/edit",
                    },
                ],
                "nextPageToken": "tok_xyz",
            }
        )

    def create(self, body=None, media_body=None, fields=None):
        return _FakeExec(
            {
                "id": "new_file_id",
                "name": body["name"],
                "mimeType": body.get("mimeType", "application/vnd.google-apps.document"),
                "webViewLink": "https://docs.google.com/document/d/new_file_id/edit",
            }
        )

    def update(self, fileId=None, body=None, fields=None):  # noqa: N803
        return _FakeExec(
            {
                "id": fileId,
                "name": body.get("name"),
                "mimeType": "application/vnd.google-apps.document",
                "modifiedTime": "2026-06-22T08:00:00Z",
                "webViewLink": f"https://docs.google.com/document/d/{fileId}/edit",
            }
        )


class _DocsService:
    def __init__(self):
        self._documents = _DocsResource()

    def documents(self):
        return self._documents


class _DriveService:
    def __init__(self):
        self._files = _FilesResource()

    def files(self):
        return self._files


def _fake_build_factory(api_name, api_version, credentials=None, cache_discovery=None):
    if api_name == "docs":
        return _DocsService()
    if api_name == "drive":
        return _DriveService()
    raise AssertionError(f"Unexpected build() call: {api_name} {api_version}")


@pytest.mark.asyncio
async def test_get_document_tool():
    tool = GetDocumentTool(_client())
    with patch("servers.google_workspace.client.build", side_effect=_fake_build_factory):
        result = await tool.call({"document_id": "doc_abc"})

    assert "result" in result
    assert result["result"]["document_id"] == "doc_abc"
    assert result["result"]["title"] == "Test Doc"
    assert result["result"]["paragraph_count"] == 2
    assert result["result"]["table_count"] == 1
    assert result["result"]["revision_id"] == "rev_42"


@pytest.mark.asyncio
async def test_create_document_tool():
    tool = CreateDocumentTool(_client())
    with patch("servers.google_workspace.client.build", side_effect=_fake_build_factory):
        result = await tool.call({"title": "New Doc"})

    assert "result" in result
    assert result["result"]["document_id"] == "new_id"
    assert result["result"]["title"] == "New Doc"
    assert result["result"]["web_view_link"].endswith("/new_id/edit")


@pytest.mark.asyncio
async def test_drive_list_files_tool():
    tool = DriveListFilesTool(_client())
    with patch("servers.google_workspace.client.build", side_effect=_fake_build_factory):
        result = await tool.call({"page_size": 20})

    assert "result" in result
    assert result["result"]["file_count"] == 1
    assert result["result"]["files"][0]["id"] == "f1"
    assert result["result"]["next_page_token"] == "tok_xyz"


@pytest.mark.asyncio
async def test_drive_list_files_tool_with_query():
    """Query string should be passed through to Drive's q parameter."""
    tool = DriveListFilesTool(_client())
    captured = {}

    class _CapturingList:
        def list(self, **kwargs):
            captured.update(kwargs)
            return _FakeExec({"files": []})

    class _CapturingService:
        def files(self):
            return _CapturingList()

    def factory(api_name, api_version, credentials=None, cache_discovery=None):
        return _CapturingService()

    with patch("servers.google_workspace.client.build", side_effect=factory):
        result = await tool.call({"page_size": 5, "query": "mimeType='application/vnd.google-apps.document'"})

    assert captured["pageSize"] == 5
    assert captured["q"] == "mimeType='application/vnd.google-apps.document'"
    assert result["result"]["file_count"] == 0


@pytest.mark.asyncio
async def test_drive_create_file_tool():
    tool = DriveCreateFileTool(_client())
    with patch("servers.google_workspace.client.build", side_effect=_fake_build_factory):
        result = await tool.call({"name": "Native Doc"})

    assert "result" in result
    assert result["result"]["file_id"] == "new_file_id"
    assert result["result"]["name"] == "Native Doc"


@pytest.mark.asyncio
async def test_drive_update_file_tool():
    tool = DriveUpdateFileTool(_client())
    with patch("servers.google_workspace.client.build", side_effect=_fake_build_factory):
        result = await tool.call({"file_id": "f1", "name": "Renamed"})

    assert "result" in result
    assert result["result"]["file_id"] == "f1"
    assert result["result"]["name"] == "Renamed"
