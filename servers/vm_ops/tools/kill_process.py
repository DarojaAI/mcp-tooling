"""kill_process tool — gated kill by pid.

Gated by ``MCPTOOLING_CONFIRM_DESTRUCTIVE=true``. We send SIGTERM by
default and escalate to SIGKILL only if the caller passes
``force=true``. PID is validated as a positive integer; we never
accept a signal number from MCP input (a caller-asserted ``-9``
could trivially mask as ``kill`` doing something unexpected on
some systems).
"""

from __future__ import annotations

import os
import re
from typing import Any

from runtime.base import BaseTool
from servers.vm_ops.host_command import HostCommandError, run_host_command

_PID_RE = re.compile(r"^[1-9][0-9]{0,9}$")  # 1..9999999999; kernel pid_max is usually 4194304


def _confirm_destructive() -> bool:
    return os.getenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", "false") == "true"


class KillProcessTool(BaseTool):
    """Gated: send SIGTERM (default) or SIGKILL (force=true) to a pid."""

    @property
    def tool_name(self) -> str:
        return "kill_process"

    @property
    def description(self) -> str:
        return (
            "DESTRUCTIVE: send a signal to a process by PID. Default is "
            "SIGTERM (clean shutdown). force=true escalates to SIGKILL. "
            "Requires MCPTOOLING_CONFIRM_DESTRUCTIVE=true."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "string",
                    "description": "Target process ID (positive integer).",
                    "pattern": _PID_RE.pattern,
                },
                "force": {
                    "type": "boolean",
                    "description": "If true, send SIGKILL (9) instead of SIGTERM (15).",
                    "default": False,
                },
                "reason": {
                    "type": "string",
                    "description": "Free-form reason logged alongside the kill.",
                    "maxLength": 512,
                },
            },
            "required": ["pid"],
            "additionalProperties": False,
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            if not _confirm_destructive():
                return {
                    "error": "destructive_not_confirmed",
                    "details": (
                        "Set MCPTOOLING_CONFIRM_DESTRUCTIVE=true to enable "
                        "process kill. This is a safety gate to prevent "
                        "accidental process termination."
                    ),
                }

            pid = args["pid"]
            if not _PID_RE.match(pid):
                return {
                    "error": "invalid_pid",
                    "details": f"pid must match {_PID_RE.pattern!r}; got {pid!r}",
                }

            # Signal is fixed by the tool: SIGTERM (-15) or SIGKILL (-9).
            # We deliberately do NOT pass a user-supplied signal number —
            # that would let a caller pass ``-9`` while naming it as
            # ``SIGTERM``, or invoke signals reserved for the kernel.
            signal_arg = "-9" if args.get("force") else "-15"

            result = await run_host_command(
                "kill",
                [signal_arg, pid],
            )

            return {
                "result": {
                    "pid": int(pid),
                    "signal": "SIGKILL" if signal_arg == "-9" else "SIGTERM",
                    "reason": args.get("reason", ""),
                    "returncode": result.returncode,
                    "stderr_tail": (result.stderr or "")[-512:],
                }
            }
        except HostCommandError as e:
            return {"error": "host_command_failed", "details": str(e)[:500]}
        except Exception as e:
            return {"error": "internal_error", "details": str(e)[:500]}
