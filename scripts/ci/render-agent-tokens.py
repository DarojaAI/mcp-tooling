#!/usr/bin/env python3
"""
Render per-agent bearer tokens for the mcp-tooling MCP server.

For each agent in MCPTOOLING_AGENT_BINDINGS_JSON, derive a deterministic
bearer token via HMAC-SHA256(MCPTOOLING_AGENT_TOKEN_SALT, "<server>:<agent>")
and emit two artifacts:

  1. The merged MCPTOOLING_ALLOWED_TOKENS value
     (= existing global tokens + comma-joined per-agent tokens).
     This replaces the raw MCPTOOLING_ALLOWED_TOKENS secret so the
     server-side allowlist includes every agent's token.

  2. A JSON map of {"agent_id": "token"} so the consumer (linux-desktop-seed
     gateway) can pull it from a workflow artifact and write per-agent
     Authorization values into each agent's openclaw config.

The tokens are deterministic: same salt + same binding = same token.
No random per-deploy values, no need to persist per-agent tokens in
GitHub secrets.

Usage (in GitHub Actions):

    env:
      MCPTOOLING_AGENT_TOKEN_SALT: ${{ secrets.MCPTOOLING_AGENT_TOKEN_SALT }}
      MCPTOOLING_AGENT_BINDINGS_JSON: ${{ vars.MCPTOOLING_AGENT_BINDINGS_JSON }}
      MCPTOOLING_ALLOWED_TOKENS: ${{ secrets.MCPTOOLING_ALLOWED_TOKENS }}
    run: |
      python3 scripts/ci/render-agent-tokens.py \
        --out-merged-env  >> "$GITHUB_ENV" \
        --out-agent-json  agent-tokens.json

Exit codes:
  0 - success
  1 - missing required env var
  2 - invalid JSON in MCPTOOLING_AGENT_BINDINGS_JSON
  3 - empty binding list (no agents defined)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys

REQUIRED_ENV_VARS = (
    "MCPTOOLING_AGENT_TOKEN_SALT",
    "MCPTOOLING_AGENT_BINDINGS_JSON",
)


def _die(msg: str, code: int = 1) -> None:
    print(f"::error::{msg}", file=sys.stderr)
    sys.exit(code)


def _get_env(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        _die(f"required env var {name} is not set")
    return val


def _parse_bindings(raw: str) -> list[dict]:
    """Parse MCPTOOLING_AGENT_BINDINGS_JSON.

    Expected shape (matches linux-desktop-seed PR #908):
      [
        {"agent": "trip_planning", "servers": ["duffel"]},
        {"agent": "*", "servers": ["duffel"]}
      ]

    The "*" entry is a default; it's expanded into a per-server token
    named "<server>_default" so any agent not explicitly listed still
    gets through when it tries that server. This mirrors the "*: [duffel]"
    default the user described in their handoff.
    """
    try:
        bindings = json.loads(raw)
    except json.JSONDecodeError as exc:
        _die(f"MCPTOOLING_AGENT_BINDINGS_JSON is not valid JSON: {exc}", code=2)

    if not isinstance(bindings, list):
        _die(
            "MCPTOOLING_AGENT_BINDINGS_JSON must be a JSON array of "
            '{"agent": "<id>", "servers": ["<server>", ...]} entries',
            code=2,
        )

    for entry in bindings:
        if not isinstance(entry, dict):
            _die(f"binding entry is not an object: {entry!r}", code=2)
        if "agent" not in entry or "servers" not in entry:
            _die(
                f"binding entry missing required keys 'agent'/'servers': {entry!r}",
                code=2,
            )
        if not isinstance(entry["servers"], list):
            _die(f"binding entry 'servers' must be a list: {entry!r}", code=2)

    return bindings


def _agent_keys(bindings: list[dict]) -> list[tuple[str, str]]:
    """Expand bindings into (agent_id, server_id) pairs to mint tokens for.

    For {"agent": "trip_planning", "servers": ["duffel"]} -> one key.
    For {"agent": "*",            "servers": ["duffel"]} -> one key named
        "<server>_default" so the gateway can use a single shared token for
        any agent that doesn't have its own binding.
    """
    pairs: list[tuple[str, str]] = []
    for entry in bindings:
        agent = entry["agent"]
        for server in entry["servers"]:
            if agent == "*":
                pairs.append((f"{server}_default", server))
            else:
                pairs.append((agent, server))
    # Deduplicate while preserving order (same binding twice shouldn't
    # mint the same token twice and bloat MCPTOOLING_ALLOWED_TOKENS).
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for pair in pairs:
        if pair not in seen:
            seen.add(pair)
            deduped.append(pair)
    return deduped


def _mint_token(salt: str, server: str, agent: str) -> str:
    """Deterministic HMAC-SHA256 token for a (server, agent) pair."""
    msg = f"{server}:{agent}".encode()
    digest = hmac.new(salt.encode(), msg, hashlib.sha256).hexdigest()
    # Prefix so the token is recognizable in logs as a derived agent token
    # (vs. a human-minted global one).
    return f"ag_{digest}"


def _existing_tokens(raw: str) -> set[str]:
    return {t.strip() for t in raw.split(",") if t.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-merged-env",
        action="store_true",
        help="Emit `export MCPTOOLING_ALLOWED_TOKENS=...` lines to stdout "
             "(intended for >> $GITHUB_ENV).",
    )
    parser.add_argument(
        "--out-agent-json",
        metavar="PATH",
        help="Write the per-agent token map as JSON to PATH. Use the server "
             "name as the key so the gateway knows which MCP server each "
             "token is for.",
    )
    args = parser.parse_args()

    salt = _get_env("MCPTOOLING_AGENT_TOKEN_SALT")
    bindings_raw = _get_env("MCPTOOLING_AGENT_BINDINGS_JSON")
    existing_raw = os.environ.get("MCPTOOLING_ALLOWED_TOKENS", "")

    bindings = _parse_bindings(bindings_raw)
    keys = _agent_keys(bindings)
    if not keys:
        _die("MCPTOOLING_AGENT_BINDINGS_JSON yielded zero agent/server pairs", code=3)

    # Server -> {agent: token} map (the artifact shape the gateway wants).
    server_to_agents: dict[str, dict[str, str]] = {}
    for agent, server in keys:
        token = _mint_token(salt, server, agent)
        server_to_agents.setdefault(server, {})[agent] = token

    # Flat map {f"{server}:{agent}": token} for the merged env var.
    # We keep the existing global tokens untouched (they may include
    # hand-minted keys for tools outside the agent-binding world).
    new_tokens: list[str] = []
    for _server, agents in server_to_agents.items():
        for _agent, token in agents.items():
            new_tokens.append(token)

    existing = _existing_tokens(existing_raw)
    # Avoid clobbering an existing global token if it happens to collide
    # with an agent-derived one (extremely unlikely given the HMAC
    # domain, but defensive).
    for tok in new_tokens:
        if tok in existing:
            print(
                f"::warning::derived token {tok[:10]}... already present in "
                "MCPTOOLING_ALLOWED_TOKENS; skipping (dedup)",
                file=sys.stderr,
            )
    merged = sorted(existing | set(new_tokens))

    if args.out_merged_env:
        # GitHub Actions GITHUB_ENV doesn't support multi-line values
        # directly, but a single long line is fine.
        print(f"MCPTOOLING_ALLOWED_TOKENS={','.join(merged)}")

    if args.out_agent_json:
        with open(args.out_agent_json, "w", encoding="utf-8") as fp:
            json.dump(server_to_agents, fp, indent=2, sort_keys=True)
            fp.write("\n")
        print(
            f"wrote per-agent token map for {len(server_to_agents)} server(s) "
            f"to {args.out_agent_json}",
            file=sys.stderr,
        )

    # Always print a summary to stdout so CI logs are useful.
    print(
        f"rendered {len(new_tokens)} agent token(s) across "
        f"{len(server_to_agents)} server(s); "
        f"merged allowlist size = {len(merged)}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()