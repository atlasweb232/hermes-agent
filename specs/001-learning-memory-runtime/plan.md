# Implementation Plan: Runtime Learning Memory Framework

**Branch**: `132-learning-memory-runtime` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-learning-memory-runtime/spec.md`

## Summary

Extend the current Hermes runtime learning work from advisory retrieval and policy audit into a complete, auditable learning framework. The first slice is a supervisor orchestration protocol that converts user/dashboard requests into Spec Kit-preserved work, memory packets, planner packets, worker delegation packets, validation reports, and session summaries. Follow-on slices are a fail-closed learning judge, a SQLite-backed runtime event bus, hybrid metadata/lexical/vector/graph retrieval, tiered memory retrieval, memory wiki compilation, offline dreaming proposals, and learning observability. Enforcement remains audit-only until judge and operator approval are both present.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Existing Hermes CLI modules, `sqlite3`, SQLite FTS5, optional local vector backend such as `sqlite-vec`, `sqlite-vss`, or LanceDB, existing auxiliary model client, pytest, existing dashboard/backend patterns

**Storage**: Hermes `state.db` SQLite database, SQLite-backed metadata/graph/FTS indexes, optional local vector index, existing config YAML, future optional Redis/Kafka/vector DB only after SQLite/local limits are proven

**Testing**: pytest focused unit and integration tests under `tests/hermes_cli/` and `tests/tools/`

**Target Platform**: Linux/macOS developer and VM environments used by Hermes Agent

**Project Type**: Python CLI/runtime agent with optional dashboard/backend surfaces

**Performance Goals**: Foreground command/chat/delegation paths must not block on background learning jobs; retrieval must keep injected memory compact enough for prompt use

**Constraints**: Non-trivial implementation work must go through Spec Kit unless explicitly skipped with recorded reason; vector similarity never overrides hard metadata filters; fail-closed judge behavior; advisory/audit default; no secret storage in learned memory; no active enforcement without judge plus operator approval

**Scale/Scope**: Single-node SQLite-first implementation supporting later migration to Redis Streams or Kafka

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Evidence before memory: PASS. Retrieval, orchestration, and enforcement remain advisory unless current evidence supports action.
- Separation of learning layers: PASS. Data model preserves separate tables/records for raw events, candidates, decisions, memory, wiki, proposals, and policies.
- Human-controlled enforcement: PASS. Enforcement mode is explicitly out of MVP and requires future operator approval.
- Bounded background work: PASS. Event bus and jobs use leases, retries, intervals, and one-shot CLI execution; supervisor protocol uses explicit packets rather than hidden blocking work.
- Testable runtime contracts: PASS. Every story includes JSON CLI/API contracts, packet schemas, retrieval-index contracts, runtime gates, and focused pytest coverage.

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
│   ├── goal-allocation.md
│   ├── health-sidecar.md
│   ├── learning-state.md
│   ├── restart-recovery.md
│   └── task-graph.md
└── tasks.md
```

### Source Code (repository root)

```text
hermes_cli/
├── config.py
├── main.py
├── goal_allocator.py
├── health_sidecar.py
├── restart_recovery.py
├── runtime_orchestrator.py
├── runtime_packets.py
├── runtime_templates.py
├── policy_engine.py
├── supervisor_memory.py
├── learning_bus.py
├── learning_judge.py
├── memory_wiki.py
├── memory_dreaming.py
├── memory_index.py
├── memory_graph.py
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

hermes_cli/runtime_templates/
├── supervisor_intake.md
├── supervisor_initialization_protocol.md
├── memory_packet.md
├── speckit_planner_packet.md
├── worker_delegation_packet.md
├── worker_result.md
├── validation_report.md
└── session_summary.md
```

**Structure Decision**: Use existing Hermes CLI/runtime modules. Add small focused modules for orchestration, packets, templates, and learning responsibilities instead of expanding `supervisor_memory.py` indefinitely.

## Phase 0: Research

See [research.md](./research.md).

## Phase 1: Design And Contracts

See [data-model.md](./data-model.md), [quickstart.md](./quickstart.md), and [contracts/](./contracts/).

## Phase 12: Goal-Based Multi-Agent Allocation

See [contracts/goal-allocation.md](./contracts/goal-allocation.md) and [../../docs/multi-agent-allocation-architecture.md](../../docs/multi-agent-allocation-architecture.md).

