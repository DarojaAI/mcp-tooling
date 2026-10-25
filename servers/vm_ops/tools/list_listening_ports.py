"""list_listening_ports tool — ss/netstat output."""

from __future__ import annotations

from typing import Any

from runtime.base import BaseTool
from servers.vm_ops.host_command import HostCommandError, run_host_command


class ListListeningPortsTool(BaseTool):
    """List TCP/UDP sockets in LISTEN state on the host."""

    @property
    def tool_name(self) -> str:
        return "list_listening_ports"

    @property
    def description(self) -> str:
        return (
            "List TCP and UDP sockets currently in LISTEN state. Returns "
            "protocol, local address:port, peer address:port (TCP only), "
            "and the owning process pid/name."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "protocol": {
                    "type": "string",
                    "description": "Filter by protocol.",
                    "enum": ["tcp", "udp", "all"],
                    "default": "all",
                },
            },
            "additionalProperties": False,
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            protocol = args.get("protocol", "all")

            # ``ss -tulnp`` prints listeners with PID/program when
            # available. We don't expose any flag toggles — the only
            # knob is protocol (which we honor by including/excluding
            # ``-t`` / ``-u``).
            ss_args: list[str] = ["-tulnp"]
            if protocol == "tcp":
                ss_args = ["-tlnp"]
            elif protocol == "udp":
                ss_args = ["-ulnp"]

            result = await run_host_command("ss", ss_args)

            entries = []
            for raw in result.stdout.splitlines():
                line = raw.strip()
                if not line or line.startswith("State") or line.startswith("Netid"):
                    continue

                # ss -t output columns: State Recv-Q Send-Q Local
                # Address:Port Peer Address:Port Process
                # ss -u output columns: State Recv-Q Send-Q Local
                # Address:Port Peer Address:Port (no Process column on
                # older ss; we tolerate the difference).
                parts = line.split()
                if len(parts) < 5:
                    continue

                proto = parts[0].lower()
                local = parts[3] if len(parts) > 3 else ""
                peer = parts[4] if len(parts) > 4 else ""
                process = " ".join(parts[5:]) if len(parts) > 5 else ""

                pid: int | None = None
                name = ""
                if process.startswith("users:"):
                    # Format: users:(("name",pid=1234,fd=5))
                    paren = process.find("((")
                    if paren != -1:
                        inner = process[paren + 2 :]
                        close = inner.find(")")
                        if close != -1:
                            inner = inner[:close]
                            fragments = inner.split(",")
                            if fragments:
                                name = fragments[0].strip('"')
                            for frag in fragments[1:]:
                                if frag.strip().startswith("pid="):
                                    try:
                                        pid = int(frag.split("=", 1)[1])
                                    except ValueError:
                                        pid = None

                entries.append(
                    {
                        "protocol": proto,
                        "local_address": local,
                        "peer_address": peer,
                        "pid": pid,
                        "process": name,
                    }
                )

            return {
                "result": {
                    "count": len(entries),
                    "listeners": entries,
                    "protocol_filter": protocol,
                }
            }
        except HostCommandError as e:
            return {"error": "host_command_failed", "details": str(e)[:500]}
        except Exception as e:
            return {"error": "internal_error", "details": str(e)[:500]}
