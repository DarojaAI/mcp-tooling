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
