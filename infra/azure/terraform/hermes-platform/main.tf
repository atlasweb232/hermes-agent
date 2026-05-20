locals {
  normalized_prefix = lower(replace(var.name_prefix, "-", ""))
  normalized_env    = lower(replace(var.environment, "-", ""))
  suffix            = random_string.suffix.result

  common_tags = merge(
    {
      platform    = "hermes"
      environment = var.environment
      managed_by  = "terraform"
    },
    var.tags,
  )

  eventhub_topics = toset([
    "runtime.events",
    "learning.events",
    "memory.sync",
    "observability.events",
    "deployment.events",
    "deadletter.events",
  ])

  storage_containers = toset([
    "hermes-artifacts",
    "hermes-memory",
    "hermes-corpus",
    "hermes-audit",
  ])

  storage_account_name = substr("${local.normalized_prefix}${local.normalized_env}${local.suffix}", 0, 24)
}

resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.common_tags
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "${var.name_prefix}-${var.environment}-logs"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.common_tags
}

resource "azurerm_application_insights" "this" {
  name                = "${var.name_prefix}-${var.environment}-appi"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"
  tags                = local.common_tags
}

resource "azurerm_storage_account" "this" {
  name                     = local.storage_account_name
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "ZRS"
  account_kind             = "StorageV2"
  is_hns_enabled           = true
  min_tls_version          = "TLS1_2"
  tags                     = local.common_tags

  blob_properties {
    delete_retention_policy {
      days = 30
    }
    container_delete_retention_policy {
      days = 30
    }
  }
}

resource "azurerm_storage_container" "this" {
  for_each              = local.storage_containers
  name                  = each.value
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

resource "azurerm_key_vault" "this" {
  name                       = substr("${var.name_prefix}-${var.environment}-kv-${local.suffix}", 0, 24)
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 30
  purge_protection_enabled   = true
  tags                       = local.common_tags
}

resource "azurerm_eventhub_namespace" "this" {
  name                = "${var.name_prefix}-${var.environment}-ehns-${local.suffix}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = var.eventhub_sku
  capacity            = var.eventhub_capacity
  tags                = local.common_tags
}

resource "azurerm_eventhub" "topics" {
  for_each            = local.eventhub_topics
  name                = each.value
  namespace_name      = azurerm_eventhub_namespace.this.name
  resource_group_name = azurerm_resource_group.this.name
  partition_count     = var.eventhub_partition_count
  message_retention   = var.eventhub_message_retention
}

resource "azurerm_postgresql_flexible_server" "this" {
  count = var.enable_postgres ? 1 : 0

  name                   = "${var.name_prefix}-${var.environment}-pg-${local.suffix}"
  resource_group_name    = azurerm_resource_group.this.name
  location               = azurerm_resource_group.this.location
  version                = "16"
  administrator_login    = var.postgres_admin_login
  administrator_password = var.postgres_admin_password
  sku_name               = var.postgres_sku_name
  storage_mb             = var.postgres_storage_mb
  tags                   = local.common_tags
}

resource "azurerm_postgresql_flexible_server_database" "hermes" {
  count = var.enable_postgres ? 1 : 0

  name      = "hermes"
  server_id = azurerm_postgresql_flexible_server.this[0].id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_container_app_environment" "this" {
  name                       = "${var.name_prefix}-${var.environment}-cae"
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  tags                       = local.common_tags
}

resource "azurerm_container_app" "runtime" {
  name                         = "${var.name_prefix}-${var.environment}-runtime"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"
  tags                         = local.common_tags

  template {
    min_replicas = var.runtime_min_replicas
    max_replicas = var.runtime_max_replicas

    container {
      name   = "hermes-runtime"
      image  = var.runtime_image
      cpu    = 1
      memory = "2Gi"

      env {
        name  = "HERMES_EVENT_BUS_BACKEND"
        value = "eventhubs_kafka"
      }
      env {
        name  = "HERMES_EVENT_BUS_FALLBACK_SPOOL"
        value = "sqlite"
      }
      env {
        name  = "HERMES_EVENTHUB_NAMESPACE"
        value = azurerm_eventhub_namespace.this.name
      }
      env {
        name  = "HERMES_STORAGE_ACCOUNT"
        value = azurerm_storage_account.this.name
      }
      env {
        name  = "HERMES_KEY_VAULT_URI"
        value = azurerm_key_vault.this.vault_uri
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.this.connection_string
      }
    }
  }

  ingress {
    external_enabled = var.container_ingress_external_enabled
    target_port      = 8080

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

resource "azurerm_container_app" "sidecar" {
  name                         = "${var.name_prefix}-${var.environment}-sidecar"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"
  tags                         = local.common_tags

  template {
    min_replicas = var.sidecar_min_replicas
    max_replicas = var.sidecar_max_replicas

    container {
      name   = "hermes-sidecar"
      image  = var.sidecar_image
      cpu    = 1
      memory = "2Gi"

      env {
        name  = "HERMES_EVENT_BUS_BACKEND"
        value = "eventhubs_kafka"
      }
      env {
        name  = "HERMES_EVENT_BUS_FALLBACK_SPOOL"
        value = "sqlite"
      }
      env {
        name  = "HERMES_EVENTHUB_NAMESPACE"
        value = azurerm_eventhub_namespace.this.name
      }
      env {
        name  = "HERMES_STORAGE_ACCOUNT"
        value = azurerm_storage_account.this.name
      }
      env {
        name  = "HERMES_KEY_VAULT_URI"
        value = azurerm_key_vault.this.vault_uri
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.this.connection_string
      }
    }
  }
}
