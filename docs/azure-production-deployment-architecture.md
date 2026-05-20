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

## Production Resource Targets

The Azure production profile should be explicit about which managed service is
used for each platform responsibility. The default target is managed Azure
services first, self-hosted infrastructure only when a managed service cannot
meet the requirement.

| Responsibility | Preferred Azure Target | Alternative | Notes |
| --- | --- | --- | --- |
| Runtime cells | Azure Container Apps | AKS or VM Scale Sets | Container Apps is the first production target for horizontally scaled Hermes runtime/sidecar containers. |
| Event bus | Azure Event Hubs with Kafka protocol | Redpanda on AKS or Kafka-compatible provider | Event Hubs is preferred for managed operations. Redpanda is used only when full Kafka semantics are required. |
| Local spool | SQLite per runtime cell | Local disk volume | Always remains enabled as broker-unavailable fallback. |
| Object storage | ADLS Gen2 / Azure Blob Storage | S3/GCS via external profile | Stores corpus bundles, wiki artifacts, deployment artifacts, benchmark outputs, and audit exports. |
| State store | Azure Database for PostgreSQL Flexible Server | Cosmos DB | PostgreSQL is the default relational state target; Cosmos is only for document/event-heavy profiles. |
| Secrets | Azure Key Vault | External secret manager | Stores provider keys, connector tokens, deployment tokens, and tenant secrets by reference only. |
| Observability | Azure Monitor + Application Insights + Log Analytics | Hermes local observability only | Production should export metrics/logs/traces without raw transcripts or secrets. |
| Public ingress | Azure Front Door | Application Gateway / Container Apps ingress | Front Door is preferred for global routing, TLS, WAF, and traffic split. |
| Private network | VNet integration + private endpoints | Public locked-down ingress | Production profiles should prefer private access to Key Vault, storage, database, and bus. |
| IaC output | Terraform first | Bicep optional | Hermes generates/validates artifacts and can apply only after explicit approval. |

The first Terraform scaffold lives at
[`infra/azure/terraform/hermes-platform/`](../infra/azure/terraform/hermes-platform/).
It creates the managed Azure baseline for Container Apps, Event Hubs, ADLS/Blob
containers, Key Vault, Log Analytics, Application Insights, and optional
PostgreSQL. It is validated as Terraform but must still be invoked through the
Phase 20 plan/preflight/approval workflow before any production apply.

## Object Storage Layout

Object storage is the durable artifact plane. It is not the runtime database.
For Azure, use ADLS Gen2 or Blob Storage containers with lifecycle policies.

Suggested containers:

```text
hermes-artifacts
  /deployments/<env>/<run_id>/
  /benchmarks/<env>/<run_id>/
  /worker-artifacts/<tenant>/<job_id>/

hermes-memory
  /wiki/<scope>/<tenant_or_global>/...
  /sync-deltas/<date>/...
  /indexes/lexical/<version>/...
  /indexes/vector/<version>/...
  /indexes/graph/<version>/...

hermes-corpus
  /training-corpus/tenant_id=<id>/scope=<scope>/dataset_family=<family>/date=<date>/...

hermes-audit
  /deployment-runs/<run_id>/
  /approval-records/<date>/
  /redaction-reports/<date>/
```

Rules:

- Never store raw secrets.
- Avoid raw transcripts unless a tenant explicitly enables an audited retention
  policy; default is compact redacted evidence only.
- Store hashes, manifests, approval refs, and source refs with every exported
  bundle.
- Use lifecycle policies for logs/artifacts and longer retention for approval
  and audit manifests.

## State Store Layout

PostgreSQL should hold durable control-plane state:

- tenants
- repos
- runtime cells
- connectors
- jobs/task graph/allocation state
- worker health
- feature toggles
- memory/wiki metadata
- deployment profiles
- deployment runs
- approval records
- cost ledgers

SQLite remains per-runtime-cell spool/cache. It is not the production
multi-tenant source of truth.

## Event Bus Topology

Production topics should be explicit:

```text
runtime.events
learning.events
memory.sync
observability.events
deployment.events
deadletter.events
```

Consumer groups:

```text
curator-sidecars
judge-sidecars
wiki-indexers
local-sync-sidecars
observability-writers
deployment-workers
corpus-remittance-workers
```

Fallback:

- If Event Hubs/Redpanda is unavailable, foreground runtime writes to SQLite
  spool and returns.
- A publish sidecar retries broker publish later.
- Bad events go to dead-letter with bounded redacted payloads.
- Replay must be idempotent using event ids and bundle hashes.

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

1. Deployment profile contract and DTOs with explicit Azure resource targets.
2. Plan/preflight tests with fake Azure adapters.
3. Terraform-first artifact generation with Bicep optional.
4. Approval-gated apply run model.
5. Status and rollback DTOs.
6. Event Hubs/Redpanda bus deployment helper templates.
7. Object storage, PostgreSQL/Cosmos, Key Vault, Azure Monitor, and ingress
   planning outputs.
8. SQLite fallback/spool verification.
9. Smoke/soak checklist output.
10. CLI/API JSON surfaces.

No live Azure resources should be created by default tests.
