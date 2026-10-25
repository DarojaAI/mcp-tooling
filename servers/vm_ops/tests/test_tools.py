"""Tests for vm-ops tools.

These tests run on the host they're invoked on (i.e. they exercise
real ``ps``, ``df``, ``uname``, etc.). That's intentional — vm-ops is
a host-diagnostics tool, and the only way to validate it is to call
it against a real host. CI runs on ubuntu-latest runners; the
host_command cap + timeout guard against runaway output.
"""

from __future__ import annotations

import pytest

from servers.vm_ops.tools.check_disk import CheckDiskTool
from servers.vm_ops.tools.get_service_status import GetServiceStatusTool
from servers.vm_ops.tools.get_system_info import GetSystemInfoTool
from servers.vm_ops.tools.kill_process import KillProcessTool
from servers.vm_ops.tools.list_listening_ports import ListListeningPortsTool
from servers.vm_ops.tools.list_processes import ListProcessesTool
from servers.vm_ops.tools.restart_service import RestartServiceTool
from servers.vm_ops.tools.tail_logs import TailLogsTool

# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_system_info_returns_expected_shape():
    tool = GetSystemInfoTool()
    assert tool.tool_name == "get_system_info"
    schema = tool.input_schema
    assert schema["type"] == "object"
    assert schema.get("additionalProperties") is False

    result = await tool.call({})
    assert "result" in result
    payload = result["result"]
    assert "hostname" in payload
    assert "kernel" in payload
    assert "os" in payload
    assert "cpu_count" in payload
    assert isinstance(payload["cpu_count"], int)
    assert payload["memory"]["total"].endswith(" kB")
    assert "disk_root" in payload


@pytest.mark.asyncio
async def test_tail_logs_default_window():
    tool = TailLogsTool()
    schema = tool.input_schema
    assert "since_minutes" in schema["properties"]
    assert schema["properties"]["since_minutes"]["default"] == 60

    result = await tool.call({})
    assert "result" in result
    assert "entries" in result["result"]
    assert "filters" in result["result"]


@pytest.mark.asyncio
async def test_tail_logs_rejects_invalid_severity():
    # Input schema should already reject non-enum severities before
    # the tool's call() runs. This pins the schema as the gate.
    tool = TailLogsTool()
    schema = tool.input_schema
    assert "severity" in schema["properties"]
    sev = schema["properties"]["severity"]
    assert sev.get("enum") is None  # we use a pattern, not an enum
    assert sev.get("pattern")


@pytest.mark.asyncio
async def test_tail_logs_rejects_path_in_service():
    """Service name with ``/`` should be rejected (defense against
    passing a path or an option-flag-shaped name)."""
    tool = TailLogsTool()
    result = await tool.call({"service": "../../../etc/passwd"})
    assert "error" in result
    assert result["error"] == "invalid_service"


@pytest.mark.asyncio
async def test_list_processes_returns_pids():
    tool = ListProcessesTool()
    result = await tool.call({"limit": 5})
    assert "result" in result
    processes = result["result"]["processes"]
    assert len(processes) <= 5
    for p in processes:
        assert isinstance(p["pid"], int)
        assert p["pid"] > 0
        assert "user" in p
        assert "rss_kib" in p
        assert isinstance(p["rss_kib"], int)


@pytest.mark.asyncio
async def test_list_processes_rejects_unknown_sort_key():
    tool = ListProcessesTool()
    # Schema should reject unknown keys before call() runs.
    schema = tool.input_schema
    sort_by = schema["properties"]["sort_by"]
    assert "enum" in sort_by
    for k in ("pid", "rss", "pcpu"):
        assert k in sort_by["enum"]


@pytest.mark.asyncio
async def test_list_listening_ports_returns_entries():
    tool = ListListeningPortsTool()
    result = await tool.call({})
    assert "result" in result
    listeners = result["result"]["listeners"]
    # Don't assert count > 0 — a CI runner might legitimately have no
    # listeners beyond systemd-internal ones that ``ss -tulnp`` may
    # not show as pid-bearing.
    for entry in listeners:
        assert "protocol" in entry
        assert "local_address" in entry


@pytest.mark.asyncio
async def test_check_disk_returns_mounts():
    tool = CheckDiskTool()
    result = await tool.call({})
    assert "result" in result
    mounts = result["result"]["mounts"]
    assert len(mounts) > 0
    for m in mounts:
        assert "filesystem" in m
        assert "mounted_on" in m
        assert "use_pct" in m


@pytest.mark.asyncio
async def test_check_disk_rejects_relative_path():
    """The schema's pattern should reject anything but an absolute path."""
    tool = CheckDiskTool()
    schema = tool.input_schema
    assert schema["properties"]["path"]["pattern"].startswith("^/")


@pytest.mark.asyncio
async def test_get_service_status_unknown_unit():
    """systemctl is-active on a nonexistent unit returns exit 4 + 'inactive'."""
    tool = GetServiceStatusTool()
    result = await tool.call({"service": "definitely-not-a-real-unit.service"})
    assert "result" in result
    payload = result["result"]
    assert payload["service"] == "definitely-not-a-real-unit.service"
    # ``is-active`` exits 4 for missing units (3 for stopped, 0 for running).
    assert payload["is_active_exit"] in (3, 4)


