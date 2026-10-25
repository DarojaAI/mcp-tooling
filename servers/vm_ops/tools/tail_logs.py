"""tail_logs tool — journald query, filtered by service/severity/time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from runtime.base import BaseTool
from servers.vm_ops.host_command import (
    DEFAULT_MAX_OUTPUT_BYTES,
    HostCommandError,
    run_host_command,
)

# Severity filter values that map 1:1 to ``journalctl -p`` numeric priorities.
# We accept either the numeric form (0=emerg .. 7=debug) or a friendly name.
# Friendly → numeric mapping follows syslog(3) / RFC 5424 ordering.
_SEVERITY_ALIASES = {
    "emerg": "0",
    "alert": "1",
    "crit": "2",
    "err": "3",
    "warning": "4",
    "notice": "5",
    "info": "6",
    "debug": "7",
}


class TailLogsTool(BaseTool):
    """Read recent journald entries, optionally filtered by service, severity, time."""

    @property
    def tool_name(self) -> str:
        return "tail_logs"

    @property
    def description(self) -> str:
        return (
            "Read recent journald entries. Optional filters: service name "
            "(systemd unit substring), severity (numeric 0-7 or friendly: "
            "emerg/alert/crit/err/warning/notice/info/debug), and a time "
            "window in minutes back from now (default 60)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "systemd unit substring to filter on (e.g. 'mcp-tooling-duffel').",
                    "minLength": 1,
                    "maxLength": 128,
                },
                "severity": {
                    "type": "string",
                    "description": "Severity filter: 0-7 (numeric) or friendly name.",
                    "pattern": r"^(emerg|alert|crit|err|warning|notice|info|debug|[0-7])$",
                },
                "since_minutes": {
                    "type": "integer",
                    "description": "How far back to read (minutes from now).",
                    "minimum": 1,
                    "maximum": 60 * 24 * 7,  # cap at one week
                    "default": 60,
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Cap the number of returned entries (default 100).",
                    "minimum": 1,
                    "maximum": 5000,
                    "default": 100,
                },
            },
            "additionalProperties": False,
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            journal_args: list[str] = [
                "--no-pager",
                "--output=short",
                "-n",
                str(args.get("max_lines", 100)),
            ]

            sev = args.get("severity")
            if sev is not None:
                sev = _SEVERITY_ALIASES.get(sev.lower(), sev)
                journal_args.extend(["-p", sev])

            service = args.get("service")
            if service is not None:
                # ``_SYSTEMD_UNIT`` matches the full unit name; substring
                # matches would be ambiguous (e.g. "duffel" matches both
                # "mcp-tooling-duffel.service" and a hypothetical
                # "duffel-helper.service"). We require exact unit match
                # via ``journalctl -u``.
                if "/" in service or " " in service:
                    return {
                        "error": "invalid_service",
                        "details": "service must be a systemd unit name (no '/' or whitespace).",
                    }
                journal_args.extend(["-u", service])

            since = int(args.get("since_minutes", 60))
            # ``journalctl --since`` accepts ISO-8601; use the form
            # "YYYY-MM-DD HH:MM:SS" in UTC for readability.
            cutoff = datetime.now(UTC) - timedelta(minutes=since)
            journal_args.extend(["--since", cutoff.strftime("%Y-%m-%d %H:%M:%S")])

            # Allow up to 256 KiB for logs — much larger than the default
            # 64 KiB because multi-line stack traces blow past 64 KiB.
            result = await run_host_command(
                "journalctl",
                journal_args,
                max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES * 4,
            )

            entries = [
                line for line in result.stdout.splitlines() if line.strip()
            ]

            return {
                "result": {
                    "entry_count": len(entries),
                    "entries": entries,
                    "filters": {
                        "service": service,
                        "severity": sev,
                        "since_minutes": since,
                        "max_lines": args.get("max_lines", 100),
                    },
                }
            }
        except HostCommandError as e:
            return {"error": "host_command_failed", "details": str(e)[:500]}
        except Exception as e:
            return {"error": "internal_error", "details": str(e)[:500]}
