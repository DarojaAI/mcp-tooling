"""Static endpoint registry — read/update helpers for config/endpoints.yaml.

Why this exists
---------------
PR #49 publishes MCP endpoint URLs as workflow artifacts (fetched via the
GitHub REST API). That's good for "where is the server right now" queries
but a poor fit for:

- Offline / isolated-network clients that can't reach GitHub.
- Local dev (no terraform state applied yet).
- Humans debugging "what servers does this repo expose?".

`config/endpoints.yaml` is the complement: a checked-in file the deploy
workflow updates after each `deploy-mcp-server.yml` run. Two-tier
discovery:

  artifact  -> time-sensitive, per-run, requires GitHub auth
  file      -> stable, in-repo, no auth

Shape (top of file is a comment):

    servers:
      <server_name>:
        <env_name>:
          mcp_url: http://<ipv4>:<port>/mcp
          health: http://<ipv4>:<port>/healthz
          last_deployed: 2026-06-23T20:35:12Z
          last_run: <url-to-workflow-run>

Two-server example (also tests/ci/test_endpoint_registry.py::test_example):

    servers:
      duffel:
        dev:
          mcp_url: http://203.0.113.10:8765/mcp
          health: http://203.0.113.10:8765/healthz
          last_deployed: 2026-06-23T20:35:12Z
          last_run: https://github.com/DarojaAI/mcp-tooling/actions/runs/12345
      google-workspace:
        dev:
          mcp_url: http://203.0.113.20:8766/mcp
          health: http://203.0.113.20:8766/healthz
          last_deployed: 2026-06-23T20:40:01Z
          last_run: https://github.com/DarojaAI/mcp-tooling/actions/runs/12346
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Header that goes above the YAML payload in the file. The header is what
# humans read first; keep it informative and stable.
FILE_HEADER = """\
# mcp-tooling - MCP endpoint registry
# =============================================================================
# Static discovery complement to the workflow-artifact mechanism in
# docs/integrations/mcp-endpoint-discovery.md. Each (server, env) entry
# is updated by .github/workflows/deploy-mcp-server.yml's
# endpoint-manifest job after a successful deploy.
#
# This file is auto-generated. Do not edit by hand — open an issue if
# a key is wrong or stale.
# =============================================================================

