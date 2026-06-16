#!/usr/bin/env python3
"""
Validate that GitHub Actions workflows comply with config/dat-contract.yaml.

This script:
1. Parses all .github/workflows/*.yml files
2. Extracts vars.* and secrets.* references
3. Cross-checks against config/dat-contract.yaml
4. Fails if:
   - Workflow uses a var/secret not in the contract
   - Contract lists a required var/secret not used by any workflow
"""

import re
import sys
from pathlib import Path

import yaml


def extract_refs_from_workflow(content: str) -> tuple[set[str], set[str]]:
    """Extract vars.X and secrets.Y references from workflow YAML."""
    var_pattern = re.compile(r'\$\{\{\s*vars\.([A-Z_]+)\s*\}\}')
    secret_pattern = re.compile(r'\$\{\{\s*secrets\.([A-Z_]+)\s*\}\}')

    vars_used = set(var_pattern.findall(content))
    secrets_used = set(secret_pattern.findall(content))

    return vars_used, secrets_used

def main():
    contract_path = Path("config/dat-contract.yaml")
    workflows_dir = Path(".github/workflows")

    if not contract_path.exists():
        print(f"❌ {contract_path} not found", file=sys.stderr)
        sys.exit(1)

    if not workflows_dir.exists():
        print("⚠️  No workflows directory found, skipping validation")
        sys.exit(0)

    # Load contract
    with open(contract_path) as f:
        contract = yaml.safe_load(f)

    contract_vars = {spec["github_var"] for spec in contract.get("deploy_env_vars", {}).values()}
    contract_secrets = {spec["github_secret"] for spec in contract.get("secrets", {}).values()}

    required_vars = {
        spec["github_var"]
        for spec in contract.get("deploy_env_vars", {}).values()
        if spec.get("required", False)
    }
    required_secrets = {
        spec["github_secret"]
        for spec in contract.get("secrets", {}).values()
        if spec.get("required", False)
    }

    # Scan all workflows
    all_vars_used = set()
    all_secrets_used = set()

    for workflow_file in workflows_dir.glob("*.yml"):
        content = workflow_file.read_text()
        vars_used, secrets_used = extract_refs_from_workflow(content)
        all_vars_used.update(vars_used)
        all_secrets_used.update(secrets_used)

    # Built-in GitHub Actions secrets that workflows can reference without
    # declaring them in the contract (they're auto-injected by GitHub).
    BUILTIN_SECRETS = {"GITHUB_TOKEN"}

    # Check for violations
    errors = []

    # Violation 1: workflow uses undeclared var/secret
    undeclared_vars = all_vars_used - contract_vars
    undeclared_secrets = all_secrets_used - contract_secrets - BUILTIN_SECRETS

    if undeclared_vars:
        errors.append(f"❌ Workflows use undeclared vars: {', '.join(sorted(undeclared_vars))}")

    if undeclared_secrets:
        errors.append(f"❌ Workflows use undeclared secrets: {', '.join(sorted(undeclared_secrets))}")

    # Violation 2: contract declares required var/secret but no workflow uses it
    unused_required_vars = required_vars - all_vars_used
    unused_required_secrets = required_secrets - all_secrets_used

    if unused_required_vars:
        errors.append(f"⚠️  Contract declares required vars not used by workflows: {', '.join(sorted(unused_required_vars))}")

    if unused_required_secrets:
        errors.append(f"⚠️  Contract declares required secrets not used by workflows: {', '.join(sorted(unused_required_secrets))}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)

    print("✅ Workflow contract validation passed")
    print(f"   Vars used: {len(all_vars_used)}, Secrets used: {len(all_secrets_used)}")

if __name__ == "__main__":
    main()
