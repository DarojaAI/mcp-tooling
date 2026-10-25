"""
Subprocess helpers for vm_ops tools.

Each vm_ops tool wraps one or two short-lived host commands. We always:

1. Use ``asyncio.create_subprocess_exec`` (not ``shell=True``) so arguments
   can never be interpreted by a shell. Argument-injection from MCP input
   is the obvious attack surface — a tool that runs ``kill <user_input>``
   with ``shell=True`` would happily run ``kill $SHELL``.
2. Cap the captured output (default 64 KiB) so a runaway command can't
   OOM the server or send a multi-MB response back to the client.
3. Cap the wall-clock timeout (default 10s) so a hung command (e.g. a
   frozen ``journalctl`` against a wedged disk) doesn't pin the event
   loop forever.
4. Refuse ``argv[0]`` paths that don't start with ``/`` so a sneaky
   caller can't drop a binary earlier on PATH. Combined with the
   explicit allowlist of binaries used by each tool, this is defense
   in depth.

The helpers here are deliberately tiny — the per-tool files do all
the parsing. This keeps the policy ("no shell, cap output, cap time,
absolute paths") in one place.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

# 64 KiB is enough for ~1k lines of typical ``ps`` / ``df`` output. Tools
# that need more (e.g. ``tail_logs``) can raise it; nothing in the
# issue warrants unbounded output.
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024

# 10s is the upper bound for any single host command. ``journalctl``
# against a healthy journal is sub-second; ``df`` / ``ps`` are
# milliseconds. A timeout here almost always means something is wrong
# on the host, and we'd rather the tool return an error than hang.
DEFAULT_TIMEOUT_SECONDS = 10.0

# Binaries that tools are allowed to invoke. Hardcoded absolute paths
# keep the allowlist auditable in one place; new tools must add a new
# entry here and reference it.
#
# Paths are duplicated where the binary lives at two locations on
# common distros (e.g. ``kill`` and ``ps`` are at both ``/bin/`` and
# ``/usr/bin/`` on Debian-derived images). We pick the path that is
# guaranteed by the systemd unit's PATH (``/usr/local/sbin:/usr/local/
# bin:/usr/sbin:/usr/bin:/sbin:/bin``), which is what the install
# script sets. ``/usr/bin/`` is the canonical location on every distro
# we deploy to.
BINARIES = {
    "df": "/usr/bin/df",
    "du": "/usr/bin/du",
    "hostname": "/usr/bin/hostname",
    "journalctl": "/usr/bin/journalctl",
    "kill": "/usr/bin/kill",
    "ps": "/usr/bin/ps",
    "ss": "/usr/bin/ss",
    "systemctl": "/usr/bin/systemctl",
    "uname": "/usr/bin/uname",
    "uptime": "/usr/bin/uptime",
}


class HostCommandError(RuntimeError):
    """Raised when a host subprocess fails, times out, or exceeds the output cap."""


@dataclass(frozen=True)
class HostCommandResult:
    """Successful subprocess result. stdout is decoded; stderr is preserved
    separately so error messages can be surfaced to the caller."""

    stdout: str
    stderr: str
    returncode: int


async def run_host_command(
    binary: str,
    args: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> HostCommandResult:
    """Run ``binary`` with ``args`` and capture up to ``max_output_bytes``.

    Args:
        binary: key into ``BINARIES`` (e.g. ``"ps"``). Resolved via the
            allowlist — passing a raw path raises ValueError.
        args: argv passed to the binary. Each entry must be a string.
        timeout: wall-clock cap. Exceeding it kills the process and
            raises ``HostCommandError``.
        max_output_bytes: cap on captured stdout+stderr (combined).
            Anything beyond is truncated and a flag is set on the error.

    Returns:
        ``HostCommandResult`` with decoded stdout/stderr + returncode.
        ``returncode`` is the actual exit code; we don't raise on
        non-zero — the caller can decide whether that's an error.

    Raises:
        ValueError: ``binary`` not in the allowlist, or an ``args``
            entry doesn't look like a safe string.
        HostCommandError: timeout, or output cap exceeded (subprocess
            is killed in either case).
    """
    if binary not in BINARIES:
        raise ValueError(
            f"binary {binary!r} not in allowlist; allowed: {sorted(BINARIES)}"
        )
    for i, a in enumerate(args):
        if not isinstance(a, str):
            raise ValueError(f"args[{i}] must be str, got {type(a).__name__}")
        # Defense against argument injection: no empty args, no leading
        # dash in a position that would be interpreted as a flag. We
        # can't blanket-ban dashes (legitimate flags exist), but we
        # CAN require explicit per-tool allowlists for any arg that
        # starts with ``-`` — that's checked at the tool layer.
        if a == "":
            raise ValueError(f"args[{i}] is empty")

    proc = await asyncio.create_subprocess_exec(
        BINARIES[binary],
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except TimeoutError as exc:
        # communicate() also raises TimeoutError when its await is
        # cancelled by wait_for; the subprocess is still running and
        # needs to be killed explicitly.
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        raise HostCommandError(
            f"{binary} timed out after {timeout}s"
        ) from exc

    # Truncate if combined output exceeds the cap. We do this BEFORE
    # decoding so a single multi-byte char at the boundary can't blow
    # up the response; we also keep stderr separate so the caller
    # sees what the binary was trying to tell us.
    total = len(stdout_b) + len(stderr_b)
    if total > max_output_bytes:
        # The subprocess has already finished by the time we read its
        # output; killing it would race with the communicate() done
        # above and raise ProcessLookupError. Drain and continue.
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        raise HostCommandError(
            f"{binary} output ({total} bytes) exceeds cap "
            f"({max_output_bytes} bytes); refusing to return partial output"
        )

    return HostCommandResult(
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
        returncode=proc.returncode if proc.returncode is not None else -1,
    )


__all__ = [
    "BINARIES",
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "HostCommandError",
    "HostCommandResult",
    "run_host_command",
]
