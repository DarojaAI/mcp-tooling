#!/usr/bin/env python3
"""
Check that no plaintext secrets appear in generated files.

This script scans specified files for patterns that look like secrets:
- Bearer tokens (Bearer eyJ...)
- Long alphanumeric strings (API keys)
- Stripe-like prefixes (sk_live_, pk_live_)

Usage:
    python3 scripts/ci/check-no-plaintext-secrets.py <file1> <file2> ...
"""

import sys
import re
from pathlib import Path

# Patterns that look like secrets
SECRET_PATTERNS = [
    (r'Bearer\s+eyJ[a-zA-Z0-9_-]+', "JWT bearer token"),
    (r'[A-Z0-9]{32,}', "Long uppercase alphanumeric (likely API key)"),
    (r'sk_live_[a-zA-Z0-9]+', "Stripe live secret key"),
    (r'pk_live_[a-zA-Z0-9]+', "Stripe live publishable key"),
    (r'-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----', "Private key block"),
]

def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Scan a file for secret patterns. Returns [(line_num, pattern_name, match), ...]"""
    if not path.exists():
        return []
    
    content = path.read_text()
    findings = []
    
    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern, name in SECRET_PATTERNS:
            if re.search(pattern, line):
                findings.append((line_num, name, line.strip()))
    
    return findings

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/ci/check-no-plaintext-secrets.py <file1> <file2> ...", file=sys.stderr)
        sys.exit(1)
    
    files_to_scan = [Path(f) for f in sys.argv[1:]]
    all_findings = []
    
    for file_path in files_to_scan:
        findings = scan_file(file_path)
        if findings:
            all_findings.append((file_path, findings))
    
    if all_findings:
        print("❌ Plaintext secrets detected:", file=sys.stderr)
        for file_path, findings in all_findings:
            print(f"\n  {file_path}:", file=sys.stderr)
            for line_num, pattern_name, line in findings:
                print(f"    Line {line_num}: {pattern_name}", file=sys.stderr)
                print(f"      {line[:80]}...", file=sys.stderr)
        sys.exit(1)
    
    print(f"✅ No plaintext secrets found in {len(files_to_scan)} file(s)")

if __name__ == "__main__":
    main()
