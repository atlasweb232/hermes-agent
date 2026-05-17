# Hermes Runtime Learning Constitution

## Core Principles

### I. Evidence Before Memory
Hermes MUST treat explicit operator instructions, git state, tests, logs, and tool outputs as more authoritative than retrieved memory. Memory can advise, but it cannot override current evidence.

### II. Separation Of Learning Layers
Raw runtime events, curator candidates, judge decisions, approved memory, memory wiki knowledge, dreaming proposals, and enforcement policies MUST remain separate data layers with explicit promotion paths. No layer may silently mutate another layer.

### III. Human-Controlled Enforcement
Learning systems may propose and audit behavior changes automatically, but active enforcement requires both a valid judge decision and operator approval. Malformed, missing, or risky judge output MUST fail closed.

### IV. Bounded Background Work
Sidecars, curators, judges, wiki compilers, dreaming jobs, and housekeeping MUST run outside the foreground agent loop with explicit limits, leases, retries, and observable status. They must not stall normal chat, delegation, or terminal execution.

### V. Testable Runtime Contracts
Every runtime learning feature MUST expose deterministic CLI or API surfaces, structured JSON output, and focused tests for data transitions, failure modes, and safety gates.

## Runtime Constraints

- Default policy mode is advisory or audit-only unless explicitly configured otherwise.
- Secret-like, destructive, or privilege-changing commands are never rewritten by learned policy.
- Learning retrieval must be scoped, quality-gated, compact, and labeled as advisory.
- Background jobs must be idempotent and safe to rerun after process loss.
- Long-lived memory must carry evidence pointers, confidence, timestamps, and status.

## Development Workflow

- Implement in small independently testable slices: spec, tests, code, docs, then VM validation.
- Prefer SQLite-backed local durability before adding distributed infrastructure.
- Promote to Redis Streams or Kafka only when multi-process or multi-VM requirements make SQLite insufficient.
- Update architecture docs whenever a new runtime learning layer or promotion path is added.

## Governance

This constitution governs Spec Kit artifacts for Hermes runtime learning work. Changes require a new commit, architecture note, and migration guidance for existing memory state.

**Version**: 1.0.0 | **Ratified**: 2026-05-16 | **Last Amended**: 2026-05-16