@pytest.mark.asyncio
async def test_get_service_status_rejects_invalid_name():
    tool = GetServiceStatusTool()
    result = await tool.call({"service": "../etc/passwd"})
    assert "error" in result
    assert result["error"] == "invalid_service"


# ---------------------------------------------------------------------------
# Gated destructive tools — without the gate, they refuse to act.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_service_refuses_without_gate(monkeypatch):
    monkeypatch.delenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", raising=False)
    tool = RestartServiceTool()
    result = await tool.call({"service": "ssh.service"})
    assert "error" in result
    assert result["error"] == "destructive_not_confirmed"


@pytest.mark.asyncio
async def test_restart_service_refuses_with_wrong_gate(monkeypatch):
    """Only the literal lowercase 'true' counts. 1 / yes / on / True all fail."""
    for value in ("1", "yes", "True", "TRUE", "on"):
        monkeypatch.setenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", value)
        tool = RestartServiceTool()
        result = await tool.call({"service": "ssh.service"})
        assert "error" in result, f"unexpected success with gate={value!r}"
        assert result["error"] == "destructive_not_confirmed"


@pytest.mark.asyncio
async def test_restart_service_executes_with_gate(monkeypatch):
    """With the gate set, the tool actually invokes systemctl.

    We target ``ssh.service`` — even on minimal CI runners, sshd may
    not be running, and ``systemctl restart`` of a non-existent
    service returns non-zero, which is fine: the point is that the
    gate let the call through.
    """
    monkeypatch.setenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", "true")
    tool = RestartServiceTool()
    result = await tool.call({"service": "ssh.service", "reason": "unit test"})
    assert "result" in result, result
    payload = result["result"]
    assert payload["service"] == "ssh.service"
    assert payload["reason"] == "unit test"
    assert "returncode" in payload


@pytest.mark.asyncio
async def test_kill_process_refuses_without_gate(monkeypatch):
    monkeypatch.delenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", raising=False)
    tool = KillProcessTool()
    result = await tool.call({"pid": "1"})
    assert "error" in result
    assert result["error"] == "destructive_not_confirmed"


@pytest.mark.asyncio
async def test_kill_process_rejects_zero_pid():
    """PID 0 isn't a process — kernel uses it as "send to every process in
    the process group" for some signals. We never want to expose that."""
    tool = KillProcessTool()
    # We test the schema first because the gate is the second line of
    # defense; the schema should reject pid="0" up front.
    schema = tool.input_schema
    assert schema["properties"]["pid"]["pattern"].startswith("^[1-9]")


@pytest.mark.asyncio
async def test_kill_process_rejects_oversized_pid():
    """pid_max is usually 4194304; reject anything past 10 digits to
    prevent accidental integer overflow in tool clients."""
    tool = KillProcessTool()
    schema = tool.input_schema
    pattern = schema["properties"]["pid"]["pattern"]
    # 10 digits max: ^[1-9][0-9]{0,9}$
    assert "{0,9}" in pattern


@pytest.mark.asyncio
async def test_kill_process_executes_with_gate(monkeypatch):
    """With the gate, we attempt to kill a pid we're sure doesn't exist.

    PID 999999 is in the legitimate numeric range but won't exist on
    a CI runner. ``kill`` returns non-zero, which the tool reports —
    we're testing that the gate let it through.
    """
    monkeypatch.setenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", "true")
    tool = KillProcessTool()
    result = await tool.call({"pid": "999999", "reason": "unit test"})
    assert "result" in result, result
    payload = result["result"]
    assert payload["pid"] == 999999
    assert payload["signal"] == "SIGTERM"


@pytest.mark.asyncio
async def test_kill_process_force_uses_sigkill(monkeypatch):
    monkeypatch.setenv("MCPTOOLING_CONFIRM_DESTRUCTIVE", "true")
    tool = KillProcessTool()
    result = await tool.call({"pid": "999999", "force": True})
    assert "result" in result
    assert result["result"]["signal"] == "SIGKILL"


# ---------------------------------------------------------------------------
# Schema invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool",
    [
        GetSystemInfoTool(),
        TailLogsTool(),
        ListProcessesTool(),
        ListListeningPortsTool(),
        CheckDiskTool(),
        GetServiceStatusTool(),
    ],
)
def test_read_only_tools_have_no_destructive_shadow(tool):
    """No read-only tool may inherit the destructive gate."""
    schema = tool.input_schema
    assert "additionalProperties" in schema, tool.tool_name
    # Read-only tools must not require ``reason`` (that's a destructive-tool affordance).
    required = schema.get("required", [])
    assert "reason" not in required, tool.tool_name


@pytest.mark.parametrize(
    "tool",
    [RestartServiceTool(), KillProcessTool()],
)
def test_destructive_tools_declare_destructive_in_description(tool):
    """Every destructive tool must surface the word 'DESTRUCTIVE' in its
    human-readable description so LLM-driven callers can't miss the
    gating requirement.
    """
    assert "DESTRUCTIVE" in tool.description
    assert "MCPTOOLING_CONFIRM_DESTRUCTIVE" in tool.description
