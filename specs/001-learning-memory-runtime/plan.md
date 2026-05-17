# Implementation Plan: Runtime Learning Memory Framework

**Branch**: `132-learning-memory-runtime` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-learning-memory-runtime/spec.md`

## Summary

Extend the current Hermes runtime learning work from advisory retrieval and policy audit into a complete, auditable learning framework. The next implementation slices are a fail-closed learning judge, a SQLite-backed runtime event bus, tiered memory retrieval, memory wiki compilation, offline dreaming proposals, and learning observability. Enforcement remains audit-only until judge and operator approval are both present.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Existing Hermes CLI modules, `sqlite3`, existing auxiliary model client, pytest, existing dashboard/backend patterns

**Storage**: Hermes `state.db` SQLite database, existing config YAML, future optional Redis/Kafka only after SQLite limits are proven

**Testing**: pytest focused unit and integration tests under `tests/hermes_cli/` and `tests/tools/`

**Target Platform**: Linux/macOS developer and VM environments used by Hermes Agent

**Project Type**: Python CLI/runtime agent with optional dashboard/backend surfaces

**Performance Goals**: Foreground command/chat/delegation paths must not block on background learning jobs; retrieval must keep injected memory compact enough for prompt use

**Constraints**: Fail-closed judge behavior; advisory/audit default; no secret storage in learned memory; no active enforcement without judge plus operator approval

**Scale/Scope**: Single-node SQLite-first implementation supporting later migration to Redis Streams or Kafka

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Evidence before memory: PASS. Retrieval and enforcement remain advisory unless current evidence supports action.
- Separation of learning layers: PASS. Data model preserves separate tables/records for raw events, candidates, decisions, memory, wiki, proposals, and policies.
- Human-controlled enforcement: PASS. Enforcement mode is explicitly out of MVP and requires future operator approval.
- Bounded background work: PASS. Event bus and jobs use leases, retries, intervals, and one-shot CLI execution.
- Testable runtime contracts: PASS. Every story includes JSON CLI/API contracts and focused pytest coverage.

## Project Structure

### Documentation (this feature)

```text
specs/001-learning-memory-runtime/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   ├── event-bus.md
│   └── learning-state.md
└── tasks.md
```

### Source Code (repository root)

```text
hermes_cli/
├── config.py
├── main.py
├── policy_engine.py
├── supervisor_memory.py
├── learning_bus.py
├── learning_judge.py
├── memory_wiki.py
├── memory_dreaming.py
└── learning_jobs.py

tools/
└── terminal_tool.py

plugins/
└── kanban/dashboard/

tests/
├── hermes_cli/
└── tools/

docs/
└── curator-policy-framework-architecture.md
```

**Structure Decision**: Use existing Hermes CLI/runtime modules. Add small focused modules for new learning responsibilities instead of expanding `supervisor_memory.py` indefinitely.

## Phase 0: Research

See [research.md](./research.md).

## Phase 1: Design And Contracts

See [data-model.md](./data-model.md), [quickstart.md](./quickstart.md), and [contracts/](./contracts/).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Multiple learning state types | Required to prevent raw events, proposals, wiki, and enforcement from collapsing into one unsafe memory store | A single `memory` table would make approval state and audit boundaries ambiguous |
| Background bus before distributed bus | Required to decouple foreground work without deploying Kafka/Redis | Direct synchronous sidecar calls would drag the agent loop and make failures user-visible |
