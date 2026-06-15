#!/usr/bin/env python3
"""
Contract check: every KEY=... line in the .env body must be referenced
in the systemd service file (either as EnvironmentFile or as Environment=KEY=...)

Imported from twentycrm-management PR#XXX on 2026-06-13, adapted for systemd units.
Original checked docker-compose.yml; this version checks systemd service files.

Usage:
    python3 runtime/dotenv_contract.py <dotenv-file> <systemd-unit-file>

Exits 0 if every .env key is referenced, 1 otherwise.
"""

import re
import sys


def extract_env_keys(dotenv_text: str) -> set[str]:
    """Return the set of keys (KEY, before '=') from the .env body."""
    return set(re.findall(r"^([A-Z_][A-Z0-9_]*)\s*=", dotenv_text, re.MULTILINE))


def extract_systemd_refs(unit_text: str) -> set[str]:
    """
    Return the set of env-var names referenced in the systemd unit file.
    
    Two reference styles count:
    - EnvironmentFile=/path/to/file (loads all vars from that file)
    - Environment=KEY=value (explicit inline)
    
    If EnvironmentFile is present, we assume all vars are loaded (return None = skip check).
    """
    # Check for EnvironmentFile directive
    if re.search(r"^\s*EnvironmentFile\s*=", unit_text, re.MULTILINE):
        # EnvironmentFile present = all vars loaded, skip per-key validation
        return None
    
    # Extract inline Environment= directives
    refs = set(re.findall(r"^\s*Environment\s*=\s*([A-Z_][A-Z0-9_]*)\s*=", unit_text, re.MULTILINE))
    return refs


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <dotenv-file> <systemd-unit-file>", file=sys.stderr)
        return 2

    dotenv_path, unit_path = sys.argv[1], sys.argv[2]

    with open(dotenv_path) as f:
        env_text = f.read()
    with open(unit_path) as f:
        unit_text = f.read()

    env_keys = extract_env_keys(env_text)
    systemd_refs = extract_systemd_refs(unit_text)

    print(f"[CONTRACT] .env keys ({len(env_keys)} total):")
    for k in sorted(env_keys):
        print(f"  - {k}")

    if systemd_refs is None:
        print("[CONTRACT] systemd unit has EnvironmentFile= directive (all vars loaded automatically)")
        print("[CONTRACT] OK: skipping per-key validation")
        return 0

    print(f"[CONTRACT] systemd inline Environment= references ({len(systemd_refs)} unique):")
    for k in sorted(systemd_refs):
        print(f"  - {k}")

    missing = sorted(env_keys - systemd_refs)
    if missing:
        print(f"[CONTRACT] FAIL: {len(missing)} .env key(s) not referenced in systemd unit:")
        for k in missing:
            print(f"  - {k}")
        return 1

    print(f"[CONTRACT] OK: all {len(env_keys)} .env keys are referenced in systemd unit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
