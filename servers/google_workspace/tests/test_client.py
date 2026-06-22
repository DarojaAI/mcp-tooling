"""Tests for the GoogleWorkspaceClient.

Strategy: monkeypatch googleapiclient.discovery.build to return a fake
service whose resource methods return canned responses. This avoids
needing to spin up httplib2 mocks and keeps tests fast and hermetic.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from servers.google_workspace.client import (
    GoogleWorkspaceClient,
    GoogleWorkspaceError,
)
from servers.google_workspace.scope_guard import ScopePolicyError


def _make_client() -> GoogleWorkspaceClient:
    return GoogleWorkspaceClient(
        client_id="test.apps.googleusercontent.com",
        client_secret="test-secret",
        refresh_token="1//fake-refresh-token",
    )


def test_client_rejects_empty_refresh_token():
    with pytest.raises(GoogleWorkspaceError, match="GOOGLE_WORKSPACE_REFRESH_TOKEN is empty"):
        GoogleWorkspaceClient(client_id="x", client_secret="y", refresh_token="")


def test_client_rejects_widened_scopes():
    """If a caller tries to widen scopes at construction, the client refuses."""
    with pytest.raises(ScopePolicyError):
        GoogleWorkspaceClient(
            client_id="x",
            client_secret="y",
            refresh_token="1//fake",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )


def test_client_default_scopes_are_narrow():
    """No scopes passed → narrow allowlist is used."""
    c = _make_client()
    assert c.scopes == sorted(["drive.file", "documents"]) or set(c.scopes) == {
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/documents",
    }


def test_allowed_scope_set_exposed():
    assert "https://www.googleapis.com/auth/drive.file" in GoogleWorkspaceClient.allowed_scope_set()
    assert "https://www.googleapis.com/auth/documents" in GoogleWorkspaceClient.allowed_scope_set()
    assert "https://www.googleapis.com/auth/gmail.readonly" not in GoogleWorkspaceClient.allowed_scope_set()


def test_check_scopes_helper():
    """Static helper delegates to validate_scopes."""
    out = GoogleWorkspaceClient.check_scopes(["https://www.googleapis.com/auth/drive.file"])
    assert out == ["https://www.googleapis.com/auth/drive.file"]


# ---------------------------------------------------------------------------
# Mock the google API surface. We construct a fake service object that mimics
# the chained-method pattern: service.docs().get(documentId=...).execute().
# ---------------------------------------------------------------------------


class _FakeExec:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeDocsResource:
    def __init__(self, documents_payload):
        self._documents = documents_payload

    def get(self, documentId=None):  # noqa: N803 — Google API param name
        return _FakeExec(self._documents.get(documentId, {}))

    def create(self, body=None):
        return _FakeExec(self._documents.get("_created", {"documentId": "new_id", "title": body["title"]}))

    def batchUpdate(self, documentId=None, body=None):  # noqa: N803
        return _FakeExec({"replies": [], "documentId": documentId})


class _FakeFilesResource:
    def __init__(self, files_payload):
        self._files = files_payload

    def list(self, **kwargs):
        return _FakeExec(self._files["list"])

    def create(self, body=None, media_body=None, fields=None):
        return _FakeExec(self._files["create"])

    def update(self, fileId=None, body=None, fields=None):
        return _FakeExec(self._files["update"])


class _FakeDocsService:
    """Mimic service.documents() which returns the documents resource."""

    def __init__(self, documents_payload):
        self._documents = _FakeDocsResource(documents_payload)

    def documents(self):
        return self._documents


class _FakeDriveService:
    """Mimic service.files() which returns the files resource."""

    def __init__(self, files_payload):
        self._files = _FakeFilesResource(files_payload)

    def files(self):
        return self._files


def _fake_build_docs_factory(documents_payload):
    def factory(api_name, api_version, credentials=None, cache_discovery=None):
        if api_name == "docs":
            return _FakeDocsService(documents_payload)
        raise AssertionError(f"Unexpected build() call: {api_name} {api_version}")

    return factory


def _fake_build_drive_factory(files_payload):
    def factory(api_name, api_version, credentials=None, cache_discovery=None):
        if api_name == "drive":
            return _FakeDriveService(files_payload)
        raise AssertionError(f"Unexpected build() call: {api_name} {api_version}")

    return factory


# ---------------------------------------------------------------------------
# Async tool tests — one per client method.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_document():
    documents = {
        "doc_abc": {
            "documentId": "doc_abc",
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
    }
    c = _make_client()
    with patch(
        "servers.google_workspace.client.build",
        side_effect=_fake_build_docs_factory(documents),
    ):
        result = await c.get_document("doc_abc")

    assert result["title"] == "Test Doc"
    assert result["revisionId"] == "rev_42"
    assert len(result["body"]["content"]) == 3


@pytest.mark.asyncio
async def test_create_document():
    documents = {"_created": {"documentId": "new_doc_xyz", "title": "New Doc"}}
    c = _make_client()
    with patch(
        "servers.google_workspace.client.build",
        side_effect=_fake_build_docs_factory(documents),
    ):
        result = await c.create_document(title="New Doc")

    assert result["documentId"] == "new_doc_xyz"
    assert result["title"] == "New Doc"


@pytest.mark.asyncio
async def test_batch_update_document():
    documents = {"any_id": {"documentId": "any_id", "title": "x", "body": {}, "revisionId": "rev_1"}}
    c = _make_client()
    with patch(
        "servers.google_workspace.client.build",
        side_effect=_fake_build_docs_factory(documents),
    ):
        result = await c.batch_update_document(
            "any_id",
            [{"insertText": {"location": {"index": 1}, "text": "Hello"}}],
        )
    assert result["documentId"] == "any_id"
    assert result["replies"] == []


@pytest.mark.asyncio
async def test_batch_update_document_empty_raises():
    c = _make_client()
    with pytest.raises(GoogleWorkspaceError, match="at least one request"):
        await c.batch_update_document("any_id", [])


@pytest.mark.asyncio
async def test_list_files():
    files = {
        "list": {
            "files": [
                {
                    "id": "f1",
                    "name": "Doc One",
                    "mimeType": "application/vnd.google-apps.document",
                    "modifiedTime": "2026-06-22T07:00:00Z",
                    "size": "1234",
                    "webViewLink": "https://docs.google.com/document/d/f1/edit",
                },
                {
                    "id": "f2",
                    "name": "Doc Two",
                    "mimeType": "application/vnd.google-apps.document",
                    "modifiedTime": "2026-06-22T07:01:00Z",
                    "webViewLink": "https://docs.google.com/document/d/f2/edit",
                },
            ],
            "nextPageToken": "tok_xyz",
        }
    }
    c = _make_client()
    with patch(
        "servers.google_workspace.client.build",
        side_effect=_fake_build_drive_factory(files),
    ):
        result = await c.list_files(page_size=50, query="mimeType='application/vnd.google-apps.document'")

    assert len(result["files"]) == 2
    assert result["nextPageToken"] == "tok_xyz"


@pytest.mark.asyncio
async def test_list_files_caps_page_size():
    """page_size > 100 must be silently capped to 100 to bound response size."""
    files = {"list": {"files": []}}
    c = _make_client()

    captured = {}

    class _CapturingList:
        def __init__(self):
            pass

        def list(self, **kwargs):
            captured.update(kwargs)
            return _FakeExec(files["list"])

    class _CapturingService:
        def __init__(self):
            self._files = _CapturingList()

        def files(self):
            return self._files

    def factory(api_name, api_version, credentials=None, cache_discovery=None):
        return _CapturingService()

    with patch("servers.google_workspace.client.build", side_effect=factory):
        await c.list_files(page_size=99999)

    assert captured["pageSize"] == 100


@pytest.mark.asyncio
async def test_create_file_native_mime():
    files = {
        "create": {
            "id": "new_file_id",
            "name": "Native Doc",
            "mimeType": "application/vnd.google-apps.document",
            "webViewLink": "https://docs.google.com/document/d/new_file_id/edit",
        }
    }
    c = _make_client()
    with patch(
        "servers.google_workspace.client.build",
        side_effect=_fake_build_drive_factory(files),
    ):
        result = await c.create_file(name="Native Doc")

    assert result["id"] == "new_file_id"
    assert result["name"] == "Native Doc"


@pytest.mark.asyncio
async def test_update_file():
    files = {
        "update": {
            "id": "f1",
            "name": "Renamed Doc",
            "mimeType": "application/vnd.google-apps.document",
            "modifiedTime": "2026-06-22T08:00:00Z",
            "webViewLink": "https://docs.google.com/document/d/f1/edit",
        }
    }
    c = _make_client()
    with patch(
        "servers.google_workspace.client.build",
        side_effect=_fake_build_drive_factory(files),
    ):
        result = await c.update_file("f1", name="Renamed Doc")

    assert result["name"] == "Renamed Doc"


@pytest.mark.asyncio
async def test_update_file_empty_raises():
    c = _make_client()
    with pytest.raises(GoogleWorkspaceError, match="at least one field"):
        await c.update_file("f1")
