"""restart_service tool — gated systemctl restart.

Gated by ``MCPTOOLING_CONFIRM_DESTRUCTIVE=true``. Same gate as Duffel's
``cancel_booking`` tool — the env flag is the explicit "yes, I know
this can break things" acknowledgment from the operator.
"""

from __future__ import annotations

import os
import re
from typing import Any

from runtime.base import BaseTool
from servers.vm_ops.host_command import (
    DEFAULT_MAX_OUTPUT_BYTES,
    HostCommandError,
    run_host_command,
)

_UNIT_NAME_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,256}$")


def _confirm_destructive() -> bool:
    """Mirror of Duffel's gating logic: opt-in via env flag.

    We lowercase + compare to ``true`` to match the Duffel convention.
    Anything else (``1``, ``yes``, ``on``, ``True`` with mixed case)
    is rejected on purpose — one canonical form keeps operators from
    depending on subtle shell-style boolean parsing.
    """
    return os.getenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", "false") == "true"


class RestartServiceTool(BaseTool):
    """Gated: systemctl restart a systemd unit."""

    @property
    def tool_name(self) -> str:
        return "restart_service"

    @property
    def description(self) -> str:
        return (
            "DESTRUCTIVE: restart a systemd unit. Requires "
            "MCPTOOLING_CONFIRM_DESTRUCTIVE=true. The unit will be "
            "unavailable for the duration of the restart."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "systemd unit name (e.g. 'mcp-tooling-duffel.service').",
                    "pattern": _UNIT_NAME_RE.pattern,
                },
                "reason": {
                    "type": "string",
                    "description": "Free-form reason logged alongside the restart.",
                    "maxLength": 512,
                },
            },
            "required": ["service"],
            "additionalProperties": False,
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if not _confirm_destructive():
                return {
                    "error": "destructive_not_confirmed",
                    "details": (
                        "Set MCPTOOLING_CONFIRM_DESTRUCTIVE=true to enable "
                        "service restart. This is a safety gate to prevent "
                        "accidental restarts."
                    ),
                }

            service = args["service"]
            if not _UNIT_NAME_RE.match(service):
                return {
                    "error": "invalid_service",
                    "details": f"service must match {_UNIT_NAME_RE.pattern!r}",
                }

            # ``systemctl restart`` blocks until the unit is back up
            # (or until it fails). We don't pass ``--no-block`` — the
            # operator wants to know whether the restart succeeded.
            result = await run_host_command(
                "systemctl",
                ["restart", service],
                timeout=60.0,
                max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES,
            )

            return {
                "result": {
                    "service": service,
                    "reason": args.get("reason", ""),
                    "returncode": result.returncode,
                    "stderr_tail": (result.stderr or "")[-512:],
                }
            }
        except HostCommandError as e:
            return {"error": "host_command_failed", "details": str(e)[:500]}
        except Exception as e:
            return {"error": "internal_error", "details": str(e)[:500]}
