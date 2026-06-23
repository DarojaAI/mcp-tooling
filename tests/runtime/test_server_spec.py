"""Tests for runtime.server_spec.

These test the generic runtime against fake build_client/build_tools
callbacks. Per-server tests (duffel, google-workspace) live in
servers/<name>/tests/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.allowlist import Allowlist
from runtime.base import BaseTool
from runtime.registry import ToolRegistry
from runtime.server_spec import ScopePolicy, ServerSpec, run_server, setup


SECRETS_DUFFEL = """\
DUFFEL_API_KEY=test_duffel_key
MCPTOOLING_ALLOWED_TOKENS=tok1,tok2
"""

SECRETS_GW_NARROW = """\
GOOGLE_WORKSPACE_CLIENT_ID=test.apps.googleusercontent.com
GOOGLE_WORKSPACE_CLIENT_SECRET=test-secret
GOOGLE_WORKSPACE_REFRESH_TOKEN=1//fake
MCPTOOLING_ALLOWED_TOKENS=tok1,tok2
"""

SECRETS_GW_BAD_SCOPES = """\
GOOGLE_WORKSPACE_CLIENT_ID=test.apps.googleusercontent.com
GOOGLE_WORKSPACE_CLIENT_SECRET=test-secret
GOOGLE_WORKSPACE_REFRESH_TOKEN=1//fake
MCPTOOLING_ALLOWED_TOKENS=tok1,tok2
GOOGLE_WORKSPACE_SCOPES=https://www.googleapis.com/auth/gmail.readonly
"""


# ---------------------------------------------------------------------------
# Fake tools for testing build_tools callbacks.
# ---------------------------------------------------------------------------


class _FakeTool(BaseTool):
    def __init__(self, name):
        self._name = name

    @property
    def tool_name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"fake {self._name}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"result": "ok"}


def _build_fake_client(secrets):
    return {"client": "fake", "api_key": secrets["DUFFEL_API_KEY"]}


def _build_fake_tools(client):
    return [_FakeTool("alpha"), _FakeTool("beta"), _FakeTool("gamma")]


# ---------------------------------------------------------------------------
# Tests for the non-OAuth path (Duffel shape).
# ---------------------------------------------------------------------------


def test_setup_non_oauth_returns_registry_and_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A non-OAuth spec produces a working registry + allowlist."""
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_DUFFEL)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))

    spec = ServerSpec(
        name="fake-duffel",
        default_port=9999,
        required_secrets=frozenset({"DUFFEL_API_KEY", "MCPTOOLING_ALLOWED_TOKENS"}),
        build_client=_build_fake_client,
        build_tools=_build_fake_tools,
    )
    registry, allowlist, diagnostics = setup(spec)

    assert len(registry) == 3
    assert sorted(t.tool_name for t in registry._tools.values()) == ["alpha", "beta", "gamma"]
    assert "tok1" in allowlist.allowed_tokens
    assert "tok2" in allowlist.allowed_tokens
    assert diagnostics["name"] == "fake-duffel"
    assert diagnostics["tool_count"] == 3
    # Non-OAuth: no scopes in diagnostics.
    assert diagnostics["scopes"] == []
    assert diagnostics["configured_scopes"] == []


def test_setup_non_oauth_missing_secrets_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Missing secrets file → SystemExit(1)."""
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(tmp_path / "missing.env"))
    spec = ServerSpec(
        name="fake",
        default_port=9999,
        required_secrets=frozenset({"DUFFEL_API_KEY"}),
        build_client=_build_fake_client,
        build_tools=_build_fake_tools,
    )
    with pytest.raises(SystemExit) as exc:
        setup(spec)
    assert exc.value.code == 1


def test_setup_non_oauth_missing_required_key_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Missing required key in secrets file → SystemExit(1)."""
    path = tmp_path / "secrets.env"
    path.write_text("# empty\n")
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))
    spec = ServerSpec(
        name="fake",
        default_port=9999,
        required_secrets=frozenset({"DUFFEL_API_KEY"}),
        build_client=_build_fake_client,
        build_tools=_build_fake_tools,
    )
    with pytest.raises(SystemExit) as exc:
        setup(spec)
    assert exc.value.code == 1