This phase integrates upstream `/goal` continuation with deterministic worker allocation. `/goal` remains the continuation and pause/resume controller; the allocator owns worker ranking, latency budgets, attempt recording, worker health, fallback, and recovery decisions inside each bounded goal/task turn.

## Phase 13: Self-Healing Workflow Control Plane

See [contracts/task-graph.md](./contracts/task-graph.md), [contracts/health-sidecar.md](./contracts/health-sidecar.md), [contracts/restart-recovery.md](./contracts/restart-recovery.md), [contracts/worker-progress-context-gate.md](./contracts/worker-progress-context-gate.md), and [../../super-architecture.md](../../super-architecture.md).

This phase plugs the remaining stability layer around the allocator: supervisor-owned parallel task graph, worker progress/context gate, asynchronous health sidecar, and restart recovery. These services must be generic across chat, goal, dashboard, API, and worker workflows.

The immediate priority is context preservation. Worker streams must be visible through observability surfaces but remain store-only by default. The supervisor receives compact typed packets only at decision boundaries, while a low-cost progress summarizer sidecar can convert durable worker events into bounded checkpoints without blocking foreground work.

## Phase 14: Production Evaluation Harness

See [contracts/production-evaluation-harness.md](./contracts/production-evaluation-harness.md) and [../../docs/production-evaluation-harness-architecture.md](../../docs/production-evaluation-harness-architecture.md).

This phase creates a controlled upstream-vs-branch evaluation environment for long-horizon tasks. It must measure quality, latency, token/cost usage, context growth, memory usefulness, sidecar overhead, judge decisions, Slack alerts, and human-in-the-loop events before production rollout. The harness is the production gate for the memory framework, self-learning loop, sidecars, judges, multi-agent allocation, QA toolsets, and CI/CD integration.

## Phase 15: End-to-End Feature Testing And Feature Toggles

See [contracts/end-to-end-feature-testing.md](./contracts/end-to-end-feature-testing.md).

This phase adds a feature-by-feature E2E test matrix and runtime feature toggles. The goal is to validate each subsystem independently, prove disabled features do not leak behavior, and only then run aggregate benchmark scenarios. Feature toggles are also the operational safety mechanism for staged rollout, provider outages, cost control, and isolating faulty sidecars.

## Phase 16: Tenant Platform Onboarding And Scaling

See [../../docs/tenant-platform-architecture.md](../../docs/tenant-platform-architecture.md).

This phase defines the SaaS/control-plane layer around Hermes: tenant registry, repo onboarding, communication connectors, toolset profiles, runtime cells, budgets, admin observability, and tenant-scoped job submission. The recommended implementation path is a shared control plane plus isolated tenant runtime cells, starting with a local/dev adapter before committing to Kafka, Kubernetes, vector DB, or graph DB.

## Phase 17: Skill And Memory Pipeline

See [../../docs/skill-memory-pipeline-architecture.md](../../docs/skill-memory-pipeline-architecture.md).

This phase connects procedural skills to the memory infrastructure. Skills are retrieved and injected through the same classifier, tenant scope, safety, feature-toggle, and context-budget rules as memory packets. SkillClaw may provide skill evolution and distribution, but published skills must remain evidence-backed, validated, versioned, and approval-gated.

## Phase 18: Dreaming Integration Revision

See [../../docs/dreaming-integration-architecture.md](../../docs/dreaming-integration-architecture.md).

This phase revises dreaming for the tenant and skill platform. Dreaming stays proposal-only but can now explicitly propose skill candidates, skill repairs, CI/CD hardening, test gaps, routing improvements, cost optimizations, and architecture review items. Local dreaming remains tenant/repo scoped; global dreaming reads only redacted approved shareable memory/wiki evidence.

## Phase 19: Lesser-Model Corpus Remittance For External MLOps

See [../../docs/lesser-model-mlops-architecture.md](../../docs/lesser-model-mlops-architecture.md).

This phase separates offline model improvement from runtime memory. Hermes captures lesser-model failures, strong-model rectifications, validation evidence, and distilled lessons into approved training records, then remits reproducible bundles to configured storage for an external MLOps platform. The external MLOps platform owns batch or streaming fine-tuning, model registry, evaluation gates, serving, and rollout decisions.

## Phase 20: Azure Production Deployment Orchestration

See [contracts/azure-production-deployment.md](./contracts/azure-production-deployment.md) and [../../docs/azure-production-deployment-architecture.md](../../docs/azure-production-deployment-architecture.md).

