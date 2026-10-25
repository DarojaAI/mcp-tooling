"""list_processes tool — ps-like output, sorted."""

from __future__ import annotations

from typing import Any

from runtime.base import BaseTool
from servers.vm_ops.host_command import HostCommandError, run_host_command

# Sort keys that ``ps`` accepts directly as the argument to ``--sort``.
# We expose a small friendly subset; falling outside the allowlist is
# not safe (an attacker could craft a custom ``-``-prefixed column).
_SORT_KEYS = frozenset(
    {"pid", "ppid", "user", "rss", "vsz", "pcpu", "pmem", "etime", "comm", "cmd"}
)


class ListProcessesTool(BaseTool):
    """List processes on the host, sorted by a chosen column."""

    @property
    def tool_name(self) -> str:
        return "list_processes"

    @property
    def description(self) -> str:
        return (
            "List running processes (ps-like). Returns pid, user, rss (KiB), "
            "cpu%, mem%, elapsed time, and command. Sorted by the given "
            "column (default: rss descending)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sort_by": {
                    "type": "string",
                    "description": "Column to sort by.",
                    "enum": sorted(_SORT_KEYS),
                    "default": "rss",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of processes to return (after sort).",
                    "minimum": 1,
                    "maximum": 5000,
                    "default": 50,
                },
                "user": {
                    "type": "string",
                    "description": "Filter by user name (optional).",
                    "pattern": r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,31}$",
                },
            },
            "additionalProperties": False,
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            sort_by = args.get("sort_by", "rss")
            if sort_by not in _SORT_KEYS:
                return {
                    "error": "invalid_sort_key",
                    "details": f"sort_by must be one of {sorted(_SORT_KEYS)}",
                }

            ps_args: list[str] = [
                "-o",
                "pid,user,rss,pcpu,pmem,etime,comm",
                "--sort",
                f"-{sort_by}",  # leading "-" = descending, top consumers first
            ]
            user = args.get("user")
            if user is not None:
                ps_args.extend(["-U", user])

            result = await run_host_command("ps", ps_args)

            lines = result.stdout.splitlines()
            # First line is the header; remainder are rows.
            rows = []
            for raw in lines[1:]:
                stripped = raw.strip()
                if not stripped:
                    continue
                # ps output is whitespace-separated; ``comm`` can contain
                # spaces but it's the last column, so we treat everything
                # but the last token as a column.
                parts = stripped.split(None, 6)
                if len(parts) < 7:
                    continue
                pid, user_, rss, pcpu, pmem, etime, comm = parts
                rows.append(
                    {
                        "pid": int(pid),
                        "user": user_,
                        "rss_kib": int(rss),
                        "pcpu": pcpu,
                        "pmem": pmem,
                        "etime": etime,
                        "comm": comm,
                    }
                )

            limit = int(args.get("limit", 50))
            rows = rows[:limit]

            return {
                "result": {
                    "count": len(rows),
                    "processes": rows,
                    "sort_by": sort_by,
                }
            }
        except HostCommandError as e:
            return {"error": "host_command_failed", "details": str(e)[:500]}
        except Exception as e:
            return {"error": "internal_error", "details": str(e)[:500]}
