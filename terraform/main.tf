# =============================================================================
# mcp-tooling - Terraform Root Module
# =============================================================================
# Provisions a Hetzner VM to host the Duffel MCP server (and any future
# MCP servers added under servers/).
#
# Backend: S3 on Hetzner Storage Box (per-environment state keys).
# Provider: hetznercloud/hcloud.
# Reuses: terraform-hcloud-linux-vm for VM provisioning (Layer 1).
# =============================================================================

terraform {
  required_version = ">= 1.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.46"
    }
  }

  backend "s3" {
    endpoint                    = "https://s3.fra1.cloudprovider.de"
    bucket                      = "terraform-state-mcp-tooling"
    # key is overridden at init time: dev/terraform.tfstate, prod/terraform.tfstate, etc.
    key                         = "dev/terraform.tfstate"
    region                      = "fra1"
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    force_path_style            = true
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

# =============================================================================
# Data Sources
# =============================================================================

data "hcloud_ssh_key" "main" {
  count = var.hetzner_ssh_key_name != "" ? 1 : 0
  name  = var.hetzner_ssh_key_name
}

# =============================================================================
# Layer 1 — VM provisioning via terraform-hcloud-linux-vm
# =============================================================================

module "vm" {
  source = "git::https://github.com/DarojaAI/terraform-hcloud-linux-vm.git?ref=7471582"

  hcloud_token         = var.hcloud_token
  server_name          = var.server_name
  server_type          = var.server_type
  location             = var.location
  image                = var.image
  hetzner_ssh_key_name = var.hetzner_ssh_key_name
  ssh_keys             = var.ssh_keys
  labels               = merge(var.labels, var.environment != "" ? { environment = var.environment } : {})
}

# =============================================================================
# Firewall
# =============================================================================
# Duffel MCP HTTP server defaults to port 8765; mcp-tooling doesn't expose
# any other inbound services. Add rules here when adding new servers.

resource "hcloud_firewall" "main" {
  name   = "${var.server_name}-firewall"
  labels = merge(var.labels, var.environment != "" ? { environment = var.environment } : {})

  # SSH inbound
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # Duffel MCP HTTP server (default port)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "8765"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # All outbound — TCP
  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "any"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }

  # All outbound — UDP
  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "any"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }

  # ICMP (ping)
  rule {
    direction       = "out"
    protocol        = "icmp"
    destination_ips = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_firewall_attachment" "main" {
  firewall_id = hcloud_firewall.main.id
  server_ids  = [module.vm.server_id]
}

# =============================================================================
# Variables
# =============================================================================

variable "hcloud_token" {
  description = "Hetzner API token"
  type        = string
  sensitive   = true
}

variable "server_name" {
  description = "Name of the server (must be unique in Hetzner project)"
  type        = string
}

variable "server_type" {
  description = "Hetzner server type (e.g., cx22, cpx21, cpx41)"
  type        = string
  default     = "cx22"

  validation {
    condition     = can(regex("^(cx|cp|cc|ca)x?[0-9]{1,2}$", var.server_type))
    error_message = "Invalid server_type. Must be a known Hetzner server type (e.g., cx22, cpx41, cax11, ccx33)."
  }
}

variable "location" {
  description = "Hetzner datacenter location (e.g., hel1, fsn1, nbg1)"
  type        = string
  default     = "hel1"

  validation {
    condition     = contains(["fsn1", "nbg1", "hel1", "ash", "hil"], var.location)
    error_message = "Invalid location. Must be a known Hetzner datacenter: fsn1, nbg1, hel1, ash, hil."
  }
}

variable "image" {
  description = "OS image to use"
  type        = string
  default     = "ubuntu-24.04"

  validation {
    condition     = can(regex("^ubuntu-", var.image))
    error_message = "Image must start with 'ubuntu-' since this is an Ubuntu project."
  }
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = ""
}

variable "ssh_keys" {
  description = "SSH key IDs or names to attach in Hetzner"
  type        = list(string)
  default     = []
}

variable "hetzner_ssh_key_name" {
  description = "Name of a single SSH key registered in Hetzner"
  type        = string
  default     = ""
}

variable "labels" {
  description = "Labels to apply to resources"
  type        = map(string)
  default = {
    project    = "mcp-tooling"
    managed_by = "terraform"
  }
}
