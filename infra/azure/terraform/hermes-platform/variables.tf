variable "name_prefix" {
  description = "Short lowercase prefix used for Azure resource names."
  type        = string
  default     = "hermes"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "environment must be one of dev, staging, or production."
  }
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Resource group to create for Hermes platform resources."
  type        = string
  default     = "rg-hermes-staging"
}

variable "tenant_id" {
  description = "Azure tenant id used by Key Vault."
  type        = string
}

variable "tags" {
  description = "Tags applied to all supported resources."
  type        = map(string)
  default     = {}
}

variable "runtime_image" {
  description = "Container image for Hermes runtime cells."
  type        = string
  default     = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
}

variable "sidecar_image" {
  description = "Container image for Hermes sidecar workers."
  type        = string
  default     = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
}

variable "runtime_min_replicas" {
  description = "Minimum Hermes runtime replicas."
  type        = number
  default     = 1
}

variable "runtime_max_replicas" {
  description = "Maximum Hermes runtime replicas."
  type        = number
  default     = 5
}

variable "sidecar_min_replicas" {
  description = "Minimum Hermes sidecar replicas."
  type        = number
  default     = 1
}

variable "sidecar_max_replicas" {
  description = "Maximum Hermes sidecar replicas."
  type        = number
  default     = 10
}

variable "eventhub_sku" {
  description = "Event Hubs namespace SKU."
  type        = string
  default     = "Standard"
}

variable "eventhub_capacity" {
  description = "Event Hubs throughput units."
  type        = number
  default     = 1
}

variable "eventhub_partition_count" {
  description = "Partition count for each Hermes event topic."
  type        = number
  default     = 2
}

variable "eventhub_message_retention" {
  description = "Retention in days for Event Hubs topics."
  type        = number
  default     = 1
}

variable "enable_postgres" {
  description = "Create Azure PostgreSQL Flexible Server for production control-plane state."
  type        = bool
  default     = false
}

variable "postgres_admin_login" {
  description = "PostgreSQL administrator login. Required when enable_postgres is true."
  type        = string
  default     = "hermesadmin"
}

variable "postgres_admin_password" {
  description = "PostgreSQL administrator password. Required when enable_postgres is true; do not commit tfvars containing this value."
  type        = string
  sensitive   = true
  default     = null
}

variable "postgres_sku_name" {
  description = "PostgreSQL Flexible Server SKU."
  type        = string
  default     = "B_Standard_B2s"
}

variable "postgres_storage_mb" {
  description = "PostgreSQL storage in MB."
  type        = number
  default     = 32768
}

variable "container_ingress_external_enabled" {
  description = "Expose the Hermes runtime Container App through public ingress. Production should normally use Front Door/Application Gateway in front."
  type        = bool
  default     = false
}
