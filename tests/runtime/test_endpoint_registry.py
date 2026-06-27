"""Tests for scripts/ci/endpoint_registry.py.

Covers the static endpoint-registry file shape, the merge/update logic
(must not lose data when two (server, env) keys coexist), the schema
validator (reject malformed URLs / missing keys / unknown keys), and
the CLI surface of scripts/ci/print-endpoint.py.

The registry library lives in scripts/ci/ because it is consumed by a
deploy workflow job and by humans running `python scripts/ci/print-endpoint.py`,
not by the runtime servers. The tests live here in tests/runtime/ for
collection convenience — pytest discovers them via the existing test
configuration.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# scripts/ci/ is not on the default sys.path; add it for these tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import endpoint_registry as reg  # noqa: E402

# ---------------------------------------------------------------------------
# Empty / load
# ---------------------------------------------------------------------------


def test_empty_registry_shape():
    data = reg.empty_registry()
    assert data == {"servers": {}}


def test_load_missing_file_returns_empty(tmp_path):
    data = reg.load(tmp_path / "does-not-exist.yaml")
    assert data == {"servers": {}}


def test_load_empty_file_returns_empty(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    assert reg.load(p) == {"servers": {}}


def test_load_only_whitespace_returns_empty(tmp_path):
    p = tmp_path / "ws.yaml"
    p.write_text("   \n\n")
    assert reg.load(p) == {"servers": {}}


def test_load_unparseable_yaml_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("not: [valid: yaml")
    with pytest.raises(reg.EndpointRegistryError, match="failed to parse"):
        reg.load(p)


def test_load_top_level_not_mapping_raises(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- one\n- two\n")
    with pytest.raises(reg.EndpointRegistryError, match="top-level must be a mapping"):
        reg.load(p)


def test_load_tolerates_top_level_without_servers_key(tmp_path):
    p = tmp_path / "minimal.yaml"
    p.write_text("{}")
    assert reg.load(p) == {"servers": {}}


def test_load_rejects_servers_not_mapping(tmp_path):
    p = tmp_path / "bad-servers.yaml"
    p.write_text("servers: not-a-mapping\n")
    with pytest.raises(reg.EndpointRegistryError, match="'servers' must be a mapping"):
        reg.load(p)


# ---------------------------------------------------------------------------
# update — happy path
# ---------------------------------------------------------------------------


def _frozen_now() -> datetime:
    # `timezone.utc` (not `datetime.UTC`) so this stays 3.10-compatible.
    return datetime(2026, 6, 23, 20, 35, 12, tzinfo=timezone.utc)  # noqa: UP017


def test_update_inserts_first_entry():
    data = reg.empty_registry()
    out = reg.update(
        data,
        shape="self_hosted",
        server="google-workspace",
        env="dev",
        mcp_url="http://203.0.113.20:8766/mcp",
        health="http://203.0.113.20:8766/healthz",
        last_run="https://github.com/DarojaAI/mcp-tooling/actions/runs/12345",
        now=_frozen_now(),
    )
    assert out == {
        "servers": {
            "google-workspace": {
                "dev": {
                    "shape": "self_hosted",
                    "mcp_url": "http://203.0.113.20:8766/mcp",
                    "health": "http://203.0.113.20:8766/healthz",
                    "last_deployed": "2026-06-23T20:35:12Z",
                    "last_run": "https://github.com/DarojaAI/mcp-tooling/actions/runs/12345",
                }
            }
        }
    }
    # Caller's dict is not mutated.
    assert data == {"servers": {}}


def test_update_overwrites_existing_entry():
    data = reg.update(
        reg.empty_registry(),
        server="google-workspace",
        env="dev",
        mcp_url="http://203.0.113.20:8766/mcp",
        health="http://203.0.113.20:8766/healthz",
        now=_frozen_now(),
    )
    later = reg.update(
        data,
        server="google-workspace",
        env="dev",
        mcp_url="http://203.0.113.21:8766/mcp",
        health="http://203.0.113.21:8766/healthz",
        now=datetime(2026, 6, 24, 9, 0, 0, tzinfo=timezone.utc),  # noqa: UP017
    )
    assert later["servers"]["google-workspace"]["dev"]["mcp_url"] == "http://203.0.113.21:8766/mcp"
    assert later["servers"]["google-workspace"]["dev"]["health"] == "http://203.0.113.21:8766/healthz"
    assert later["servers"]["google-workspace"]["dev"]["last_deployed"] == "2026-06-24T09:00:00Z"


def test_update_preserves_sibling_entries_across_servers():
    """Two servers, one env each — updating one must not touch the other."""
    data = reg.update(
        reg.empty_registry(),
        server="duffel",
        env="dev",
        mcp_url="http://203.0.113.10:8765/mcp",
        health="http://203.0.113.10:8765/healthz",
        now=_frozen_now(),
    )
    data = reg.update(
        data,
        shape="self_hosted",
        server="google-workspace",
        env="dev",
        mcp_url="http://203.0.113.20:8766/mcp",
        health="http://203.0.113.20:8766/healthz",
        now=_frozen_now(),
    )
    assert reg.list_servers(data) == ["duffel", "google-workspace"]
    assert reg.get(data, "duffel", "dev")["mcp_url"] == "http://203.0.113.10:8765/mcp"
    assert reg.get(data, "google-workspace", "dev")["mcp_url"] == "http://203.0.113.20:8766/mcp"


def test_update_preserves_sibling_entries_across_envs():
    """Same server, two envs — updating dev must not touch prod (and vice versa).

    This is the case that matters for the workflow: dev and prod deploys
    can land minutes apart, and a prod entry must survive a dev update.
    """
    data = reg.update(
        reg.empty_registry(),
        server="duffel",
        env="dev",
        mcp_url="http://203.0.113.10:8765/mcp",
        health="http://203.0.113.10:8765/healthz",
        now=_frozen_now(),
    )
    data = reg.update(
        data,
        shape="self_hosted",
        server="duffel",
        env="prod",
        mcp_url="http://198.51.100.5:8765/mcp",
        health="http://198.51.100.5:8765/healthz",
        now=_frozen_now(),
    )
    assert reg.list_envs(data, "duffel") == ["dev", "prod"]
    assert reg.get(data, "duffel", "dev")["mcp_url"] == "http://203.0.113.10:8765/mcp"
    assert reg.get(data, "duffel", "prod")["mcp_url"] == "http://198.51.100.5:8765/mcp"


def test_update_omits_last_run_when_not_given():
    data = reg.update(
        reg.empty_registry(),
        server="duffel",
        env="dev",
        mcp_url="http://203.0.113.10:8765/mcp",
        health="http://203.0.113.10:8765/healthz",
        now=_frozen_now(),
    )
    assert "last_run" not in data["servers"]["duffel"]["dev"]


def test_update_uses_real_now_when_not_provided():
    """Smoke test — if `now` is None we use datetime.now(); verify the
    shape is still valid (last_deployed is a current ISO-8601 'Z' string).
    """
    data = reg.update(
        reg.empty_registry(),
        server="duffel",
        env="dev",
        mcp_url="http://203.0.113.10:8765/mcp",
        health="http://203.0.113.10:8765/healthz",
    )
    last = data["servers"]["duffel"]["dev"]["last_deployed"]
    assert reg._ISO_8601_RE.match(last)


# ---------------------------------------------------------------------------
# update — validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_value",
    [
        "not-a-url",
        "",
        "ftp://example.com/foo",  # wrong scheme
        "javascript:alert(1)",
        "http:// space-in-host",
    ],
)
def test_update_rejects_bad_mcp_url(bad_value):
    with pytest.raises(reg.EndpointRegistryError, match="mcp_url is not a valid"):
        reg.update(
            reg.empty_registry(),
            server="duffel",
            env="dev",
            mcp_url=bad_value,
            health="http://203.0.113.10:8765/healthz",
            now=_frozen_now(),
        )


@pytest.mark.parametrize(
    "bad_value",
    [
        "not-a-url",
        "",
        "ftp://example.com/healthz",
    ],
)
def test_update_rejects_bad_health(bad_value):
    with pytest.raises(reg.EndpointRegistryError, match="health is not a valid"):
        reg.update(
            reg.empty_registry(),
            server="duffel",
            env="dev",
            mcp_url="http://203.0.113.10:8765/mcp",
            health=bad_value,
            now=_frozen_now(),
        )


@pytest.mark.parametrize(
    "bad_name",
    [
        "",  # empty
        "-leading-hyphen",
        "has spaces",
        "has/slash",
        "a" * 65,  # too long
    ],
)
def test_update_rejects_bad_server_name(bad_name):
    with pytest.raises(reg.EndpointRegistryError, match="server name must match"):
        reg.update(
            reg.empty_registry(),
            server=bad_name,
            env="dev",
            mcp_url="http://203.0.113.10:8765/mcp",
            health="http://203.0.113.10:8765/healthz",
            now=_frozen_now(),
        )


@pytest.mark.parametrize(
    "bad_name",
    ["", "-leading-hyphen", "has/slash", "a" * 65],
)
def test_update_rejects_bad_env_name(bad_name):
    with pytest.raises(reg.EndpointRegistryError, match="env name must match"):
        reg.update(
            reg.empty_registry(),
            server="duffel",
            env=bad_name,
            mcp_url="http://203.0.113.10:8765/mcp",
            health="http://203.0.113.10:8765/healthz",
            now=_frozen_now(),
        )


# ---------------------------------------------------------------------------
# dump + write — round-trip
# ---------------------------------------------------------------------------


def test_dump_includes_header():
    out = reg.dump(reg.empty_registry())
    assert out.startswith(reg.FILE_HEADER)
    assert "mcp-tooling - MCP endpoint registry" in out


def test_dump_emits_valid_yaml():
    data = reg.update(
        reg.empty_registry(),
        server="google-workspace",
        env="dev",
        mcp_url="http://203.0.113.20:8766/mcp",
        health="http://203.0.113.20:8766/healthz",
        now=_frozen_now(),
    )
    out = reg.dump(data)
    # Header is plain text; the YAML body parses cleanly on its own.
    body_start = out.index("servers:")
    body = out[body_start:]
    reloaded = reg.loads(body)
    assert reloaded == data


def test_write_round_trip(tmp_path):
    p = tmp_path / "endpoints.yaml"
    data = reg.update(
        reg.empty_registry(),
        server="google-workspace",
        env="dev",
        mcp_url="http://203.0.113.20:8766/mcp",
        health="http://203.0.113.20:8766/healthz",
        now=_frozen_now(),
    )
    reg.write(p, data)
    assert reg.load(p) == data


def test_write_creates_parent_dirs(tmp_path):
    p = tmp_path / "nested" / "deeper" / "endpoints.yaml"
    data = reg.update(
        reg.empty_registry(),
        server="duffel",
        env="dev",
        mcp_url="http://203.0.113.10:8765/mcp",
        health="http://203.0.113.10:8765/healthz",
        now=_frozen_now(),
    )
    reg.write(p, data)
    assert p.exists()


def test_write_is_atomic(tmp_path):
    """The .tmp file should not be left behind after a successful write."""
    p = tmp_path / "endpoints.yaml"
    data = reg.update(
        reg.empty_registry(),
        server="duffel",
        env="dev",
        mcp_url="http://203.0.113.10:8765/mcp",
        health="http://203.0.113.10:8765/healthz",
        now=_frozen_now(),
    )
    reg.write(p, data)
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []


# ---------------------------------------------------------------------------
# Schema validation on load
# ---------------------------------------------------------------------------


def test_validate_rejects_missing_required_key(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "servers:\n"
        "  duffel:\n"
        "    dev:\n"
        "      shape: self_hosted\n"
        "      mcp_url: http://x/mcp\n"
        "      # missing health + last_deployed\n"
    )
    with pytest.raises(reg.EndpointRegistryError, match="missing keys"):
        reg.load(p)


def test_validate_rejects_unknown_key(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "servers:\n"
        "  duffel:\n"
        "    dev:\n"
        "      shape: self_hosted\n"
        "      mcp_url: http://x/mcp\n"
        "      health: http://x/healthz\n"
        "      last_deployed: 2026-06-23T20:35:12Z\n"
        "      surprise: 'should not be here'\n"
    )
    with pytest.raises(reg.EndpointRegistryError, match="unknown keys"):
        reg.load(p)


def test_validate_rejects_bad_last_deployed_format(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "servers:\n"
        "  duffel:\n"
        "    dev:\n"
        "      shape: self_hosted\n"
        "      mcp_url: http://x/mcp\n"
        "      health: http://x/healthz\n"
        "      last_deployed: '2026-06-23 20:35:12'\n"  # space, not 'T'
    )
    with pytest.raises(reg.EndpointRegistryError, match="last_deployed must be ISO-8601"):
        reg.load(p)


def test_validate_rejects_non_mapping_entry(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "servers:\n"
        "  duffel:\n"
        "    dev: 'just-a-string'\n"
    )
    with pytest.raises(reg.EndpointRegistryError, match="must be a mapping"):
        reg.load(p)


# ---------------------------------------------------------------------------
# Shape 2 (remote_mcp) — config-only entries, no /healthz we control
# ---------------------------------------------------------------------------


def test_update_inserts_remote_mcp_entry():
    """Shape 2 entries require shape + mcp_url + last_deployed; health is optional."""
    data = reg.empty_registry()
    out = reg.update(
        data,
        server="trivago",
        env="dev",
        mcp_url="https://mcp.trivago.com/mcp",
        shape="remote_mcp",
        transport="streamable-http",
        last_run="https://github.com/DarojaAI/mcp-tooling/actions/runs/12347",
        now=_frozen_now(),
    )
    assert out == {
        "servers": {
            "trivago": {
                "dev": {
                    "shape": "remote_mcp",
                    "transport": "streamable-http",
                    "mcp_url": "https://mcp.trivago.com/mcp",
                    "last_deployed": "2026-06-23T20:35:12Z",
                    "last_run": "https://github.com/DarojaAI/mcp-tooling/actions/runs/12347",
                }
            }
        }
    }


def test_update_remote_mcp_defaults_transport_when_omitted():
    """If the caller doesn't pass transport, the entry simply omits it
    (we never persist a default — absence means 'whatever the vendor shipped')."""
    data = reg.update(
        reg.empty_registry(),
        server="trivago",
        env="dev",
        mcp_url="https://mcp.trivago.com/mcp",
        shape="remote_mcp",
        now=_frozen_now(),
    )
    assert "transport" not in data["servers"]["trivago"]["dev"]


def test_update_remote_mcp_health_optional():
    """Vendors that expose a health probe can record it; vendors that
    don't, won't. Both must validate."""
    with_health = reg.update(
        reg.empty_registry(),
        server="trivago",
        env="dev",
        mcp_url="https://mcp.trivago.com/mcp",
        shape="remote_mcp",
        health="https://mcp.trivago.com/healthz",
        now=_frozen_now(),
    )
    assert with_health["servers"]["trivago"]["dev"]["health"] == "https://mcp.trivago.com/healthz"

    without_health = reg.update(
        reg.empty_registry(),
        server="trivago",
        env="dev",
        mcp_url="https://mcp.trivago.com/mcp",
        shape="remote_mcp",
        now=_frozen_now(),
    )
    assert "health" not in without_health["servers"]["trivago"]["dev"]


def test_update_self_hosted_requires_health():
    """Defense in depth: callers should not be able to write a Shape 1
    entry without a /healthz URL — the gateway would probe it and 404."""
    with pytest.raises(
        reg.EndpointRegistryError,
        match="health is required for shape=self_hosted",
    ):
        reg.update(
            reg.empty_registry(),
            server="duffel",
            env="dev",
            mcp_url="http://x/mcp",
            shape="self_hosted",
            now=_frozen_now(),
        )


def test_update_rejects_unknown_shape():
    with pytest.raises(reg.EndpointRegistryError, match="shape must be one of"):
        reg.update(
            reg.empty_registry(),
            server="bogus",
            env="dev",
            mcp_url="https://x/mcp",
            shape="edge_case_mcp",
            now=_frozen_now(),
        )


def test_update_rejects_bad_transport():
    with pytest.raises(reg.EndpointRegistryError, match="transport must be one of"):
        reg.update(
            reg.empty_registry(),
            server="trivago",
            env="dev",
            mcp_url="https://mcp.trivago.com/mcp",
            shape="remote_mcp",
            transport="grpc",
            now=_frozen_now(),
        )


def test_validate_loads_remote_mcp_yaml(tmp_path):
    """End-to-end: write a Shape 2 entry via YAML, load it, round-trip."""
    p = tmp_path / "endpoints.yaml"
    p.write_text(
        "servers:\n"
        "  trivago:\n"
        "    dev:\n"
        "      shape: remote_mcp\n"
        "      transport: streamable-http\n"
        "      mcp_url: https://mcp.trivago.com/mcp\n"
        "      last_deployed: 2026-06-23T20:35:12Z\n"
    )
    data = reg.load(p)
    assert data["servers"]["trivago"]["dev"]["shape"] == "remote_mcp"
    assert data["servers"]["trivago"]["dev"]["mcp_url"] == "https://mcp.trivago.com/mcp"


def test_validate_remote_mcp_rejects_health_must_be_url(tmp_path):
    """If a Shape 2 entry carries a health URL, it must parse."""
    p = tmp_path / "bad.yaml"
    p.write_text(
        "servers:\n"
        "  trivago:\n"
        "    dev:\n"
        "      shape: remote_mcp\n"
        "      mcp_url: https://mcp.trivago.com/mcp\n"
        "      health: 'not-a-url'\n"
        "      last_deployed: 2026-06-23T20:35:12Z\n"
    )
    with pytest.raises(reg.EndpointRegistryError, match=r"\.health is not a valid URL"):
        reg.load(p)


def test_validate_rejects_entry_without_shape(tmp_path):
    """shape is mandatory on every entry — there is no implicit default.
    Misclassifying a Shape 2 entry as Shape 1 would have the gateway
    probe a vendor-controlled /healthz that doesn't exist."""
    p = tmp_path / "bad.yaml"
    p.write_text(
        "servers:\n"
        "  trivago:\n"
        "    dev:\n"
        "      mcp_url: https://mcp.trivago.com/mcp\n"
        "      last_deployed: 2026-06-23T20:35:12Z\n"
    )
    with pytest.raises(reg.EndpointRegistryError, match="missing required key 'shape'"):
        reg.load(p)