"""

# Canonical key ordering. Anything else gets sorted alphabetically after.
KEY_ORDER = ("mcp_url", "health", "last_deployed", "last_run")

# Schema validation per (server, env) entry.
_REQUIRED_KEYS = {"mcp_url", "health", "last_deployed"}
_ALLOWED_KEYS = set(KEY_ORDER)

# Sanity constraints for the values we accept.
_URL_RE = re.compile(r"^https?://[^\s]+$")
_ISO_8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class EndpointRegistryError(ValueError):
    """Raised when an endpoint entry fails validation or the file is malformed."""


def empty_registry() -> dict[str, Any]:
    """Return a fresh in-memory registry with the top-level `servers` key."""
    return {"servers": {}}


def load(path: str | Path) -> dict[str, Any]:
    """Load a registry from disk. Returns an empty registry if the file
    doesn't exist yet. Raises EndpointRegistryError on parse / schema errors.
    """
    p = Path(path)
    if not p.exists():
        return empty_registry()
    text = p.read_text()
    if not text.strip():
        return empty_registry()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise EndpointRegistryError(f"failed to parse {path}: {exc}") from exc
    return _normalize_loaded(data, source=str(p))


def loads(text: str) -> dict[str, Any]:
    """Load a registry from a YAML string. Useful for tests + JSON-driven updates."""
    if not text.strip():
        return empty_registry()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise EndpointRegistryError(f"failed to parse YAML: {exc}") from exc
    return _normalize_loaded(data, source="<string>")


def dump(data: dict[str, Any]) -> str:
    """Render a registry as a YAML string with the standard file header.

    Timestamps are forced into single-quoted string form so re-loading
    the file always produces strings (not datetime objects). Without
    the quoting, PyYAML's safe_load would re-parse them as datetimes
    on every load, and round-trip tests would see type drift.
    """
    _validate(data)
    body = yaml.safe_dump(
        data,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return FILE_HEADER + body


def write(path: str | Path, data: dict[str, Any]) -> None:
    """Validate + render + write. Atomic via a tmp file + rename."""
    _validate(data)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(dump(data))
    tmp.replace(p)


def update(
    data: dict[str, Any],
    *,
    server: str,
    env: str,
    mcp_url: str,
    health: str,
    last_run: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Insert or update one (server, env) entry. Returns a new dict (the
    input is not mutated). Existing entries for other (server, env) pairs
    are preserved unchanged.
    """
    _validate_name(server, "server")
    _validate_name(env, "env")
    if not _URL_RE.match(mcp_url):
        raise EndpointRegistryError(f"mcp_url is not a valid http(s) URL: {mcp_url!r}")
    if not _URL_RE.match(health):
        raise EndpointRegistryError(f"health is not a valid http(s) URL: {health!r}")

    # `timezone.utc` (not `datetime.UTC`) so we stay 3.10-compatible.
    timestamp = (now or datetime.now(timezone.utc)).strftime(  # noqa: UP017
        "%Y-%m-%dT%H:%M:%SZ"
    )
    if not _ISO_8601_RE.match(timestamp):
        # Sanity — should always match because of strftime above, but assert
        # anyway so future format tweaks can't silently break the contract.
        raise EndpointRegistryError(f"timestamp {timestamp!r} is not ISO-8601 'Z'")

    new_entry = {
        "mcp_url": mcp_url,
        "health": health,
        "last_deployed": timestamp,
    }
    if last_run is not None:
        if not _URL_RE.match(last_run):
            raise EndpointRegistryError(f"last_run is not a valid http(s) URL: {last_run!r}")
        new_entry["last_run"] = last_run

    # Deep-copy via round-trip; the registry is small enough that this is
    # cheaper than copying manually, and it normalizes shape (drops None
    # values, sorts keys inside the dict if sort_keys below ever changes).
    base = yaml.safe_load(yaml.safe_dump(data)) if data else empty_registry()
    servers = base.setdefault("servers", {})
    server_bucket = servers.setdefault(server, {})
    server_bucket[env] = new_entry

    _validate(base)
    return base


def get(data: dict[str, Any], server: str, env: str) -> dict[str, Any]:
    """Read a single (server, env) entry. Returns {} if missing.

    Does not raise on missing keys; that's a convenience for the CLI
    (`print-endpoint.py` exits 0 with a friendly message instead of
    crashing when an entry doesn't exist).
    """
    return data.get("servers", {}).get(server, {}).get(env, {})


def list_servers(data: dict[str, Any]) -> list[str]:
    return sorted(data.get("servers", {}).keys())


def list_envs(data: dict[str, Any], server: str) -> list[str]:
    return sorted(data.get("servers", {}).get(server, {}).keys())


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _normalize_loaded(data: Any, *, source: str) -> dict[str, Any]:
    """Coerce a freshly-loaded YAML document into the canonical registry shape.

    Side effect: timestamps that PyYAML parsed as datetime.datetime
    objects (because they were unquoted in the YAML) are converted back
    to strings in canonical 'Z' form, so downstream validation and JSON
    consumers see the same shape regardless of how the file was written.
    """
    if data is None:
        return empty_registry()
    if not isinstance(data, dict):
        raise EndpointRegistryError(
            f"{source}: top-level must be a mapping, got {type(data).__name__}"
        )
    if "servers" not in data:
        # Tolerate a near-empty file that loaded as {}.
        data = {"servers": {}}
    if not isinstance(data["servers"], dict):
        raise EndpointRegistryError(
            f"{source}: 'servers' must be a mapping, got {type(data['servers']).__name__}"
        )
    _coerce_timestamps_in_place(data["servers"])
    _validate(data, source=source)
    return data


