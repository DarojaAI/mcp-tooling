"""check_disk tool — df per mount + du per path."""

from __future__ import annotations

import re
from typing import Any

from runtime.base import BaseTool
from servers.vm_ops.host_command import (
    DEFAULT_TIMEOUT_SECONDS,
    HostCommandError,
    run_host_command,
)

# ``du`` accepts a positional PATH. We validate it here so a crafted
# ``args["path"]`` can't smuggle flag content through ``du --max-depth``.
# The regex is intentionally conservative: absolute path, no shell
# metacharacters, no whitespace, length cap. (Anything fancier needs
# editing this file — that's the point.)
_PATH_RE = re.compile(r"^/[A-Za-z0-9._/()-]{1,4095}$")


class CheckDiskTool(BaseTool):
    """Show filesystem usage per mount, plus du for an optional path."""

    @property
    def tool_name(self) -> str:
        return "check_disk"

    @property
    def description(self) -> str:
        return (
            "Show df output for all mounted filesystems (size/used/avail/use%). "
            "Optionally include du summary for a path (capped depth 2)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Optional path to du-summarize. Must be absolute; "
                        "no shell metacharacters."
                    ),
                    "pattern": r"^/[A-Za-z0-9._/()-]{1,4095}$",
                },
                "depth": {
                    "type": "integer",
                    "description": "du max-depth (1..5; default 2).",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 2,
                },
            },
            "additionalProperties": False,
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            df_result = await run_host_command(
                "df",
                ["-h", "--output=source,size,used,avail,pcent,target"],
            )

            mounts = []
            for raw in df_result.stdout.splitlines()[1:]:
                line = raw.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 6:
                    continue
                source, size, used, avail, pcent, target = parts[:6]
                mounts.append(
                    {
                        "filesystem": source,
                        "size": size,
                        "used": used,
                        "avail": avail,
                        "use_pct": pcent,
                        "mounted_on": target,
                    }
                )

            path = args.get("path")
            depth = int(args.get("depth", 2))
            du_summary = None
            if path is not None:
                if not _PATH_RE.match(path):
                    return {
                        "error": "invalid_path",
                        "details": "path must be an absolute path with no shell metacharacters.",
                    }
                # ``du -d N -h path`` sums at the given depth. ``-x``
                # stays on one filesystem (crossing filesystems would
                # give confusing aggregates).
                du_result = await run_host_command(
                    "du",
                    ["-h", "-d", str(depth), "-x", path],
                    timeout=DEFAULT_TIMEOUT_SECONDS * 6,
                )
                du_entries = []
                for raw in du_result.stdout.splitlines():
                    line = raw.strip()
                    if not line:
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) != 2:
                        continue
                    size, p = parts
                    du_entries.append({"size": size, "path": p})
                du_summary = {"path": path, "depth": depth, "entries": du_entries}

            return {
                "result": {
                    "mount_count": len(mounts),
                    "mounts": mounts,
                    "du": du_summary,
                }
            }
        except HostCommandError as e:
            return {"error": "host_command_failed", "details": str(e)[:500]}
        except Exception as e:
            return {"error": "internal_error", "details": str(e)[:500]}