def test_dump_then_load_remote_mcp_round_trip(tmp_path):
    """Write via update(), reload via load(), assert equal."""
    p = tmp_path / "endpoints.yaml"
    data = reg.update(
        reg.empty_registry(),
        server="trivago",
        env="dev",
        mcp_url="https://mcp.trivago.com/mcp",
        shape="remote_mcp",
        transport="streamable-http",
        last_run="https://github.com/DarojaAI/mcp-tooling/actions/runs/1",
        now=_frozen_now(),
    )
    reg.write(p, data)
    reloaded = reg.load(p)
    assert reloaded == data


# ---------------------------------------------------------------------------
# print-endpoint.py CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def registry_file(tmp_path) -> Path:
    p = tmp_path / "endpoints.yaml"
    data = reg.update(
        reg.empty_registry(),
        server="duffel",
        env="dev",
        mcp_url="http://203.0.113.10:8765/mcp",
        health="http://203.0.113.10:8765/healthz",
        last_run="https://github.com/DarojaAI/mcp-tooling/actions/runs/1",
        now=_frozen_now(),
    )
    data = reg.update(
        data,
        shape="self_hosted",
        server="google-workspace",
        env="dev",
        mcp_url="http://203.0.113.20:8766/mcp",
        health="http://203.0.113.20:8766/healthz",
        now=_frozen_now(),
    )
    reg.write(p, data)
    return p


