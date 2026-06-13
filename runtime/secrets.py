"""
Secrets loading from environment files.

Loads secrets from a dotenv-style file with explicit allowlist validation.
"""

import os
from pathlib import Path
from typing import Dict, Set


def load_secrets(
    path: Path | str | None = None,
    required_keys: Set[str] | None = None,
    optional_keys: Set[str] | None = None,
) -> Dict[str, str]:
    """
    Load secrets from an environment file.
    
    Args:
        path: Path to secrets file (default: MCPTOOLING_SECRETS_PATH env var or /etc/mcp-tooling/secrets.env)
        required_keys: Set of required keys (raises ValueError if any missing)
        optional_keys: Set of optional keys (loaded if present, ignored if missing)
    
    Returns:
        Dict of key -> value
    
    Raises:
        FileNotFoundError: If secrets file doesn't exist
        ValueError: If a required key is missing
        ValueError: If a key in the file is not in required_keys or optional_keys (strict allowlist)
    """
    # Resolve path
    if path is None:
        path = os.getenv("MCPTOOLING_SECRETS_PATH", "/etc/mcp-tooling/secrets.env")
    
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Secrets file not found: {path}")
    
    # Parse dotenv file
    secrets = {}
    with open(path) as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            
            # Parse KEY=VALUE
            if "=" not in line:
                raise ValueError(f"Invalid line {line_num} in {path}: expected KEY=VALUE")
            
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            
            # Remove quotes if present
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            
            secrets[key] = value
    
    # Validate against allowlist
    if required_keys or optional_keys:
        allowed_keys = (required_keys or set()) | (optional_keys or set())
        
        for key in secrets:
            if key not in allowed_keys:
                raise ValueError(
                    f"Key '{key}' in {path} is not in the allowlist. "
                    f"Allowed: {sorted(allowed_keys)}"
                )
    
    # Check required keys
    if required_keys:
        missing = required_keys - secrets.keys()
        if missing:
            raise ValueError(
                f"Missing required secrets in {path}: {sorted(missing)}"
            )
    
    return secrets
