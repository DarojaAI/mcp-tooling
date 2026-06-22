"""
OAuth scope guard for the Google Workspace MCP server.

The narrow-scope policy is deliberate: this server is bound to the
mcp_tooling agent in TEST only, and broader scopes (gmail, calendar,
full Drive) must be added in a follow-up PR with explicit approval.

This module is the single chokepoint that decides whether a configured
set of OAuth scopes is acceptable. It is called from __main__.setup()
before any tool is registered, so a misconfigured server cannot start
and silently expose extra capabilities.

Policy:
- ALLOWED_SCOPES is the exhaustive set of scopes this server may grant.
- Anything outside that set → ScopePolicyError.
- This is enforced both at the server-entry-point level (startup) AND
  exposed as a helper for the install script so misconfiguration is
  caught before the service ever runs.

The guard is intentionally strict: deny by default, allow by explicit
listing. The intent is that widening scope is a code change, not a
config change.
"""

from __future__ import annotations

# Narrow, deliberate scope set.
# - drive.file: per-file access to files the app has created/opened.
#   Notably NOT the full `drive` scope (which is account-wide).
# - documents: Google Docs read/write.
# Add new scopes here ONLY with an explicit PR-level review.
ALLOWED_SCOPES: frozenset[str] = frozenset(
    {
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/documents",
    }
)


class ScopePolicyError(ValueError):
    """Raised when configured OAuth scopes violate the narrow-scope policy."""


def validate_scopes(scopes: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """
    Validate a configured scope list against ALLOWED_SCOPES.

    Args:
        scopes: The scopes the server has been asked to grant.

    Returns:
        The validated scope list, in the same order (for predictable
        credential construction).

    Raises:
        ScopePolicyError: If any scope is outside ALLOWED_SCOPES, or if
            the list is empty. The error message names every disallowed
            scope so the operator can fix config without guessing.
    """
    if not scopes:
        raise ScopePolicyError(
            "No OAuth scopes configured. Refusing to start: the Google "
            "Workspace MCP server requires at least one scope from the "
            f"narrow allowlist: {sorted(ALLOWED_SCOPES)}"
        )

    disallowed = [s for s in scopes if s not in ALLOWED_SCOPES]
    if disallowed:
        allowed = sorted(ALLOWED_SCOPES)
        raise ScopePolicyError(
            "Configured OAuth scopes violate narrow-scope policy. "
            f"Disallowed: {disallowed}. "
            f"Allowed: {allowed}. "
            "Broader scopes (gmail, calendar, full drive, etc.) must "
            "be added to ALLOWED_SCOPES in a follow-up PR with explicit "
            "approval — not via runtime config."
        )

    # Dedupe while preserving order (google-auth expects a list).
    seen: set[str] = set()
    deduped: list[str] = []
    for s in scopes:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped
