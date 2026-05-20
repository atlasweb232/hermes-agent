# Platform Hardening Contract

## Shared Approval Ledger

Any production-relevant approval must include:

- approval id
- actor id
- actor role
- tenant id
- scope
- action
- target ref
- target hash
- created at
- expires at
- single-use or replay policy
- approval channel
- audit refs

Approval refs without these fields are advisory only.

## Effective Runtime Profile

The effective profile is a read-only merged view of:

- runtime feature toggles
- sidecar model tiers and role mapping
- tenant policy
- repo policy
- toolset profile
- deployment profile
- budget state
- worker health
- memory retrieval mode

It must explain every enabled/disabled decision and must not mutate state.

## Canonical Bus Envelope

Every event that can leave local process memory must include:

- event id
- event type
- tenant id
- repo id
- source subsystem
- idempotency key
- partition key
- created at
- schema version
- redaction state
- payload ref or bounded payload
- replay attempt
- dead-letter reason when applicable

Consumers must be idempotent on event id plus idempotency key.

## Sidecar Budget Governor

Before an LLM-backed sidecar runs, the governor must check:

- tenant budget
- task budget
- daily budget
- role tier
- estimated tokens
- estimated cost
- escalation reason
- exact-memory-hit skip eligibility

Budget denial must produce a bounded skipped/degraded record, not block
foreground execution.

## Context Gate Coverage

All worker execution paths must emit typed events and final packets. Raw
stdout, stderr, watch streams, logs, terminal tails, and unbounded model prose
must remain store-only artifacts.

## Memory Quality Lifecycle

Approved memory must support:

- confidence increase when helpful
- confidence decay when ignored or harmful
- stale suppression
- retirement
- compaction
- tenant/repo/scope preservation
- audit history preservation

## Dreaming Backlog Control

Dreaming proposals must be bounded by:

- tenant quota
- proposal type quota
- risk quota
- duplicate detection
- max age before archive
- operator-visible backlog summary

## Azure Production Hardening

Live Azure deployment profiles must explicitly decide:

- managed identity
- RBAC assignments
- private endpoints
- VNet integration
- ingress mode
- diagnostic settings
- storage lifecycle policies
- Key Vault access model
- rollback artifacts
- live apply approval
