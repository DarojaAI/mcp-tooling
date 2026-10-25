"""vm_ops tools.

Eight tools total: five read-only diagnostics, one service status read,
and two gated destructive ops (restart_service, kill_process).

Read-only tools never modify host state. They are always available.
Destructive tools check ``MCPTOOLING_CONFIRM_DESTRUCTIVE=true`` at call
time — the same gate Duffel uses for booking cancellation. Default is
false, so a misconfigured deployment cannot accidentally kill
processes or restart services.
"""

from servers.vm_ops.tools.check_disk import CheckDiskTool
from servers.vm_ops.tools.get_service_status import GetServiceStatusTool
from servers.vm_ops.tools.get_system_info import GetSystemInfoTool
from servers.vm_ops.tools.kill_process import KillProcessTool
from servers.vm_ops.tools.list_listening_ports import ListListeningPortsTool
from servers.vm_ops.tools.list_processes import ListProcessesTool
from servers.vm_ops.tools.restart_service import RestartServiceTool
from servers.vm_ops.tools.tail_logs import TailLogsTool

__all__ = [
    "CheckDiskTool",
    "GetServiceStatusTool",
    "GetSystemInfoTool",
    "KillProcessTool",
    "ListListeningPortsTool",
    "ListProcessesTool",
    "RestartServiceTool",
    "TailLogsTool",
]
