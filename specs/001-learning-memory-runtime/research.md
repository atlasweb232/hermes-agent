# Research: Runtime Learning Memory Framework

## Decision: SQLite Event Bus First

**Rationale**: Hermes already uses local state and CLI workflows. A SQLite-backed event bus gives durable async handoff, leases, retries, and auditability without adding Docker, Redis, or Kafka operational burden.

**Alternatives considered**:

- Kafka: too heavy for the current single-VM/local workflow.
- Redis Streams: reasonable second phase when multiple long-running workers need fanout.
- In-memory queues: lose evidence on process exit and cannot support replay.

## Decision: Learning Judge Fails Closed

**Rationale**: Goal judging can continue on judge failure, but learning approval cannot. A malformed or unavailable judge must leave candidates unapproved.

**Alternatives considered**:

- Fail-open: unsafe because it can promote noisy or risky candidates.
- Human-only approval: safe but too slow for routine low-risk memory curation.

## Decision: Enforcement Remains Audit-Only

**Rationale**: The current policy engine can detect matching policy candidates and record what it would do. Actual command rewrite requires a later deterministic enforcement design with judge plus operator approval.

**Alternatives considered**:

- Immediate rewrite: too risky for terminal commands and secrets.
- No policy engine: loses the ability to measure potential benefit.

## Decision: Memory Tiering Is Retrieval Policy, Not Storage Shortcut

**Rationale**: Hot, warm, and cold tiers control retrieval freshness, prompt budget, and curation level. They must not bypass evidence and approval requirements.

**Alternatives considered**:

- Store everything in hot memory: prompt bloat and stale lessons.
- Keep only cold wiki: misses useful in-session lessons.

## Decision: Dreaming Produces Proposals Only

**Rationale**: Dreaming can synthesize playbooks and improvement ideas, but it is speculative. Proposals must pass judge/operator gates before affecting runtime behavior.

**Alternatives considered**:

- Dreaming auto-applies policies: violates human-controlled enforcement.
- No dreaming: loses offline improvement opportunity.
