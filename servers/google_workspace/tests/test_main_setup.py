"""Tests for servers.google_workspace.__main__.setup().

These exercise the startup-time scope guard: a misconfigured scope set
must prevent any tool from being registered. This is the single most
important behavioral guarantee of this server.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Make sure setup() can import runtime + tools.
from servers.google_workspace import __main__ as gw_main

SECRETS_CONTENT_NARROW = """\
GOOGLE_WORKSPACE_CLIENT_ID=test.apps.googleusercontent.com
GOOGLE_WORKSPACE_CLIENT_SECRET=test-secret
GOOGLE_WORKSPACE_REFRESH_TOKEN=1//fake
MCPTOOLING_ALLOWED_TOKENS=tok1,tok2
"""

SECRETS_CONTENT_WITH_BAD_SCOPES = """\
GOOGLE_WORKSPACE_CLIENT_ID=test.apps.googleusercontent.com
GOOGLE_WORKSPACE_CLIENT_SECRET=test-secret
GOOGLE_WORKSPACE_REFRESH_TOKEN=1//fake
MCPTOOLING_ALLOWED_TOKENS=tok1,tok2
GOOGLE_WORKSPACE_SCOPES=https://www.googleapis.com/auth/drive.file,https://www.googleapis.com/auth/gmail.readonly
"""

SECRETS_CONTENT_WITH_GOOD_SCOPES = """\
GOOGLE_WORKSPACE_CLIENT_ID=test.apps.googleusercontent.com
GOOGLE_WORKSPACE_CLIENT_SECRET=test-secret
GOOGLE_WORKSPACE_REFRESH_TOKEN=1//fake
MCPTOOLING_ALLOWED_TOKENS=tok1,tok2
GOOGLE_WORKSPACE_SCOPES=https://www.googleapis.com/auth/drive.file,https://www.googleapis.com/auth/documents
"""


@pytest.fixture
def secrets_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write a default narrow-scopes secrets file and point MCPTOOLING_SECRETS_PATH at it."""
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_CONTENT_NARROW)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))
    return path


def test_setup_returns_registry_and_allowlist(secrets_file: Path):
    """Narrow default scopes should produce a healthy registry + allowlist."""
    registry, allowlist, diagnostics = gw_main.setup()

    assert len(registry) == 5  # all five tools registered
    names = sorted(t.tool_name for t in registry._tools.values())
    assert names == sorted(
        [
            "create_document",
            "drive_create_file",
            "drive_list_files",
            "drive_update_file",
            "get_document",
        ]
    )
    # Default scopes are sorted alphabetically by the client (documents
    # comes before drive.file in lex order).
    assert diagnostics["scopes"] == [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive.file",
    ]
    assert diagnostics["configured_scopes"] == []  # unset
    # Allowlist gets all tokens; all tools permitted by default.
    assert "tok1" in allowlist.allowed_tokens
    assert "tok2" in allowlist.allowed_tokens


def test_setup_refuses_bad_scopes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A gmail scope in GOOGLE_WORKSPACE_SCOPES must exit with code 2 and not register anything."""
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_CONTENT_WITH_BAD_SCOPES)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))

    with pytest.raises(SystemExit) as exc:
        gw_main.setup()
    assert exc.value.code == 2


def test_setup_accepts_explicit_narrow_scopes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Operators may set GOOGLE_WORKSPACE_SCOPES to the narrow allowlist explicitly.

    Configured order is preserved (drive.file first, then documents),
    matching what validate_scopes returns.
    """
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_CONTENT_WITH_GOOD_SCOPES)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))

    registry, _allowlist, diagnostics = gw_main.setup()
    assert len(registry) == 5
    assert diagnostics["scopes"] == [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/documents",
    ]
    # And configured_scopes echoes the operator's intent.
    assert diagnostics["configured_scopes"] == [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/documents",
    ]


def test_setup_missing_secrets_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Missing secrets file must exit with code 1."""
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(tmp_path / "missing.env"))

    with pytest.raises(SystemExit) as exc:
        gw_main.setup()
    assert exc.value.code == 1


def test_setup_missing_required_key_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A missing GOOGLE_WORKSPACE_REFRESH_TOKEN must exit 1 (secrets layer)."""
    path = tmp_path / "secrets.env"
    path.write_text(
        """\
GOOGLE_WORKSPACE_CLIENT_ID=test.apps.googleusercontent.com
GOOGLE_WORKSPACE_CLIENT_SECRET=test-secret
MCPTOOLING_ALLOWED_TOKENS=tok1
"""
    )
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))

    with pytest.raises(SystemExit) as exc:
        gw_main.setup()
    assert exc.value.code == 1


def test_parse_scopes_empty():
    assert gw_main._parse_scopes(None) == []
    assert gw_main._parse_scopes("") == []


def test_parse_scopes_strips_whitespace():
    raw = " https://a , https://b ,https://c "
    out = gw_main._parse_scopes(raw)
    assert out == ["https://a", "https://b", "https://c"]
