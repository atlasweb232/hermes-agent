# Operator Dashboard Architecture

## Goal

Hermes needs a production operator dashboard after the memory, sidecar, tenant,
bus, benchmark, and Azure deployment surfaces are available. The dashboard is
not a second agent. It is a bounded control plane UI over redacted backend DTOs.

## Principles

- Use existing backend DTOs first.
- Keep all dangerous actions behind the shared approval ledger.
- Prefer lazy-loaded detail drawers over loading full job/session state.
- Store raw logs and transcripts outside model context; show summaries and
  evidence refs.
- Make costs, context, sidecar usage, and worker degradation visible.
- Keep tenant scoping explicit on every query and mutation.

## Views

### Dashboard Home

- active jobs
- blocked jobs
- pending approvals
- sidecar degraded state
- budget warnings
- deployment warnings
- urgent route health

### Jobs

The jobs table is the primary operator surface. It supports tenant, repo, date,
status, worker, model, blocker, deployment, and cost filters. Rows are compact:
title, owner, status, current worker, last progress summary, cost, memory hit
count, and urgent state.

### Job Detail

Job detail is a lazy drawer or page. Tabs include Overview, Agents, Spec Kit,
Memory, Validation, Sidecars, Bus Events, Costs, Deployment, and Ask. Each tab
must call a scoped endpoint and return bounded redacted DTOs.

### Approval Inbox

The approval inbox groups high-risk actions:

- memory promotion
- dreaming conversion
- policy enforcement
- corpus export/remittance
- Azure apply/promote/destroy/DNS/secret rotation
- protected CI/CD operations

Approvals write through the shared approval ledger and must display expiry,
target hash, evidence refs, risk, scope, and actor role.

### Sidecar And Bus Health

Sidecar panels expose role, tier, model, budget decision, last run, backlog,
failure reason, and next eligible run. Bus panels expose backend, topic, lag,
dead-letter count, replay count, and SQLite spool state.

### Cost And Context

Cost views aggregate tokens, estimated cost, wall time, context admitted, memory
packet size, sidecar calls, worker attempts, and benchmark comparisons by tenant,
repo, job, model, worker, and sidecar role.

### Deployment

Deployment views consume Azure orchestration DTOs: plan, preflight, approval,
apply, smoke, soak, promote, rollback, and hardening failures. The dashboard may
request actions, but the backend must reject unsafe actions without an approval
ledger entry.

## Data Flow

```text
backend DTOs
  -> dashboard API routes
  -> compact list views
  -> lazy detail tabs
  -> approval ledger for dangerous actions
  -> scoped Ask with read-only evidence bundle
```

## Non-Goals

- No raw transcript browser in the MVP.
- No direct repo mutation from UI.
- No direct memory/policy/deployment mutation bypassing approval gates.
- No always-on LLM panel that reads full job history.
- No separate dashboard database until existing state surfaces prove inadequate.

## Rollout

1. Contract and architecture.
2. Backend route/DTO tests for all dashboard panes.
3. Minimal server-rendered or existing-dashboard UI shell.
4. Jobs list and detail drawer.
5. Approval inbox.
6. Sidecar/bus/cost/deployment panels.
7. Scoped Ask.
8. E2E dashboard smoke with seeded state.
