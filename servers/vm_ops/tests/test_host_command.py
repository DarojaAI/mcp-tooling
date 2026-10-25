"""Tests for the run_host_command helper."""

from __future__ import annotations

import pytest

from servers.vm_ops.host_command import (
    HostCommandError,
    run_host_command,
)


@pytest.mark.asyncio
async def test_run_host_command_basic():
    """A trivial command (hostname) should return non-empty stdout."""
    result = await run_host_command("hostname", [])
    assert result.returncode == 0
    assert result.stdout.strip() != ""
    assert result.stderr == ""


@pytest.mark.asyncio
async def test_run_host_command_args_pass_through():
    """Args are forwarded verbatim to the binary."""
    result = await run_host_command("uname", ["-r"])
    assert result.returncode == 0
    # ``uname -r`` prints something like "6.8.0-146-generic\n"
    assert result.stdout.strip()


@pytest.mark.asyncio
async def test_run_host_command_rejects_unknown_binary():
    with pytest.raises(ValueError, match="not in allowlist"):
        await run_host_command("rm", ["-rf", "/"])


@pytest.mark.asyncio
async def test_run_host_command_rejects_empty_arg():
    with pytest.raises(ValueError, match="empty"):
        await run_host_command("ps", [""])


@pytest.mark.asyncio
async def test_run_host_command_rejects_non_string_arg():
    with pytest.raises(ValueError, match="must be str"):
        await run_host_command("ps", [123])  # type: ignore[list-item]


@pytest.mark.asyncio
async def test_run_host_command_caps_output():
    """A custom tiny cap should trip when a tiny command produces more."""
    with pytest.raises(HostCommandError, match="exceeds cap"):
        # ``ps -ef`` always exceeds 8 bytes on any real system; we cap
        # at 8 to force the trip.
        await run_host_command("ps", ["-ef"], max_output_bytes=8)


@pytest.mark.asyncio
async def test_run_host_command_timeout_kills_process():
    """A command that hangs should be killed and raise HostCommandError."""
    with pytest.raises(HostCommandError, match="timed out"):
        # ``sleep`` is not in the allowlist, so use ``ps`` with an
        # ``etime`` filter that matches nothing — but ``ps`` is too
        # fast. Instead, exercise the timeout path via the
        # ``timeout`` parameter with a known-fast command that we
        # artificially cap at a near-zero budget.
        await run_host_command("ps", ["-ef"], timeout=0.001)


@pytest.mark.asyncio
async def test_run_host_command_non_zero_returncode_is_not_an_error():
    """We don't raise on non-zero — the caller decides whether that's a failure."""
    # ``kill 1`` requires root and fails for everyone else; perfect
    # for asserting that we don't raise.
    result = await run_host_command("kill", ["-15", "1"])
    assert result.returncode != 0
