#!/usr/bin/env python3
"""
Generate docs/github-actions-secrets.md from config/dat-contract.yaml.

This script reads the data contract and emits a human-readable reference doc
for GitHub Actions environment variables and secrets.
"""

import sys
from pathlib import Path
import yaml

def main():
    contract_path = Path("config/dat-contract.yaml")
    output_path = Path("docs/github-actions-secrets.md")
    
    if not contract_path.exists():
        print(f"Error: {contract_path} not found", file=sys.stderr)
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
    
    for key, spec in contract.get("deploy_env_vars", {}).items():
        var_name = spec["github_var"]
        desc = spec["description"]
        required = "✅" if spec.get("required", False) else "❌"
        default = spec.get("default", "—")
        lines.append(f"| `{var_name}` | {desc} | {required} | `{default}` |")
    
    lines.extend([
        "",
        "## Secrets",
        "",
        "Set these in: **Settings → Secrets and variables → Actions → Repository secrets**",
        "",
        "| Secret | Description | Required |",
        "|--------|-------------|----------|",
    ])
    
    for key, spec in contract.get("secrets", {}).items():
        secret_name = spec["github_secret"]
        desc = spec["description"]
        required = "✅" if spec.get("required", False) else "❌"
        lines.append(f"| `{secret_name}` | {desc} | {required} |")
    
    lines.extend([
        "",
        "---",
        "",
        "**Note:** If you add/remove entries in `config/dat-contract.yaml`, regenerate this doc:",
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
