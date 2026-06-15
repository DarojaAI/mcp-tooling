#!/usr/bin/env python3
"""
Generate docs/github-actions-secrets.md from config/dat-contract.yaml.

This script reads the data contract and emits a human-readable reference doc
for GitHub Actions environment variables. The Secrets section is hand-written
(see docs/secrets-section.md) and copied in verbatim — we intentionally do not
parse the `secrets` block of the contract, because reading any value reachable
from a "secrets" key in YAML trips CodeQL's clear-text-storage-sensitive-data
alert and produces false-positives on documentation generation.
"""

import sys
from pathlib import Path

import yaml


SECRETS_SECTION_PATH = Path("docs/secrets-section.md")


def main():
    contract_path = Path("config/dat-contract.yaml")
    output_path = Path("docs/github-actions-secrets.md")

    if not contract_path.exists():
        print(f"Error: {contract_path} not found", file=sys.stderr)
        sys.exit(1)

    if not SECRETS_SECTION_PATH.exists():
        print(
            f"Error: {SECRETS_SECTION_PATH} not found. "
            "This file is hand-maintained; see scripts/ci/README.md.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(contract_path) as f:
        contract = yaml.safe_load(f)

    lines = [
        "# GitHub Actions Environment Variables and Secrets",
        "",
        "**Auto-generated from `config/dat-contract.yaml`**",
        "",
        "This document lists all environment variables and secrets required by mcp-tooling's GitHub Actions workflows.",
        "",
        "## Environment Variables",
        "",
        "Set these in: **Settings → Environments → `<environment>` → Environment variables**",
        "",
        "| Variable | Description | Required | Default |",
        "|----------|-------------|----------|---------|",
    ]

    for _key, spec in contract.get("deploy_env_vars", {}).items():
        var_name = spec["github_var"]
        desc = spec["description"]
        required = "✅" if spec.get("required", False) else "❌"
        default = spec.get("default", "—")
        lines.append(f"| `{var_name}` | {desc} | {required} | `{default}` |")

    lines.append("")
    lines.append("## Secrets")
    lines.append("")
    lines.append(
        "> The Secrets section is hand-maintained in `docs/secrets-section.md` "
        "and copied into this doc by `scripts/ci/generate-secrets-doc.py`. "
        "It is not auto-generated from the contract because CodeQL's "
        "clear-text-storage-sensitive-data alert flags any code that reads "
        "values from a `secrets:` block, even when those values are *names* "
        "not *values*."
    )
    lines.append("")

    with open(SECRETS_SECTION_PATH) as f:
        secrets_md = f.read().rstrip("\n")
    lines.append(secrets_md)

    lines.extend([
        "",
        "---",
        "",
        "**Note:** If you add/remove entries in `config/dat-contract.yaml`'s `deploy_env_vars` "
        "block, regenerate this doc:",
        "",
        "```bash",
        "python3 scripts/ci/generate-secrets-doc.py",
        "```",
    ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n")
    print(f"✅ Generated {output_path}")


if __name__ == "__main__":
    main()
