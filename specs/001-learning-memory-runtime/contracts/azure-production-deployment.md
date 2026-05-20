# Azure Production Deployment Contract

## Purpose

Hermes may orchestrate Azure deployment workflows, but it must not blindly
create or mutate production infrastructure. The safe workflow is:

```text
plan -> preflight -> operator approval -> apply staging -> smoke -> soak
  -> operator approval -> promote production -> monitor -> rollback if needed
```

## Deployment Profiles

Profiles are versioned and explicit.

```json
{
  "profile_id": "azure-prod-eastus",
  "environment": "dev|staging|production",
  "subscription_id_ref": "secret-or-config-ref",
  "tenant_id": "tenant-id",
  "region": "eastus",
  "resource_group": "rg-hermes-prod",
  "runtime_cells": {
    "mode": "container_apps|vm|aks",
    "isolation": "pooled|dedicated",
    "min_instances": 1,
    "max_instances": 10
  },
  "event_bus": {
    "backend": "sqlite|eventhubs_kafka|redpanda|kafka",
    "fallback_spool": "sqlite",
    "topics": ["learning.events", "runtime.events", "memory.sync", "deadletter.events"]
  },
  "storage": {
    "object_store": "azure_blob|adls_gen2",
    "state_store": "sqlite|postgres|cosmos",
    "key_vault": "kv-hermes-prod",
    "containers": {
      "artifacts": "hermes-artifacts",
      "memory": "hermes-memory",
      "corpus": "hermes-corpus",
      "audit": "hermes-audit"
    }
  },
  "observability": {
    "backend": "hermes_local|azure_monitor|application_insights",
    "log_retention_days": 30
  },
  "network": {
    "private_ingress": true,
    "public_gateway": "frontdoor|app_gateway|none",
    "dns_zone_ref": "dns-ref"
  },
  "iac": {
    "format": "terraform|bicep",
    "artifact_store": "azure_blob",
    "apply_requires_approval": true
  },
  "approval": {
    "required_for_apply": true,
    "required_for_promote": true,
    "required_for_destroy": true
  }
}
```

## Plan Output

`hermes deploy plan --target azure --profile <id> --json` returns:

- resources to create/update
- resources not managed by Hermes
- IaC artifacts to generate
- estimated monthly cost range
- required secrets and config refs
- risk list
- smoke tests
- soak tests
- rollback plan
- approval requirements

The plan must be read-only.

## Preflight Output

`hermes deploy preflight --target azure --profile <id> --json` validates:

- Azure login/account identity
- subscription visibility
- quota for selected region
- resource provider registrations
- resource group existence or planned creation
- Key Vault access
- object/state storage access
- Event Hubs/Redpanda/Kafka choice
- PostgreSQL/Cosmos connectivity plan when configured
- Azure Monitor/Application Insights workspace plan when configured
- DNS/network prerequisites
- container/VM/AKS capacity
- required secrets are referenced, not printed
- SQLite fallback spool is configured

Preflight must fail closed if secrets, quotas, or approvals are missing.

## Apply Output

`hermes deploy apply --target azure --profile <id> --approval-id <id> --json`
executes only after explicit approval. It records:

- step id
- resource id
- status
- artifact refs
- sanitized logs
- rollback refs
- smoke-test refs

Default tests and dry runs must generate or validate IaC artifacts only. Live
apply is opt-in and approval-gated.

## Required Production Resource Classes

Azure production profiles must classify resources into these groups:

- compute: Container Apps, AKS, or VM/VMSS runtime cells
- bus: Event Hubs Kafka, Redpanda, Kafka, plus SQLite fallback spool
- object storage: ADLS Gen2 or Blob Storage containers
- state store: PostgreSQL Flexible Server or Cosmos DB
- secrets: Azure Key Vault
- observability: Azure Monitor, Application Insights, Log Analytics
- ingress/network: Front Door, Application Gateway, Container Apps ingress,
  VNet integration, private endpoints, DNS
- artifacts: Terraform/Bicep outputs, deployment manifests, smoke reports,
  rollback refs

## Production Promotion

Promotion requires:

- staging apply success
- smoke tests pass
- soak window complete
- no foreground-blocking sidecar regressions
- cost/latency within threshold
- urgent alert route verified
- operator approval

## Rollback

`hermes deploy rollback --target azure --profile <id> --run-id <id> --json`
must restore the previous known-good deployment or produce a blocked report
with required operator action.

## Non-Goals

- No implicit paid resource creation.
- No automatic DNS cutover.
- No secret printing.
- No production traffic promotion without approval.
- No foreground runtime dependency on Azure bus availability.
