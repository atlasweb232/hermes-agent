# Platform Hardening Gap Review

## Purpose

This review captures the remaining architectural gaps after the memory,
sidecar, dreaming, skill, tenant, MLOps corpus, and Azure deployment phases.
The platform is broadly safe-by-default, but production readiness depends on
closing several cross-cutting gaps that do not belong to only one subsystem.

## Closed Since First Review

- Azure deployment orchestration moved from test-local helpers into
  `hermes_cli/azure_deployment.py`.
- Phase 20 now has CLI surfaces and fake-adapter orchestration for
  plan/preflight/apply/status/smoke/soak/promote/rollback.
- Terraform scaffold exists for the first Azure resource shape.

## Remaining Gaps

### Phase 21 Closure

Phase 21 adds `hermes_cli/platform_hardening.py` as the shared deterministic
control-plane surface for the gaps below. The module provides redacted approval
ledger records, effective runtime profile resolution, canonical bus envelopes,
sidecar budget decisions, worker context-gate compliance checks, memory quality
lifecycle compaction, dreaming backlog summaries, Azure production hardening
evaluation, and a local E2E hardening fixture. These helpers are advisory and
local-testable; they do not enable enforcement or live provider mutations.

Live Azure production `apply` and `promote` decisions now consult the hardening
evaluator before returning the existing live-not-implemented block. Missing
managed identity, RBAC, private endpoints, VNet integration, private ingress,
diagnostics, storage lifecycle policy, Key Vault access, rollback artifacts, or
explicit approval blocks fail closed with bounded JSON evidence.

### Approval Boundary

Many features require operator approval, but approval refs are not yet backed
by one shared authorization ledger. Production actions need approval records
bound to actor, role, tenant, action, target hash, expiry, and non-replayable
id.

### Effective Runtime Profile

Feature toggles, sidecar model tiers, tenant policy, deployment profile, and
worker/toolset configuration can currently be reasoned about separately. A
single effective profile resolver is needed so operators can see the actual
runtime state before dispatch or deployment.

### Bus Envelope And Redrive

SQLite, Event Hubs, Redpanda, and Kafka paths need one canonical event envelope
with event id, idempotency key, tenant key, partition key, source, replay
attempt, redaction state, and dead-letter reason.

### Corpus Export Duplication

Older training-corpus export tasks overlap with the newer MLOps corpus
remittance boundary. They need to be reconciled to avoid two export systems
with different safety semantics.

### Budget Governor

Sidecar tiers and cost telemetry exist, but production needs a governor that
enforces per-tenant, per-task, and per-day budgets before LLM sidecars run.

### Context Gate Coverage

The context gate is specified and tested in isolation. Production needs
end-to-end tests proving every worker path uses typed packets and cannot stream
raw stdout/stderr/log tails directly into supervisor context.

### Memory Quality Lifecycle

Global lessons and hot cache have retrieval/feedback paths, but production
needs scheduled compaction, stale suppression, negative feedback demotion, and
quality metrics so old lessons do not pollute future tasks.

### Dreaming Backlog Control

Dreaming is proposal-only and gated, but it can propose many categories. It
needs quota/dedupe/backlog controls by tenant, proposal type, risk, and age.

### Azure Hardening

The Terraform scaffold is valid, but production hardening still needs managed
identity, RBAC, private endpoints, VNet integration, diagnostic settings,
storage lifecycle policies, Front Door/App Gateway, and Key Vault access
policy/RBAC decisions.

## Mitigation Principle

Do not add another autonomous loop. Add deterministic control-plane gates,
shared ledgers, effective-state resolution, and bounded background jobs. Keep
foreground runtime non-blocking and default all production mutations to
approval-gated dry-run behavior.
