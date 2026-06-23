"""Tests for servers.amadeus_hotels.__main__.setup().

These exercise the third auth shape (OAuth client credentials) through
the generic ServerSpec runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from servers.amadeus_hotels import __main__ as am_main

SECRETS_CONTENT = """\
AMADEUS_CLIENT_ID=test_client_id
AMADEUS_CLIENT_SECRET=***
AMADEUS_ENV=test
MCPTOOLING_ALLOWED_TOKENS=tok1,tok2
"""

SECRETS_CONTENT_PROD = """\
AMADEUS_CLIENT_ID=test_client_id
AMADEUS_CLIENT_SECRET=***
AMADEUS_ENV=production
MCPTOOLING_ALLOWED_TOKENS=tok1
"""


@pytest.fixture
def secrets_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_CONTENT)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))
    return path


def test_setup_registers_all_four_tools(secrets_file: Path):
    """All four Amadeus hotel-search tools must register on startup."""
    registry, allowlist, diagnostics = am_main.setup()

    assert len(registry) == 4
    names = sorted(t.tool_name for t in registry._tools.values())
    assert names == sorted(
        [
            "autocomplete_hotel_name",
            "get_hotel_ratings",
            "list_hotels_by_city",
            "search_hotels",
        ]
    )
    assert diagnostics["name"] == "amadeus-hotels"
    assert diagnostics["tool_count"] == 4
    # Allowlist gets tokens; default allow_all_tools is True.
    assert "tok1" in allowlist.allowed_tokens
    assert "tok2" in allowlist.allowed_tokens


def test_setup_uses_production_env_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """AMADEUS_ENV=production must flow through to the client."""
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_CONTENT_PROD)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))

    registry, _allowlist, _diagnostics = am_main.setup()
    # Verify by inspecting the first tool's client.
    first_tool = next(iter(registry._tools.values()))
    assert first_tool._client.env == "production"


def test_setup_missing_secrets_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Missing secrets file must exit 1."""
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(tmp_path / "missing.env"))
    with pytest.raises(SystemExit) as exc:
        am_main.setup()
    assert exc.value.code == 1


def test_setup_missing_required_key_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Missing AMADEUS_CLIENT_SECRET must exit 1."""
    path = tmp_path / "secrets.env"
    path.write_text(
        """\
AMADEUS_CLIENT_ID=test_client_id
MCPTOOLING_ALLOWED_TOKENS=tok1
"""
    )
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))
    with pytest.raises(SystemExit) as exc:
        am_main.setup()
    assert exc.value.code == 1


def test_setup_default_env_is_test_when_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Without AMADEUS_ENV, the client must default to test environment."""
    path = tmp_path / "secrets.env"
    path.write_text(
        """\
AMADEUS_CLIENT_ID=test_client_id
AMADEUS_CLIENT_SECRET=***
MCPTOOLING_ALLOWED_TOKENS=tok1
"""
    )
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))
    registry, _allowlist, _diagnostics = am_main.setup()
    first_tool = next(iter(registry._tools.values()))
    assert first_tool._client.env == "test"
