"""Tests for the scope guard."""

from __future__ import annotations

import pytest

from servers.google_workspace.scope_guard import (
    ALLOWED_SCOPES,
    ScopePolicyError,
    validate_scopes,
)


def test_allowed_scopes_contains_drive_file():
    assert "https://www.googleapis.com/auth/drive.file" in ALLOWED_SCOPES


def test_allowed_scopes_contains_documents():
    assert "https://www.googleapis.com/auth/documents" in ALLOWED_SCOPES


def test_allowed_scopes_does_not_contain_full_drive():
    """Full drive scope (account-wide) must NOT be in the allowlist."""
    assert "https://www.googleapis.com/auth/drive" not in ALLOWED_SCOPES


def test_allowed_scopes_does_not_contain_gmail():
    assert "https://www.googleapis.com/auth/gmail.readonly" not in ALLOWED_SCOPES
    assert "https://www.googleapis.com/auth/gmail.send" not in ALLOWED_SCOPES
    assert "https://www.googleapis.com/auth/gmail.modify" not in ALLOWED_SCOPES


def test_allowed_scopes_does_not_contain_calendar_or_sheets():
    """Calendar/Sheets/etc. are deliberately excluded in v0.1.0."""
    assert "https://www.googleapis.com/auth/calendar" not in ALLOWED_SCOPES
    assert "https://www.googleapis.com/auth/spreadsheets" not in ALLOWED_SCOPES


def test_validate_scopes_empty_raises():
    with pytest.raises(ScopePolicyError, match="No OAuth scopes configured"):
        validate_scopes([])


def test_validate_scopes_full_drive_raises():
    with pytest.raises(ScopePolicyError, match="Disallowed"):
        validate_scopes(["https://www.googleapis.com/auth/drive"])


def test_validate_scopes_gmail_raises():
    with pytest.raises(ScopePolicyError, match="Disallowed"):
        validate_scopes(["https://www.googleapis.com/auth/gmail.readonly"])


def test_validate_scopes_calendar_raises():
    with pytest.raises(ScopePolicyError, match="Disallowed"):
        validate_scopes(["https://www.googleapis.com/auth/calendar"])


def test_validate_scopes_drive_file_passes():
    out = validate_scopes(["https://www.googleapis.com/auth/drive.file"])
    assert out == ["https://www.googleapis.com/auth/drive.file"]


def test_validate_scopes_documents_passes():
    out = validate_scopes(["https://www.googleapis.com/auth/documents"])
    assert out == ["https://www.googleapis.com/auth/documents"]


def test_validate_scopes_both_passes_in_order():
    out = validate_scopes(
        [
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/documents",
        ]
    )
    assert out == [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/documents",
    ]


def test_validate_scopes_mixed_raises_with_disallowed_listed():
    """A mix of allowed + disallowed must fail loudly and name the disallowed ones."""
    mixed = [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/documents",
    ]
    with pytest.raises(ScopePolicyError) as exc:
        validate_scopes(mixed)
    msg = str(exc.value)
    assert "gmail.readonly" in msg
    assert "drive.file" not in msg.split("Disallowed:")[1].split(".")[0]


def test_validate_scopes_deduplicates():
    """Duplicate scopes must collapse to one entry (google-auth expects a list)."""
    out = validate_scopes(
        [
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive.file",
        ]
    )
    assert out == ["https://www.googleapis.com/auth/drive.file"]
