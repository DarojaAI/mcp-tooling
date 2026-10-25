# vm-ops MCP server

Host-level operations for the same Linux VM the server runs on. Exposes
two classes of tools:

- **Read-only diagnostics** (always available): `get_system_info`,
  `tail_logs`, `list_processes`, `list_listening_ports`, `check_disk`,
  `get_service_status`.
- **Gated destructive ops** (require `MCPTOOLING_CONFIRM_DESTRUCTIVE=true`):
  `restart_service`, `kill_process`.

Resolves [issue #4](https://github.com/DarojaAI/mcp-tooling/issues/4).

## Why

The other MCP servers in this repo (duffel, google-workspace,
amadeus-hotels) wrap **external** APIs. vm-ops wraps **host operations**
— it's the agent's window onto the VM it runs on. Before this existed,
debugging a wedged MCP server required SSH to the VM, looking at
journald by hand, and trying to remember whether `8766` was
google-workspace or something else.

vm-ops gives an authorized MCP caller (`MCPTOOLING_ALLOWED_TOKENS`) a
structured, allowlisted surface for the same information — plus two
gated repair actions (restart a systemd unit, kill a pid by signal)
that can recover from a stuck state without needing shell access.

## Safety model

The two destructive tools share a single env-var gate:
`MCPTOOLING_CONFIRM_DESTRUCTIVE`. Default is `false`, in which case
the tools return `{"error": "destructive_not_confirmed", ...}` without
touching anything. Setting it to `true` (literal lowercase — `1` /
`yes` / `on` are all rejected on purpose) unlocks the tools.

This is the same gate Duffel's `cancel_booking` tool uses
(see `servers/duffel/tools/cancel_booking.py`). One canonical form
keeps operators from depending on subtle shell-style boolean parsing.

The gate is checked **at call time**, not at startup. A server can run
with the gate off and still serve all six read-only tools. An operator
can flip the gate by changing the secrets file and restarting the
service — no redeploy required.

## What it cannot do (v1)

Out of scope, deferred to a future issue:

- **SSH to other hosts.** vm-ops only operates on the VM it runs on.
  Cross-host diagnostics would need key management + a trust model
  that's too large for v1.
- **File editing / package install / network config.** All too
  destructive for an MCP surface. Use SSH (or Ansible, or a future
  deploy workflow) for these.
- **Windows / macOS support.** The tools assume Linux systemd + journald.
  A `ps` / `ss` parser change might get you macOS; Windows would
  require a separate implementation.

## Tools

### Read-only

| Tool | Purpose |
|------|---------|
| `get_system_info` | hostname, kernel, OS, CPU count, total/used memory, disk usage on `/` |
| `tail_logs` | journald query, filtered by service (systemd unit), severity (numeric 0-7 or friendly name), and a time window in minutes (default 60) |
| `list_processes` | `ps`-like output, sorted by `rss` / `pcpu` / `pmem` / `etime` / etc., limit 1-5000, optional user filter |
| `list_listening_ports` | `ss -tulnp` output, parseable protocol + local address:port + pid/process |
| `check_disk` | `df` per mount, plus optional `du` summary at depth 1-5 for an absolute path |
| `get_service_status` | `systemctl is-active` + `is-enabled` + last 5 journal lines for a unit |

### Gated destructive

| Tool | Effect |
|------|--------|
| `restart_service` | `systemctl restart <unit>`. Blocks until the unit is back up or the restart fails. |
| `kill_process` | `kill -15 <pid>` (default) or `kill -9 <pid>` (`force=true`). PID must be 1..9999999999. |

Both destructive tools log a `reason` argument (free-form, ≤512 chars)
alongside the action. The reason is returned in the tool result and is
visible to whoever consumes the MCP response — it is **not** persisted
to a separate audit log yet (deferred).

## Subprocess safety

All tools route through `servers/vm_ops/host_command.run_host_command`,
which enforces four invariants:

1. **No shell.** `asyncio.create_subprocess_exec` is used with an
   argv list. A caller-supplied `pid` or `service` cannot be
   interpreted by `/bin/sh`.
2. **Allowlisted binaries.** Each tool only invokes a binary from the
   explicit `BINARIES` allowlist (e.g. `ps`, `df`, `systemctl`, `kill`).
   New binaries require editing that table.
3. **Output cap.** Default 64 KiB (`tail_logs` is 256 KiB); exceeding
   the cap kills the subprocess and raises an error rather than
   returning a truncated response.
4. **Wall-clock timeout.** Default 10s; `restart_service` uses 60s to
   let systemd finish. A timed-out subprocess is killed.

Argument validation is layered: the JSON schema rejects obviously bad
inputs at parse time (`pid` matches `^[1-9][0-9]{0,9}$`; `service`
matches `^[A-Za-z0-9_.@:-]{1,256}$`; `path` must be an absolute path
with no shell metacharacters), and `run_host_command` rejects empty /
non-string args as a second line of defense.

## Configuration

`config/servers/vm-ops.yaml` declares the canonical per-server config:

```yaml
name: vm-ops
package: servers.vm_ops
port: 8768
secrets:
  - MCPTOOLING_ALLOWED_TOKENS
optional_secrets:
  - MCPTOOLING_CONFIRM_DESTRUCTIVE
  - MCPTOOLING_ALLOWED_TOOLS
oauth_scope_guard: false
```

Port 8768 is the next free slot after duffel (8765), google-workspace
(8766), and amadeus-hotels (8767). Add `8768` to your
`inbound_ports` list in `terraform/terraform.tfvars` to open it on
the Hetzner firewall.

## Deployment

The deploy workflow picks vm-ops up like any other self-hosted server:

1. Add `8768` to `inbound_ports` in `terraform/terraform.tfvars`.
2. Run `.github/workflows/deploy-mcp-server.yml` with
   `server_name=vm-ops` and `environment=dev|staging|prod`.
3. The workflow calls `scripts/deploy/install-vm-ops-vm.sh`, which
   delegates to `install-mcp-server.sh`. The systemd unit is named
   `mcp-tooling-vm-ops.service` and listens on the configured port.

To unlock destructive ops after deploy, add
`MCPTOOLING_CONFIRM_DESTRUCTIVE=true` to `/etc/mcp-tooling/secrets.env`
on the VM and `systemctl restart mcp-tooling-vm-ops.service`.

## Tests

`tests/bats/install-vm-ops.bats` pins the install shim + config + tool
list to make sure the deploy plumbing stays wired up.

`servers/vm_ops/tests/test_host_command.py` covers the subprocess
helper (binary allowlist, arg validation, output cap, timeout,
non-zero return codes).

`servers/vm_ops/tests/test_tools.py` runs every tool against the host
the tests are invoked on. CI runs on ubuntu-latest, which has
systemd / journald / `ps` / `df` / `ss` available. Destructive tools
are tested both with the gate off (refused) and with the gate on
(allowed — the underlying `kill` / `systemctl` invocation is exercised
even when the unit doesn't exist on the runner; the assertion is that
the gate let the call through, not that it succeeded).

## See also

- `docs/integrations/mcp-integration-shapes.md` — the wider integration
  taxonomy (Shape 1 self-hosted vs Shape 2 remote_mcp); vm-ops is
  Shape 1.
- `docs/integrations/mcp-endpoint-discovery.md` — how the gateway
  finds the URL once deployed (`config/endpoints.yaml` + the
  `update-endpoints` workflow).
- `docs/integrations/serverspec-refactor.md` — the `ServerSpec`
  dataclass pattern vm-ops uses in its `__main__.py`.
