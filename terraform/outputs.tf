# =============================================================================
# Outputs — re-exported from terraform-hcloud-linux-vm module
# =============================================================================

output "ssh_command" {
  description = "Ready-to-run SSH command"
  value       = "ssh -o StrictHostKeyChecking=no -i ~/.ssh/id_ed25519 root@${module.vm.ipv4_address}"
}

output "ssh_user" {
  description = "SSH user for the server (Hetzner default)"
  value       = "root"
}

output "server_type" {
  description = "Hetzner server type"
  value       = var.server_type
}

output "location" {
  description = "Hetzner datacenter location"
  value       = var.location
}

output "labels" {
  description = "Labels applied to the server"
  value       = merge(var.labels, var.environment != "" ? { environment = var.environment } : {})
}

output "server_id" {
  description = "Hetzner server ID"
  value       = module.vm.server_id
}

output "server_name" {
  description = "Server name"
  value       = module.vm.server_name
}

output "ipv4_address" {
  description = "Public IPv4 address of the server"
  value       = module.vm.ipv4_address
}

output "ipv6_address" {
  description = "Public IPv6 address of the server"
  value       = module.vm.ipv6_address
}

output "connection_info" {
  description = "Connection info from the VM module"
  value       = module.vm.connection_info
}

output "server_status" {
  description = "Current server status"
  value       = module.vm.server_status
}

# -----------------------------------------------------------------------------
# MCP endpoint discovery
# -----------------------------------------------------------------------------
# These outputs are the "where does the MCP server live" answer that
# clients (OpenClaw gateway, other MCP servers) need in order to connect.
#
# `mcp_endpoints` returns one entry per port in `inbound_ports`, each
# shaped as `{port, base_url, mcp_url, health}`. Stable shape; consumed
# by the deploy workflow's endpoint-manifest job and by external clients
# that fetch the manifest artifact.
#
# `mcp_endpoint` is a shorthand for the single-port case (the common
# one-server-per-VM deployment). When `inbound_ports` has more than one
# entry, it returns the first — use `mcp_endpoints` for the full list.
# -----------------------------------------------------------------------------

output "mcp_endpoints" {
  description = <<-EOT
    Public MCP endpoint URLs for every inbound port on this VM, as
    `http://<ipv4_address>:<port>/mcp`. Stable shape; consumed by the
    deploy workflow's endpoint-manifest job and by external clients
    that fetch the manifest artifact.
  EOT
  value = [
    for p in var.inbound_ports : {
      port     = p
      base_url = "http://${module.vm.ipv4_address}:${p}"
      mcp_url  = "http://${module.vm.ipv4_address}:${p}/mcp"
      health   = "http://${module.vm.ipv4_address}:${p}/healthz"
    }
  ]
}

output "mcp_endpoint" {
  description = <<-EOT
    Convenience: the first entry of `mcp_endpoints`. Suitable for the
    common single-server-per-VM deployment.
  EOT
  value = length(var.inbound_ports) > 0 ? {
    port     = var.inbound_ports[0]
    base_url = "http://${module.vm.ipv4_address}:${var.inbound_ports[0]}"
    mcp_url  = "http://${module.vm.ipv4_address}:${var.inbound_ports[0]}/mcp"
    health   = "http://${module.vm.ipv4_address}:${var.inbound_ports[0]}/healthz"
  } : null
}
