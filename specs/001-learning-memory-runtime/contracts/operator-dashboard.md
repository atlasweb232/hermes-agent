# Operator Dashboard Contract

## Purpose

The operator dashboard is a bounded UI over existing Hermes control-plane
surfaces. It must not become a raw-log browser, hidden prompt injector, or
parallel mutation path. All read paths consume redacted DTOs. All dangerous
write paths go through existing approval, deployment, tenant, memory, or
feature-toggle APIs.

## Primary Views

### Jobs

Inputs:

- `tenant_id`
- `repo_id`
- `date_from`
- `date_to`
- `status`
- `worker_family`
- `model`
- `blocked`
- `deployment_id`

Output row:

- job id
- tenant and repo
- task title
- status and blocker reason
- active worker and model
- last progress summary
- cost estimate
- latency summary
- memory packet count
- sidecar state summary
- deployment state when linked

### Job Detail

Lazy tabs:

- Overview
- Agents
- Spec Kit
- Memory
- Validation
- Sidecars
- Bus Events
- Costs
- Deployment
- Ask

Each tab returns bounded summaries and evidence refs. Raw transcripts, raw
worker stdout/stderr, provider logs, connector credentials, and full event
streams are forbidden.

### Approval Inbox

Approval items include:

- memory promotion
- dreaming conversion
- corpus export/remittance
- Azure apply/promote/destroy/DNS/secret rotation
- protected CI/CD operation
- policy enforcement

Every approval action must include actor, role, tenant, action, target hash,
expiry, evidence refs, and approval ledger id. Replays and mismatched target
hashes must fail closed.

### Sidecar Health

Rows include:

- sidecar role
- tier
- provider/model
- enabled/degraded/disabled state
- budget decision
- queue/backlog summary
- last run
- failure reason
- next eligible run

### Cost And Context

The dashboard shows cost and context attribution by tenant, repo, job, model,
worker, sidecar role, memory retrieval, Slack/dashboard Ask, deployment worker,
and benchmark run.

## Scoped Ask

Scoped Ask receives only a read-only evidence bundle:

- task packet summary
- selected memory packet summaries
- validation summaries
- worker attempt summaries
- sidecar summaries
- deployment summaries
- cost summaries

Scoped Ask has no mutation tools and cannot approve, deploy, edit memory,
change config, or modify repos.

## Safety Rules

- UI must lazy-load details.
- UI must never request raw transcripts by default.
- UI must display redaction state and evidence refs.
- Approval actions must call the shared approval ledger.
- Dangerous operations must require explicit operator confirmation.
- Tenant admins cannot access other tenants without explicit cross-tenant role.
- All DTOs must remain stable enough for API clients and tests.
