output "resource_group_name" {
  description = "Resource group name."
  value       = azurerm_resource_group.this.name
}

output "container_app_environment_id" {
  description = "Container Apps environment id."
  value       = azurerm_container_app_environment.this.id
}

output "runtime_container_app_name" {
  description = "Hermes runtime Container App name."
  value       = azurerm_container_app.runtime.name
}

output "runtime_container_app_fqdn" {
  description = "Hermes runtime ingress FQDN when external ingress is enabled."
  value       = try(azurerm_container_app.runtime.ingress[0].fqdn, null)
}

output "sidecar_container_app_name" {
  description = "Hermes sidecar Container App name."
  value       = azurerm_container_app.sidecar.name
}

output "eventhub_namespace_name" {
  description = "Event Hubs namespace name."
  value       = azurerm_eventhub_namespace.this.name
}

output "eventhub_topics" {
  description = "Hermes event topic names."
  value       = sort(keys(azurerm_eventhub.topics))
}

output "storage_account_name" {
  description = "ADLS Gen2 storage account name."
  value       = azurerm_storage_account.this.name
}

output "storage_containers" {
  description = "Hermes storage containers."
  value       = sort(keys(azurerm_storage_container.this))
}

output "key_vault_uri" {
  description = "Key Vault URI."
  value       = azurerm_key_vault.this.vault_uri
}

output "application_insights_connection_string" {
  description = "Application Insights connection string. Treat as operational config, not a secret."
  value       = azurerm_application_insights.this.connection_string
  sensitive   = true
}

output "postgres_fqdn" {
  description = "PostgreSQL server FQDN when enabled."
  value       = var.enable_postgres ? azurerm_postgresql_flexible_server.this[0].fqdn : null
}
