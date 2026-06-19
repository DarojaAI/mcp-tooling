"""Tests for scripts/ci/render-agent-tokens.py."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "render-agent-tokens.py"

# Load the script as a module so we can call its helpers directly (faster
# than spawning a subprocess for every assertion). The script uses
# __future__ annotations and is otherwise self-contained.
_spec = importlib.util.spec_from_file_location("render_agent_tokens", SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# ---------------------------------------------------------------------------
# Unit tests on helpers
# ---------------------------------------------------------------------------


def test_mint_token_is_deterministic():
    """Same (salt, server, agent) always yields the same token."""
    a = _mod._mint_token("salt-xyz", "duffel", "trip_planning")
    b = _mod._mint_token("salt-xyz", "duffel", "trip_planning")
    assert a == b
    assert a.startswith("ag_")
    assert len(a) == 3 + 64  # "ag_" + 64-char sha256 hex


def test_mint_token_changes_with_salt():
    """Different salts produce different tokens for the same agent."""
    a = _mod._mint_token("salt-1", "duffel", "trip_planning")
    b = _mod._mint_token("salt-2", "duffel", "trip_planning")
    assert a != b


def test_mint_token_changes_with_agent():
    """Different agents produce different tokens under the same salt."""
    a = _mod._mint_token("salt", "duffel", "trip_planning")
    b = _mod._mint_token("salt", "duffel", "other_agent")
    assert a != b


def test_mint_token_changes_with_server():
    """Different servers produce different tokens for the same agent."""
    a = _mod._mint_token("salt", "duffel", "trip_planning")
    b = _mod._mint_token("salt", "atlas", "trip_planning")
    assert a != b


def test_agent_keys_handles_explicit_bindings():
    bindings = [{"agent": "trip_planning", "servers": ["duffel"]}]
    assert _mod._agent_keys(bindings) == [("trip_planning", "duffel")]


def test_agent_keys_expands_wildcard_default():
    """The '*' agent becomes '<server>_default' for each listed server."""
    bindings = [{"agent": "*", "servers": ["duffel", "atlas"]}]
    assert _mod._agent_keys(bindings) == [
        ("duffel_default", "duffel"),
        ("atlas_default", "atlas"),
    ]


def test_agent_keys_mixes_explicit_and_default():
    bindings = [
        {"agent": "trip_planning", "servers": ["duffel"]},
        {"agent": "*", "servers": ["duffel"]},
    ]
    # Explicit agent takes precedence over default; both are emitted.
    assert _mod._agent_keys(bindings) == [
        ("trip_planning", "duffel"),
        ("duffel_default", "duffel"),
    ]


def test_agent_keys_dedupes_repeated_bindings():
    """If the same agent/server pair appears twice, only one token is minted."""
    bindings = [
        {"agent": "trip_planning", "servers": ["duffel"]},
        {"agent": "trip_planning", "servers": ["duffel"]},
    ]
    assert _mod._agent_keys(bindings) == [("trip_planning", "duffel")]


def test_parse_bindings_rejects_non_array():
    with pytest.raises(SystemExit):
        _mod._parse_bindings('{"agent": "x", "servers": ["y"]}')


def test_parse_bindings_rejects_missing_keys():
    with pytest.raises(SystemExit):
        _mod._parse_bindings('[{"agent": "x"}]')


def test_parse_bindings_rejects_non_list_servers():
    with pytest.raises(SystemExit):
        _mod._parse_bindings('[{"agent": "x", "servers": "duffel"}]')


def test_existing_tokens_handles_empty():
    assert _mod._existing_tokens("") == set()


def test_existing_tokens_handles_whitespace_and_commas():
    assert _mod._existing_tokens(" a , b ,, c ") == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# End-to-end via subprocess (covers the argparse + main() path)
# ---------------------------------------------------------------------------


def _run_script(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    full_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_end_to_end_emits_merged_env_and_artifact(tmp_path: Path):
    """Default + explicit bindings -> merged env var + JSON artifact."""
    bindings = [
        {"agent": "trip_planning", "servers": ["duffel"]},
        {"agent": "*", "servers": ["duffel"]},
    ]
    out_json = tmp_path / "agent-tokens.json"

    result = _run_script(
        {
            "MCPTOOLING_AGENT_TOKEN_SALT": "salt-abc",
            "MCPTOOLING_AGENT_BINDINGS_JSON": json.dumps(bindings),
            "MCPTOOLING_ALLOWED_TOKENS": "global-human-token-1,global-human-token-2",
        },
        "--out-merged-env",
        "--out-agent-json",
        str(out_json),
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"

    # merged env var
    assert "MCPTOOLING_ALLOWED_TOKENS=" in result.stdout
    line = next(
        ln for ln in result.stdout.splitlines() if ln.startswith("MCPTOOLING_ALLOWED_TOKENS=")
    )
    merged = line.split("=", 1)[1].split(",")
    # Two global tokens + two derived agent tokens = 4.
    assert "global-human-token-1" in merged
    assert "global-human-token-2" in merged
    # Two derived tokens, one per (server, agent) pair.
    derived = [t for t in merged if t.startswith("ag_")]
    assert len(derived) == 2

    # JSON artifact shape: {"duffel": {"trip_planning": "...", "duffel_default": "..."}}
    artifact = json.loads(out_json.read_text())
    assert "duffel" in artifact
    assert set(artifact["duffel"].keys()) == {"trip_planning", "duffel_default"}
    # Deterministic: same salt + same binding yields same token.
    expected_trip = _mod._mint_token("salt-abc", "duffel", "trip_planning")
    expected_default = _mod._mint_token("salt-abc", "duffel", "duffel_default")
    assert artifact["duffel"]["trip_planning"] == expected_trip
    assert artifact["duffel"]["duffel_default"] == expected_default


def test_end_to_end_dedupes_when_global_token_collides(tmp_path: Path):
    """If a derived token happens to match a global one, dedupe silently."""
    salt = "salt-xyz"
    bindings = [{"agent": "trip_planning", "servers": ["duffel"]}]
    derived = _mod._mint_token(salt, "duffel", "trip_planning")

    result = _run_script(
        {
            "MCPTOOLING_AGENT_TOKEN_SALT": salt,
            "MCPTOOLING_AGENT_BINDINGS_JSON": json.dumps(bindings),
            "MCPTOOLING_ALLOWED_TOKENS": derived,  # already contains the derived token
        },
        "--out-merged-env",
        "--out-agent-json",
        str(tmp_path / "out.json"),
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    line = next(
        ln for ln in result.stdout.splitlines() if ln.startswith("MCPTOOLING_ALLOWED_TOKENS=")
    )
    merged = line.split("=", 1)[1].split(",")
    assert merged.count(derived) == 1  # not duplicated


def test_end_to_end_fails_without_salt():
    result = _run_script(
        {
            "MCPTOOLING_AGENT_BINDINGS_JSON": "[]",
            "MCPTOOLING_ALLOWED_TOKENS": "tok",
        },
    )
    assert result.returncode != 0
    assert "MCPTOOLING_AGENT_TOKEN_SALT" in result.stderr


def test_end_to_end_fails_with_invalid_json():
    result = _run_script(
        {
            "MCPTOOLING_AGENT_TOKEN_SALT": "s",
            "MCPTOOLING_AGENT_BINDINGS_JSON": "not-json",
            "MCPTOOLING_ALLOWED_TOKENS": "tok",
        },
    )
    assert result.returncode == 2


def test_end_to_end_fails_with_empty_binding_list():
    """An empty binding list is rejected (it would silently remove all
    per-agent tokens, which is almost always a config bug)."""
    result = _run_script(
        {
            "MCPTOOLING_AGENT_TOKEN_SALT": "s",
            "MCPTOOLING_AGENT_BINDINGS_JSON": "[]",
            "MCPTOOLING_ALLOWED_TOKENS": "tok",
        },
    )
    assert result.returncode == 3