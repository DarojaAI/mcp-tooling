#!/usr/bin/env python3
"""Print MCP endpoint info from config/endpoints.yaml.

Companion to scripts/ci/endpoint_registry.py. Used by:

- Humans debugging "where does this server live?"
- The OpenClaw gateway populating per-agent MCP config.
- CI scripts that need a stable URL without re-running terraform.

Usage:

    # Print the full registry as JSON-ish YAML to stdout.
    scripts/ci/print-endpoint.py

    # Print just the mcp_url for one (server, env).
    scripts/ci/print-endpoint.py --server google-workspace --env dev --field mcp_url

    # Print a full entry (mcp_url + health + last_deployed + last_run).
    scripts/ci/print-endpoint.py --server google-workspace --env dev

    # List known servers / envs.
    scripts/ci/print-endpoint.py --list-servers
    scripts/ci/print-endpoint.py --server google-workspace --list-envs

Exit codes:

    0  success (entry or list printed)
    1  bad arguments
    2  entry not found
    3  registry file missing / unparseable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make `import endpoint_registry` work whether the script is run from the
# repo root or from inside scripts/ci/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import endpoint_registry as reg  # noqa: E402

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "endpoints.yaml"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print MCP endpoint info from config/endpoints.yaml.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_PATH,
        help=f"Path to endpoints.yaml (default: {DEFAULT_PATH})",
    )
    parser.add_argument("--server", help="Server name (e.g. google-workspace)")
    parser.add_argument("--env", help="Environment name (e.g. dev, prod)")
    parser.add_argument(
        "--field",
        choices=reg.KEY_ORDER,
        help="Print just one field of the entry instead of the whole record.",
    )
    parser.add_argument("--list-servers", action="store_true", help="List known server names")
    parser.add_argument(
        "--list-envs",
        action="store_true",
        help="List known environments for --server",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of YAML-ish text (for piping).",
    )
    args = parser.parse_args(argv)
    if args.list_envs and not args.server:
        parser.error("--list-envs requires --server")
    if (args.env or args.field) and not args.server:
        parser.error("--env/--field require --server")
    if args.field and not args.env:
        parser.error("--field requires --env")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    try:
        data = reg.load(args.path)
    except reg.EndpointRegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.list_servers:
        servers = reg.list_servers(data)
        if args.json:
            print(json.dumps(servers))
        else:
            for s in servers:
                print(s)
        return 0

    if args.list_envs:
        envs = reg.list_envs(data, args.server)
        if args.json:
            print(json.dumps(envs))
        else:
            for e in envs:
                print(e)
        return 0

    if args.server and args.env:
        entry = reg.get(data, args.server, args.env)
        if not entry:
            print(
                f"error: no entry for server={args.server!r} env={args.env!r} in {args.path}",
                file=sys.stderr,
            )
            return 2
        if args.field:
            value = entry.get(args.field, "")
            if args.json:
                print(json.dumps(value))
            else:
                print(value)
        else:
            if args.json:
                print(json.dumps(entry, indent=2, sort_keys=True))
            else:
                print(f"{args.server} / {args.env}:")
                print(reg.format_entry(entry))
        return 0

    # Default: print the whole registry.
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(reg.dump(data), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())