def _run_cli(*args: str, path: Path) -> subprocess.CompletedProcess:
    """Run scripts/ci/print-endpoint.py as a subprocess."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "print-endpoint.py"
    return subprocess.run(
        [sys.executable, str(script), "--path", str(path), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_prints_full_registry_by_default(registry_file):
    res = _run_cli(path=registry_file)
    assert res.returncode == 0
    assert "duffel" in res.stdout
    assert "google-workspace" in res.stdout
    assert "mcp_url: http://203.0.113.10:8765/mcp" in res.stdout


def test_cli_prints_single_field(registry_file):
    res = _run_cli("--server", "google-workspace", "--env", "dev", "--field", "mcp_url", path=registry_file)
    assert res.returncode == 0
    assert res.stdout.strip() == "http://203.0.113.20:8766/mcp"


def test_cli_prints_full_entry(registry_file):
    res = _run_cli("--server", "google-workspace", "--env", "dev", path=registry_file)
    assert res.returncode == 0
    assert "google-workspace / dev:" in res.stdout
    assert "mcp_url: http://203.0.113.20:8766/mcp" in res.stdout
    assert "health: http://203.0.113.20:8766/healthz" in res.stdout
    assert "last_deployed: 2026-06-23T20:35:12Z" in res.stdout


def test_cli_list_servers(registry_file):
    res = _run_cli("--list-servers", path=registry_file)
    assert res.returncode == 0
    assert res.stdout.splitlines() == ["duffel", "google-workspace"]


def test_cli_list_servers_json(registry_file):
    res = _run_cli("--list-servers", "--json", path=registry_file)
    assert res.returncode == 0
    assert json.loads(res.stdout) == ["duffel", "google-workspace"]


def test_cli_list_envs_for_server(registry_file):
    res = _run_cli("--server", "duffel", "--list-envs", path=registry_file)
    assert res.returncode == 0
    assert res.stdout.splitlines() == ["dev"]


def test_cli_missing_entry_exits_2(registry_file):
    res = _run_cli("--server", "duffel", "--env", "prod", "--field", "mcp_url", path=registry_file)
    assert res.returncode == 2
    assert "no entry" in res.stderr


def test_cli_missing_file_treated_as_empty_registry(tmp_path):
    """No file on disk yet — the registry is empty but the command succeeds."""
    res = _run_cli("--list-servers", path=tmp_path / "nope.yaml")
    assert res.returncode == 0
    assert res.stdout == ""


def test_cli_unparseable_file_exits_3(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("not: [valid")
    res = _run_cli(path=p)
    assert res.returncode == 3
    assert "failed to parse" in res.stderr


def test_cli_field_requires_env(registry_file):
    res = _run_cli("--server", "duffel", "--field", "mcp_url", path=registry_file)
    assert res.returncode != 0
    assert "--field requires --env" in res.stderr


def test_cli_env_requires_server(registry_file):
    res = _run_cli("--env", "dev", path=registry_file)
    assert res.returncode != 0
    assert "--env/--field require --server" in res.stderr


def test_cli_list_envs_requires_server(registry_file):
    res = _run_cli("--list-envs", path=registry_file)
    assert res.returncode != 0
    assert "--list-envs requires --server" in res.stderr


# ---------------------------------------------------------------------------
# format_entry
# ---------------------------------------------------------------------------


def test_format_entry_orders_keys_canonically():
    entry = {
        "last_run": "http://x/run",
        "shape": "self_hosted",
        "mcp_url": "http://x/mcp",
        "last_deployed": "2026-06-23T20:35:12Z",
        "health": "http://x/healthz",
    }
    out = reg.format_entry(entry)
    # mcp_url comes first regardless of input dict order.
    assert out.index("mcp_url:") < out.index("health:") < out.index("last_deployed:") < out.index("last_run:")


def test_format_entry_empty():
    assert reg.format_entry({}) == "(no entry)"


def test_format_entry_skips_missing_keys():
    entry = {"mcp_url": "http://x/mcp"}
    out = reg.format_entry(entry)
    assert "mcp_url: http://x/mcp" in out
    assert "health" not in out
    assert "last_deployed" not in out


# ---------------------------------------------------------------------------
# Concurrency safety net — manual merge test
# ---------------------------------------------------------------------------


def test_concurrent_deploys_dont_clobber_each_other():
    """Simulate two deploys landing in quick succession on different
    (server, env) keys. The final state must contain both — the merge
    logic in `update` reads the existing registry, not just overwrites it.

    This is the case that drove the whole registry: the deploy workflow's
    `endpoint-manifest` job updates the file via git, and a second
    concurrent deploy reading the same on-disk file must not lose the
    first deploy's entry.
    """
    # Pretend the on-disk registry starts at one entry.
    on_disk_text = reg.dump(
        reg.update(
            reg.empty_registry(),
            server="duffel",
            env="dev",
            mcp_url="http://203.0.113.10:8765/mcp",
            health="http://203.0.113.10:8765/healthz",
            now=_frozen_now(),
        )
    )

    # Two workflows start in parallel; both read the same on-disk text.
    snapshot_a = reg.loads(on_disk_text)
    snapshot_b = reg.loads(on_disk_text)

    # Workflow A updates google-workspace/dev.
    snapshot_a = reg.update(
        snapshot_a,
        server="google-workspace",
        env="dev",
        mcp_url="http://203.0.113.20:8766/mcp",
        health="http://203.0.113.20:8766/healthz",
        now=_frozen_now(),
    )
    # Workflow B updates duffel/prod.
    snapshot_b = reg.update(
        snapshot_b,
        server="duffel",
        env="prod",
        mcp_url="http://198.51.100.5:8765/mcp",
        health="http://198.51.100.5:8765/healthz",
        now=_frozen_now(),
    )

    # The "winner" pushes its snapshot. The "loser" then re-reads,
    # merges on top, and pushes again. (This is what the deploy workflow
    # does — it pulls main, runs update, opens a PR; if it loses the
    # race it retries.)
    final = reg.loads(reg.dump(snapshot_a))
    final = reg.update(
        final,
        server="duffel",
        env="prod",
        mcp_url="http://198.51.100.5:8765/mcp",
        health="http://198.51.100.5:8765/healthz",
        now=_frozen_now(),
    )

    assert reg.get(final, "duffel", "dev")["mcp_url"] == "http://203.0.113.10:8765/mcp"
    assert reg.get(final, "google-workspace", "dev")["mcp_url"] == "http://203.0.113.20:8766/mcp"
    assert reg.get(final, "duffel", "prod")["mcp_url"] == "http://198.51.100.5:8765/mcp"


# ---------------------------------------------------------------------------
# Sanity: the committed config/endpoints.yaml parses cleanly.
# ---------------------------------------------------------------------------


def test_committed_endpoints_yaml_is_loadable():
    """If anyone hand-edits config/endpoints.yaml and breaks it, this test
    fails in CI before the bad commit lands on main.
    """
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "config" / "endpoints.yaml"
    if not path.exists():
        pytest.skip("config/endpoints.yaml not present (expected after first deploy)")
    data = reg.load(path)
    # Whatever's there must validate.
    assert isinstance(data.get("servers"), dict)