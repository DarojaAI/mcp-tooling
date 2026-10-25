"""get_service_status tool — systemctl is-active."""

from __future__ import annotations

import re
from typing import Any

from runtime.base import BaseTool
from servers.vm_ops.host_command import HostCommandError, run_host_command

# systemd unit names: alphanumerics, ``.``, ``_``, ``-``, ``@``, ``:``.
# We deliberately don't allow ``/`` (path-style targets) because those
# are usually not what a casual MCP caller means, and the path-style
# name would need additional shell-escaping we don't want to do.
_UNIT_NAME_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,256}$")


class GetServiceStatusTool(BaseTool):
    """Return systemctl is-active state for a systemd unit."""

    @property
    def tool_name(self) -> str:
        return "get_service_status"

    @property
    def description(self) -> str:
        return (
            "Read-only: report whether a systemd unit is active, plus "
            "the last 5 lines of its journal. Use restart_service to "
            "actually change state."
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
            },
            "required": ["service"],
            "additionalProperties": False,
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            service = args["service"]
            if not _UNIT_NAME_RE.match(service):
                return {
                    "error": "invalid_service",
                    "details": f"service must match {_UNIT_NAME_RE.pattern!r}",
                }

            # ``systemctl is-active`` exits 0 for active, 3 for inactive,
            # 4 for "no such unit". We don't want to special-case any
            # of those — just report returncode + stdout.
            is_active = await run_host_command(
                "systemctl", ["is-active", service]
            )
            is_enabled = await run_host_command(
                "systemctl", ["is-enabled", service]
            )

            recent_log = await run_host_command(
                "journalctl",
                ["-u", service, "-n", "5", "--no-pager", "--output=short"],
            )

            log_lines = [
                line for line in recent_log.stdout.splitlines() if line.strip()
            ]

            return {
                "result": {
                    "service": service,
                    "is_active": is_active.stdout.strip(),
                    "is_active_exit": is_active.returncode,
                    "is_enabled": is_enabled.stdout.strip(),
                    "is_enabled_exit": is_enabled.returncode,
                    "recent_log_lines": log_lines,
                }
            }
        except HostCommandError as e:
            return {"error": "host_command_failed", "details": str(e)[:500]}
        except Exception as e:
            return {"error": "internal_error", "details": str(e)[:500]}