def test_setup_no_build_client_raises_runtime_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A spec without build_client must fail loudly at setup(), not silently."""
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_DUFFEL)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))
    spec = ServerSpec(
        name="fake",
        default_port=9999,
        required_secrets=frozenset({"DUFFEL_API_KEY", "MCPTOOLING_ALLOWED_TOKENS"}),
        build_client=None,
        build_tools=_build_fake_tools,
    )
    with pytest.raises(RuntimeError, match="no build_client callback"):
        setup(spec)


# ---------------------------------------------------------------------------
# Tests for the OAuth path (google-workspace shape).
# ---------------------------------------------------------------------------


def _scope_policy():
    """Minimal scope policy matching the google-workspace contract."""
    from servers.google_workspace.scope_guard import ALLOWED_SCOPES, ScopePolicyError, validate_scopes

    return ScopePolicy(
        scope_env_var="GOOGLE_WORKSPACE_SCOPES",
        parse=lambda raw: [s.strip() for s in (raw or "").split(",") if s.strip()],
        validate=validate_scopes,
        default_when_unset=sorted(ALLOWED_SCOPES),
    )


def _build_oauth_client(secrets, *, scopes=None):
    return {"client": "fake-oauth", "scopes": list(scopes or [])}


def test_setup_oauth_default_scopes_used_when_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Unset GOOGLE_WORKSPACE_SCOPES → narrow defaults applied."""
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_GW_NARROW)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))

    spec = ServerSpec(
        name="fake-gw",
        default_port=9998,
        required_secrets=frozenset({
            "GOOGLE_WORKSPACE_CLIENT_ID",
            "GOOGLE_WORKSPACE_CLIENT_SECRET",
            "GOOGLE_WORKSPACE_REFRESH_TOKEN",
            "MCPTOOLING_ALLOWED_TOKENS",
        }),
        optional_secrets=frozenset({"GOOGLE_WORKSPACE_SCOPES"}),
        scope_policy=_scope_policy(),
        build_client=_build_oauth_client,
        build_tools=_build_fake_tools,
    )
    _registry, _allowlist, diagnostics = setup(spec)

    assert diagnostics["configured_scopes"] == []  # unset
    assert diagnostics["scopes"] == sorted([
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive.file",
    ])


def test_setup_oauth_explicit_narrow_scopes_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Explicit narrow scopes are validated and passed to build_client."""
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_GW_NARROW + "GOOGLE_WORKSPACE_SCOPES=https://www.googleapis.com/auth/drive.file,https://www.googleapis.com/auth/documents\n")
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))

    spec = ServerSpec(
        name="fake-gw",
        default_port=9998,
        required_secrets=frozenset({
            "GOOGLE_WORKSPACE_CLIENT_ID",
            "GOOGLE_WORKSPACE_CLIENT_SECRET",
            "GOOGLE_WORKSPACE_REFRESH_TOKEN",
            "MCPTOOLING_ALLOWED_TOKENS",
        }),
        optional_secrets=frozenset({"GOOGLE_WORKSPACE_SCOPES"}),
        scope_policy=_scope_policy(),
        build_client=_build_oauth_client,
        build_tools=_build_fake_tools,
    )
    _registry, _allowlist, diagnostics = setup(spec)

    assert diagnostics["configured_scopes"] == [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/documents",
    ]


def test_setup_oauth_disallowed_scope_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A disallowed scope must exit 2 BEFORE any tool registers."""
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_GW_BAD_SCOPES)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))

    spec = ServerSpec(
        name="fake-gw",
        default_port=9998,
        required_secrets=frozenset({
            "GOOGLE_WORKSPACE_CLIENT_ID",
            "GOOGLE_WORKSPACE_CLIENT_SECRET",
            "GOOGLE_WORKSPACE_REFRESH_TOKEN",
            "MCPTOOLING_ALLOWED_TOKENS",
        }),
        optional_secrets=frozenset({"GOOGLE_WORKSPACE_SCOPES"}),
        scope_policy=_scope_policy(),
        build_client=_build_oauth_client,
        build_tools=_build_fake_tools,
    )
    with pytest.raises(SystemExit) as exc:
        setup(spec)
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Tests for run_server (the entrypoint).
# ---------------------------------------------------------------------------


def test_run_server_stdio_spawns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """run_server(transport='stdio') must reach start_stdio_server."""
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_DUFFEL)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))

    started = {"value": False}

    async def fake_run_stdio(registry, name):
        started["value"] = True

    import runtime.server_spec as ss

    monkeypatch.setattr(ss, "run_stdio", fake_run_stdio)

    spec = ServerSpec(
        name="fake",
        default_port=9999,
        required_secrets=frozenset({"DUFFEL_API_KEY", "MCPTOOLING_ALLOWED_TOKENS"}),
        build_client=_build_fake_client,
        build_tools=_build_fake_tools,
    )
    run_server(spec, transport="stdio")
    assert started["value"] is True


def test_run_server_unknown_transport_exits(monkeypatch: pytest.MonkeyPatch):
    """An unknown transport must exit 1, not silently default."""
    spec = ServerSpec(
        name="fake",
        default_port=9999,
        required_secrets=frozenset(),
        build_client=_build_fake_client,
        build_tools=_build_fake_tools,
    )
    with pytest.raises(SystemExit) as exc:
        run_server(spec, transport="bogus")
    assert exc.value.code == 1


def test_run_server_uses_default_port_when_none_provided(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """run_server(transport='streamable-http') without port= uses spec.default_port."""
    path = tmp_path / "secrets.env"
    path.write_text(SECRETS_DUFFEL)
    monkeypatch.setenv("MCPTOOLING_SECRETS_PATH", str(path))

    captured = {"port": None}

    def fake_run_http(registry, allowlist, name, port):
        captured["port"] = port

    import runtime.server_spec as ss

    monkeypatch.setattr(ss, "run_http", fake_run_http)

    spec = ServerSpec(
        name="fake",
        default_port=12345,
        required_secrets=frozenset({"DUFFEL_API_KEY", "MCPTOOLING_ALLOWED_TOKENS"}),
        build_client=_build_fake_client,
        build_tools=_build_fake_tools,
    )
    run_server(spec, transport="streamable-http")
    assert captured["port"] == 12345