def _coerce_timestamps_in_place(servers: dict[str, Any]) -> None:
    """Walk servers[*][*].last_deployed and coerce datetime -> ISO 'Z' string.

    PyYAML's safe loader returns `datetime.datetime` for unquoted
    ISO-8601 timestamps like `last_deployed: 2026-06-23T20:35:12Z`.
    We always render them as strings (the canonical form) so the rest
    of the library can treat them uniformly.
    """
    from datetime import datetime as _dt

    for _server, envs in servers.items():
        if not isinstance(envs, dict):
            continue
        for _env, entry in envs.items():
            if not isinstance(entry, dict):
                continue
            ts = entry.get("last_deployed")
            if isinstance(ts, _dt):
                # Drop tz info we don't need; render as canonical 'Z' form.
                entry["last_deployed"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate(data: dict[str, Any], *, source: str = "<registry>") -> None:
    """Schema-check the registry. Raises EndpointRegistryError on the first failure."""
    if not isinstance(data, dict):
        raise EndpointRegistryError(f"{source}: top-level must be a mapping")
    servers = data.get("servers")
    if not isinstance(servers, dict):
        raise EndpointRegistryError(f"{source}: 'servers' must be a mapping")
    for server, envs in servers.items():
        _validate_name(server, "server")
        if not isinstance(envs, dict):
            raise EndpointRegistryError(
                f"{source}: servers[{server!r}] must be a mapping, got {type(envs).__name__}"
            )
        for env, entry in envs.items():
            _validate_name(env, "env")
            if not isinstance(entry, dict):
                raise EndpointRegistryError(
                    f"{source}: servers[{server!r}][{env!r}] must be a mapping"
                )
            missing = _REQUIRED_KEYS - entry.keys()
            if missing:
                raise EndpointRegistryError(
                    f"{source}: servers[{server!r}][{env!r}] missing keys: {sorted(missing)}"
                )
            extra = set(entry.keys()) - _ALLOWED_KEYS
            if extra:
                raise EndpointRegistryError(
                    f"{source}: servers[{server!r}][{env!r}] has unknown keys: {sorted(extra)}"
                )
            if not _URL_RE.match(entry["mcp_url"]):
                raise EndpointRegistryError(
                    f"{source}: servers[{server!r}][{env!r}].mcp_url is not a valid URL"
                )
            if not _URL_RE.match(entry["health"]):
                raise EndpointRegistryError(
                    f"{source}: servers[{server!r}][{env!r}].health is not a valid URL"
                )
            # last_deployed may be either a string or a datetime that
            # _coerce_timestamps_in_place hasn't seen yet (e.g. when
            # _validate is called directly). Compare against the string
            # form.
            from datetime import datetime as _dt

            ts = entry["last_deployed"]
            ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(ts, _dt) else ts
            if not _ISO_8601_RE.match(ts_str):
                raise EndpointRegistryError(
                    f"{source}: servers[{server!r}][{env!r}].last_deployed must be ISO-8601 'Z' format"
                )
            if "last_run" in entry and not _URL_RE.match(entry["last_run"]):
                raise EndpointRegistryError(
                    f"{source}: servers[{server!r}][{env!r}].last_run is not a valid URL"
                )


_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _validate_name(value: str, kind: str) -> None:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise EndpointRegistryError(
            f"{kind} name must match {_NAME_RE.pattern!r}; got {value!r}"
        )


# ---------------------------------------------------------------------------
# Convenience: pretty-printer used by print-endpoint.py + tests.
# ---------------------------------------------------------------------------


def format_entry(entry: dict[str, Any]) -> str:
    """Render a single entry for terminal output."""
    if not entry:
        return "(no entry)"
    out = io.StringIO()
    for key in KEY_ORDER:
        if key in entry:
            out.write(f"  {key}: {entry[key]}\n")
    return out.getvalue().rstrip()


__all__ = [
    "EndpointRegistryError",
    "FILE_HEADER",
    "KEY_ORDER",
    "dump",
    "empty_registry",
    "format_entry",
    "get",
    "list_envs",
    "list_servers",
    "load",
    "loads",
    "update",
    "write",
]