This phase adds a production-safe Azure deployment workflow for Hermes platform infrastructure. Hermes chat can orchestrate deployment planning, preflight, apply, status, smoke, promote, and rollback, but paid or dangerous operations require explicit operator approval. The default path remains local/SQLite; Azure Event Hubs Kafka protocol, Redpanda/Kafka, storage, Key Vault, runtime cells, sidecars, and observability are introduced through staged deployment profiles and smoke/soak gates.

## Phase 21: Platform Hardening And Gap Closure

See [contracts/platform-hardening.md](./contracts/platform-hardening.md) and [../../docs/platform-hardening-gap-review.md](../../docs/platform-hardening-gap-review.md).

This phase closes the cross-cutting risks left after the memory, sidecar, dreaming, tenant, skill, MLOps, and Azure deployment work. It adds a shared approval ledger, effective runtime profile resolver, canonical bus envelope, sidecar budget governor, full context-gate coverage, memory quality lifecycle, dreaming backlog control, and Azure production hardening gates.

## Phase 22: Operator Dashboard And Approval UI

See [contracts/operator-dashboard.md](./contracts/operator-dashboard.md) and [../../docs/operator-dashboard-architecture.md](../../docs/operator-dashboard-architecture.md).

This phase turns the existing observability, tenant, approval, memory, bus, benchmark, and Azure deployment DTOs into a bounded operator dashboard. The UI must be lean, lazy-loaded, redacted, approval-ledger-backed, and read-only by default so it does not become a second unsafe control plane or a source of supervisor context bloat.

## Phase 23: Production Runtime Closure

See [contracts/production-runtime-closure.md](./contracts/production-runtime-closure.md) and [../../docs/production-runtime-closure-architecture.md](../../docs/production-runtime-closure-architecture.md).

This phase converts live VM smoke findings into a final production-grade closure pass. It fixes secret-safe capture before persistence, service-equivalent model-role resolution, Codex-backed goal judge invocation, sidecar service readiness, richer runtime-failure evidence, skill evolution E2E, and the final Claude/Codex/curator/judge/memory-injection production smoke. Enforcement remains disabled by default; this phase proves advisory learning is safe, observable, bounded, and useful before production rollout.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Multiple learning state types | Required to prevent raw events, proposals, wiki, and enforcement from collapsing into one unsafe memory store | A single `memory` table would make approval state and audit boundaries ambiguous |
| Background bus before distributed bus | Required to decouple foreground work without deploying Kafka/Redis | Direct synchronous sidecar calls would drag the agent loop and make failures user-visible |
| Side-by-side evaluation harness | Required to prove memory/sidecars/judges improve outcomes over upstream before production | Anecdotal task success cannot justify higher infrastructure and model cost |
| Tenant runtime cells | Required to isolate enterprise repos, secrets, worktrees, memory, connectors, and cost ledgers | One shared always-on Hermes process would make tenant leakage and cost attribution too risky |
| Skill evolution boundary | Required to turn repeated lessons into reusable procedures without making raw session data authoritative | Injecting whole skill libraries or auto-publishing generated skills would create context bloat and unsafe hidden policy |
| Proposal-only dreaming | Required to capture long-horizon improvement ideas without letting speculative synthesis mutate runtime | Letting dreaming write skills, config, goals, or policy directly would create unsafe autonomous drift |
| Operator dashboard | Required because CLI/Slack alone cannot safely operate multi-tenant jobs, approvals, deployments, sidecars, and costs at scale | Raw logs or chat transcripts would bloat context, leak data, and make approval decisions hard to audit |
| Corpus remittance for external MLOps | Required to improve cheaper coding models without allowing live runtime sidecars to train, register, or deploy models directly | Mixing fine-tuning into runtime memory would create safety, tenant, cost, and reproducibility failures |
| Gated Azure deployment orchestration | Required to let Hermes chat assist production rollout without blindly creating paid resources or mutating production traffic | Raw one-click deployment would be unsafe for cost, DNS, secrets, tenant data, and rollback correctness |
| Cross-cutting hardening phase | Required because approval, config, budget, bus, context, memory quality, and deployment hardening span many subsystems | Leaving each subsystem to solve these independently would create loopholes and inconsistent production behavior |
| Production runtime closure phase | Required because live VM smoke exposed integration gaps that unit tests did not catch: service PATH drift, unavailable goal judge, dead curator backend, sparse evidence, unproven skill loop, and pre-persistence secret capture | Treating the branch as production-ready after isolated tests would allow unsafe learning stores and prompt-dependent runtime behavior |
