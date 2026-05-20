# Azure Production Deployment Architecture

## Goal

Hermes should be able to guide an operator from local/dev runtime to Azure
staging and production without turning deployment into an unsafe one-click
mutation. The operator experience can feel one-click after prerequisites are
configured, but the platform must preserve plan, preflight, approval, smoke,
soak, promote, and rollback gates.

## Deployment Modes

### Local/Dev

- SQLite event bus and spool.
- Local filesystem/SQLite memory wiki backends.
- Optional local/fake vector and graph adapters.
- No Azure dependency.

### Azure Staging

- Runtime cells on Azure Container Apps, VM, or AKS.
- Sidecars as separate containers/processes.
- Event bus: Azure Event Hubs Kafka protocol first, or Redpanda/Kafka if full
  Kafka semantics are required.
- Storage: Azure Blob or ADLS Gen2.
- Secrets: Azure Key Vault.
- Observability: Hermes observability plus optional Azure Monitor.
- No production traffic until smoke and soak pass.

### Azure Production

- Same profile shape as staging with stricter approval and rollback gates.
- Runtime cells scale horizontally by tenant/workload.
- Sidecars scale independently from foreground chat/task execution.
- SQLite remains local spool/fallback, not the shared production bus.
- Production promotion requires operator approval.

## Chat-Orchestrated Deployment

Hermes chat may orchestrate:

```text
hermes deploy plan --target azure --profile production
hermes deploy preflight --target azure --profile production
hermes deploy apply --target azure --profile staging --require-approval
hermes deploy smoke --target azure --profile staging
hermes deploy soak --target azure --profile staging
hermes deploy promote --from staging --to production --require-approval
hermes deploy status --target azure
hermes deploy rollback --target azure --run-id <run_id>
```

The chat supervisor must stop for explicit operator approval before:

- creating paid resources
- changing DNS
- rotating secrets
- enabling production traffic
- deleting infrastructure
- promoting staging to production

## Azure Bus Choice

Preferred production path:

- Azure Event Hubs with Kafka protocol for managed operations.

Alternative path:

- Redpanda on AKS or a dedicated VM/container cluster when full Kafka
  semantics are required.

Default path:

- SQLite local queue/spool for dev and as broker-unavailable fallback.

The foreground runtime must not block when the Azure bus is unavailable.
Events should spool locally and a publish sidecar should retry later.

## Scalability Model

- Runtime cells scale by tenant, repo, or workload class.
- Sidecars consume from queues and scale independently.
- Memory wiki backends scale through object/state/index adapters.
- Global memory sync can use Event Hubs/Kafka topics when SQLite is no longer
  enough.
- Cost budgets and feature toggles decide which sidecars run and which model
  tier they use.

## Readiness Gates

Plan gate:

- resource diff
- estimated monthly cost
- required secrets
- risk list
- rollback path

Preflight gate:

- Azure account/subscription access
- regional quota
- provider registration
- Key Vault access
- storage access
- bus health or configured fallback
- DNS/network readiness

Smoke gate:

- runtime cell health
- sidecar health
- event produce/consume
- dead-letter/replay
- memory retrieval
- urgent Slack/connector route

Soak gate:

- 24-72 hour run before production promotion
- no foreground-blocking sidecar behavior
- cost/latency within threshold
- retry/backlog stable
- no tenant boundary leakage

Promotion gate:

- operator approval
- smoke/soak evidence
- rollback target
- production traffic plan

## First Implementation Slice

1. Deployment profile contract and DTOs.
2. Plan/preflight tests with fake Azure adapters.
3. Approval-gated apply run model.
4. Status and rollback DTOs.
5. Event Hubs/Redpanda bus deployment helper templates.
6. SQLite fallback/spool verification.
7. Smoke/soak checklist output.
8. CLI/API JSON surfaces.

No live Azure resources should be created by default tests.
