"""get_system_info tool — read-only host summary."""

from __future__ import annotations

import os
from typing import Any

from runtime.base import BaseTool
from servers.vm_ops.host_command import run_host_command


class GetSystemInfoTool(BaseTool):
    """Return hostname, kernel, OS, and cpu/mem/disk totals."""

    @property
    def tool_name(self) -> str:
        return "get_system_info"

    @property
    def description(self) -> str:
        return (
            "Read-only host summary: hostname, kernel, OS pretty name, "
            "uptime, CPU count, total/used memory, total/used disk on /."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            uname = await run_host_command("uname", ["-r", "-m", "-n"])
            kernel_release = uname.stdout.strip().splitlines()[-1] if uname.stdout else ""

            pretty = ""
            try:
                with open("/etc/os-release", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            pretty = line.split("=", 1)[1].strip().strip('"')
                            break
            except FileNotFoundError:
                pretty = ""

            df = await run_host_command("df", ["-BG", "--output=size,used,avail,pcent", "/"])
            # df output format (with -BG): "1G  123M  900M  12%  /"
            df_line = df.stdout.strip().splitlines()[1] if df.stdout.strip() else ""
            df_parts = df_line.split()

            mem_total = "unknown"
            mem_used = "unknown"
            try:
                with open("/proc/meminfo", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            mem_total = line.split()[1] + " kB"
                        elif line.startswith("MemAvailable:"):
                            avail_kb = int(line.split()[1])
                            # We need used; back-compute from total.
                            # Re-read MemTotal since we may have skipped parsing.
                            pass
                # Re-read for accurate "used"
                with open("/proc/meminfo", encoding="utf-8") as f:
                    total_kb = 0
                    avail_kb = 0
                    for line in f:
                        if line.startswith("MemTotal:"):
                            total_kb = int(line.split()[1])
                        elif line.startswith("MemAvailable:"):
                            avail_kb = int(line.split()[1])
                if total_kb and avail_kb:
                    mem_total = f"{total_kb} kB"
                    mem_used = f"{total_kb - avail_kb} kB"
            except (FileNotFoundError, ValueError):
                pass

            cpu_count = os.cpu_count() or 0

            return {
                "result": {
                    "hostname": kernel_release.split()[-1] if kernel_release else "",
                    "kernel": kernel_release,
                    "os": pretty,
                    "cpu_count": cpu_count,
                    "memory": {"total": mem_total, "used": mem_used},
                    "disk_root": {
                        "size": df_parts[0] if len(df_parts) > 0 else "unknown",
                        "used": df_parts[1] if len(df_parts) > 1 else "unknown",
                        "avail": df_parts[2] if len(df_parts) > 2 else "unknown",
                        "use_pct": df_parts[3] if len(df_parts) > 3 else "unknown",
                    },
                }
            }
        except Exception as e:
            return {"error": "internal_error", "details": str(e)[:500]}
