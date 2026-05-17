# Tasks: Runtime Learning Memory Framework

**Input**: Design documents from `/specs/001-learning-memory-runtime/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required for all runtime state transitions, safety gates, and CLI JSON contracts.

**Organization**: Tasks are grouped by user story so each slice can be implemented and validated independently.

## Phase 1: Setup

**Purpose**: Preserve upstream merge and Spec Kit baseline before feature work.

- [ ] T001 Commit upstream merge and Spec Kit scaffolding in repository root
- [ ] T002 [P] Update `docs/curator-policy-framework-architecture.md` to reference `specs/001-learning-memory-runtime/`
- [ ] T003 [P] Add focused test fixtures for isolated Hermes home/state DB setup in `tests/hermes_cli/`

---

## Phase 2: Foundational

**Purpose**: Shared state, packet schemas, templates, and config needed by all user stories.

- [x] T004 Add config defaults for `supervisor.runtime_orchestration`, `supervisor.learning_judge`, `supervisor.learning_bus`, `supervisor.memory_tiers`, and `supervisor.learning_jobs` in `hermes_cli/config.py`
- [x] T005 Create `hermes_cli/runtime_packets.py` with dataclasses/schemas for supervisor task, planner, Spec Kit artifact, worker delegation, worker result, validation report, session summary, and worktree assignment packets
- [x] T006 Create `hermes_cli/runtime_templates.py` and `hermes_cli/runtime_templates/` template loader for supervisor and worker prompt templates
- [x] T007 Create `hermes_cli/learning_jobs.py` for background job records and JSON status helpers
- [x] T008 Add migration helpers for runtime learning and orchestration tables in `hermes_cli/supervisor_memory.py` or a dedicated DB module
- [x] T009 [P] Add tests for packet schema validation in `tests/hermes_cli/test_runtime_packets.py`
- [x] T010 [P] Add tests for template loading and required template names in `tests/hermes_cli/test_runtime_templates.py`
- [x] T011 [P] Add tests for job records and migration idempotency in `tests/hermes_cli/test_learning_jobs.py`
- [x] T012 [P] Add documentation of background execution and supervisor protocol limits in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Shared learning state can be initialized repeatedly without corrupting existing memory.

---

## Phase 3: User Story 1 - Supervisor Orchestration Protocol (Priority: P1)

**Goal**: Convert non-trivial user/dashboard requests into scoped, memory-aware, Spec Kit-preserved work before worker dispatch.

**Independent Test**: Run orchestration tests proving ambiguous requests ask clarifying questions, non-trivial work creates Spec Kit artifacts, worker dispatch requires valid packets, and completion requires validation evidence.

### Tests for User Story 1

- [x] T013 [P] [US1] Add supervisor initialization protocol tests in `tests/hermes_cli/test_runtime_orchestrator.py`
- [x] T014 [P] [US1] Add Spec Kit requirement and skip-reason tests in `tests/hermes_cli/test_runtime_orchestrator.py`
- [x] T015 [P] [US1] Add worker delegation packet validation tests in `tests/hermes_cli/test_runtime_orchestrator.py`
- [x] T016 [P] [US1] Add validation-report completion gate tests in `tests/hermes_cli/test_runtime_orchestrator.py`
- [x] T017 [P] [US1] Add dashboard-style ambiguous intake tests in `tests/hermes_cli/test_runtime_orchestrator.py`

### Implementation for User Story 1

- [x] T018 [US1] Create `hermes_cli/runtime_orchestrator.py` with supervisor initialization, clarification, Spec Kit gating, worker dispatch gating, validation gating, and session summary orchestration
- [x] T019 [US1] Add supervisor prompt templates in `hermes_cli/runtime_templates/supervisor_intake.md` and `hermes_cli/runtime_templates/supervisor_initialization_protocol.md`
- [x] T020 [US1] Add packet prompt templates in `hermes_cli/runtime_templates/memory_packet.md`, `speckit_planner_packet.md`, `worker_delegation_packet.md`, `worker_result.md`, `validation_report.md`, and `session_summary.md`
- [x] T021 [US1] Add `hermes runtime task init`, `hermes runtime speckit plan`, `hermes runtime delegate`, and `hermes runtime validate` CLI wiring in `hermes_cli/main.py`
- [x] T022 [US1] Add configurable planner/Spec Kit creator and worker routing defaults in `hermes_cli/config.py`
- [ ] T023 [US1] Integrate memory packet retrieval into supervisor task initialization using `hermes_cli/supervisor_memory.py`
- [x] T024 [US1] Document supervisor protocol, Spec Kit gating, planner/worker roles, and runtime gates in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Non-trivial implementation work cannot dispatch or complete without Spec Kit preservation, packet validation, and validation evidence.

---

## Phase 4: User Story 2 - Judge Learning Candidates (Priority: P2)

**Goal**: Proposed candidates are judged by a separate fail-closed evaluator before promotion.

**Independent Test**: Run judge tests with approved, rejected, needs-human, timeout, and malformed output fixtures.

### Tests for User Story 2

- [ ] T025 [P] [US2] Add strict judge schema parse tests in `tests/hermes_cli/test_learning_judge.py`
- [ ] T026 [P] [US2] Add candidate approval/rejection transition tests in `tests/hermes_cli/test_learning_judge.py`
- [ ] T027 [P] [US2] Add CLI JSON smoke tests for `hermes memory judge-run --json` in `tests/hermes_cli/test_learning_judge.py`

### Implementation for User Story 2

- [ ] T028 [US2] Create `hermes_cli/learning_judge.py` with strict decision dataclasses and parser
- [ ] T029 [US2] Integrate auxiliary model task `learning_judge` with timeout and fail-closed handling in `hermes_cli/learning_judge.py`
- [ ] T030 [US2] Add candidate status transitions and judge decision persistence in `hermes_cli/supervisor_memory.py`
- [ ] T031 [US2] Add `hermes memory judge-run` CLI wiring in `hermes_cli/main.py`
- [ ] T032 [US2] Document judge/operator approval boundary in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Judge can approve low-risk candidates and reject malformed/risky candidates without enabling enforcement.

---

## Phase 5: User Story 3 - Durable Runtime Event Bus (Priority: P3)

**Goal**: Foreground runtime paths publish events that background consumers process asynchronously.

**Independent Test**: Publish and consume events with lease expiry, retry, failure, and idempotent duplicate handling.

### Tests for User Story 3

- [ ] T033 [P] [US3] Add event publish/consume tests in `tests/hermes_cli/test_learning_bus.py`
- [ ] T034 [P] [US3] Add lease reclaim and retry-limit tests in `tests/hermes_cli/test_learning_bus.py`
- [ ] T035 [P] [US3] Add CLI JSON smoke tests for `hermes memory bus` commands in `tests/hermes_cli/test_learning_bus.py`

### Implementation for User Story 3

- [ ] T036 [US3] Create `hermes_cli/learning_bus.py` with SQLite event table helpers
- [ ] T037 [US3] Add `hermes memory bus publish/list/consume` CLI wiring in `hermes_cli/main.py`
- [ ] T038 [US3] Publish policy audit events from `tools/terminal_tool.py` without blocking command execution
- [ ] T039 [US3] Publish task outcome and candidate events from existing learning rollup/reconcile paths in `hermes_cli/supervisor_memory.py`
- [ ] T040 [US3] Add bus metrics into sidecar output in `hermes_cli/supervisor_memory.py`

**Checkpoint**: Runtime learning events can be replayed and consumed after process restarts.

---

## Phase 6: User Story 4 - Retrieve And Inject Scoped Learning (Priority: P4)

**Goal**: Approved memory is retrieved by tier, scope, and evidence quality, then injected as advisory context.

**Independent Test**: Retrieval returns only scoped, approved, evidence-backed memory and excludes false positives.

### Tests for User Story 4

- [ ] T041 [P] [US4] Extend retrieval tier tests in `tests/hermes_cli/test_supervisor_memory.py`
- [ ] T042 [P] [US4] Add meta-search scope tests for tenant, repo, tool, and machine matching in `tests/hermes_cli/test_supervisor_memory.py`
- [ ] T043 [P] [US4] Add prompt injection budget tests in `tests/hermes_cli/test_kanban_db.py`
- [ ] T044 [P] [US4] Add task classifier tests for tenant, repo, tool, task type, intent, entities, and signatures in `tests/hermes_cli/test_memory_retrieval.py`
- [ ] T045 [P] [US4] Add lexical index tests for commands, flags, file paths, branch names, tool names, and error signatures in `tests/hermes_cli/test_memory_index.py`
- [ ] T046 [P] [US4] Add vector index tests proving vector matches cannot bypass hard scope/status/evidence filters in `tests/hermes_cli/test_memory_index.py`
- [ ] T047 [P] [US4] Add graph index tests for node/edge creation, graph expansion, and explanation paths in `tests/hermes_cli/test_memory_graph.py`
- [ ] T048 [P] [US4] Add relevance scorer tests for exact match, lexical match, vector similarity, graph proximity, recency, confidence, and cross-scope penalties in `tests/hermes_cli/test_memory_retrieval.py`
- [ ] T049 [P] [US4] Add retrieval-run audit tests for filters, lexical/vector/graph candidates, rerank features, and packet output in `tests/hermes_cli/test_memory_retrieval.py`
- [ ] T050 [P] [US4] Add memory packet builder tests for top-k compaction, evidence labels, scope labels, and advisory header in `tests/hermes_cli/test_memory_retrieval.py`
- [ ] T051 [P] [US4] Add policy escalation tests for deterministic approved memory in `tests/hermes_cli/test_policy_engine.py`
- [ ] T052 [P] [US4] Add outcome feedback tests for helpful, irrelevant, harmful, and unknown memory in `tests/hermes_cli/test_memory_retrieval.py`

### Implementation for User Story 4

- [ ] T053 [US4] Create `hermes_cli/memory_retrieval.py` with task classifier, metadata normalizer, relevance scorer, retrieval-run audit, and memory packet builder
- [ ] T054 [US4] Create `hermes_cli/memory_index.py` with SQLite metadata, FTS5 lexical, and optional local vector backend abstractions
- [ ] T055 [US4] Create `hermes_cli/memory_graph.py` with SQLite node/edge tables and graph expansion helpers
- [ ] T056 [US4] Add hot/warm/cold tier fields and transition helpers in `hermes_cli/supervisor_memory.py`
- [ ] T057 [US4] Extend `retrieve_learning_context` to consume metadata filters, lexical/vector/graph candidates, reranking, and packet building in `hermes_cli/supervisor_memory.py`
- [ ] T058 [US4] Add config knobs for retrieval limits, scope penalties, lexical search, vector backend, graph expansion, packet size, and tier thresholds in `hermes_cli/config.py`
- [ ] T059 [US4] Add outcome feedback persistence and confidence/tier adjustment helpers in `hermes_cli/supervisor_memory.py`
- [ ] T060 [US4] Add deterministic policy escalation from approved memory to audit/advisory candidates in `hermes_cli/policy_engine.py`
- [ ] T061 [US4] Ensure worker context injection keeps the advisory warning in `hermes_cli/kanban_db.py`
- [ ] T062 [US4] Document hybrid retrieval, packet building, feedback, and escalation policy in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Retrieval improves prompt context without admitting unapproved or unrelated memory.

---

## Phase 7: User Story 5 - Memory Wiki And Dreaming (Priority: P5)

**Goal**: Approved memory can be compiled into wiki claims, and offline dreaming can emit proposals only.

**Independent Test**: Wiki claims and dreaming proposals are created from approved evidence but do not affect runtime until approved.

### Tests for User Story 5

- [ ] T063 [P] [US5] Add memory wiki compiler tests in `tests/hermes_cli/test_memory_wiki.py`
- [ ] T064 [P] [US5] Add dreaming proposal tests in `tests/hermes_cli/test_memory_dreaming.py`
- [ ] T065 [P] [US5] Add negative tests proving dreaming proposals are not injected or enforced in `tests/hermes_cli/test_memory_dreaming.py`

### Implementation for User Story 5

- [ ] T066 [US5] Create `hermes_cli/memory_wiki.py` for evidence-backed wiki claims
- [ ] T067 [US5] Create `hermes_cli/memory_dreaming.py` for proposal-only synthesis
- [ ] T068 [US5] Add `hermes memory wiki compile/status` CLI wiring in `hermes_cli/main.py`
- [ ] T069 [US5] Add `hermes memory dream run/status` CLI wiring in `hermes_cli/main.py`
- [ ] T070 [US5] Add wiki and dreaming sections to `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Durable knowledge and proposals exist, but speculative output cannot control live execution.

---

## Phase 8: User Story 6 - Observe Runtime Learning (Priority: P6)

**Goal**: Operators can inspect active and historical learning work across jobs, candidates, decisions, and policy audits.

**Independent Test**: JSON status commands and backend endpoints return filterable active/history records.

### Tests for User Story 6

- [ ] T071 [P] [US6] Add learning job list/filter tests in `tests/hermes_cli/test_learning_jobs.py`
- [ ] T072 [P] [US6] Add dashboard/backend API tests for learning jobs in `tests/plugins/test_kanban_dashboard_plugin.py`
- [ ] T073 [P] [US6] Add sidecar metrics regression tests in `tests/hermes_cli/test_supervisor_memory.py`

### Implementation for User Story 6

- [ ] T074 [US6] Add `hermes memory jobs list/status` CLI wiring in `hermes_cli/main.py`
- [ ] T075 [US6] Record learning jobs for sidecar, judge, bus consumer, wiki, dreaming, housekeeping, and reconcile paths
- [ ] T076 [US6] Add backend endpoints for active jobs, historical jobs, candidates, decisions, and policy audits under `plugins/kanban/dashboard/`
- [ ] T077 [US6] Add dashboard-facing DTOs and filters for date, repo, task, worker, status, and blocker fields
- [ ] T078 [US6] Document observability workflow in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Operator can see what ran, why it changed memory, what is blocked, and what remains advisory.

---

## Phase 9: Polish And Integration

- [ ] T079 Run focused learning and policy tests: `pytest tests/hermes_cli/test_supervisor_memory.py tests/hermes_cli/test_policy_engine.py tests/hermes_cli/test_config.py -q`
- [ ] T080 Run new learning framework tests under `tests/hermes_cli/test_learning_*.py`
- [ ] T081 Run runtime orchestration tests under `tests/hermes_cli/test_runtime_*.py`
- [ ] T082 Run hybrid retrieval tests under `tests/hermes_cli/test_memory_index.py tests/hermes_cli/test_memory_graph.py tests/hermes_cli/test_memory_retrieval.py`
- [ ] T083 Run VM smoke sequence for supervisor protocol, sidecar, judge, bus, retrieval, and policy audit
- [ ] T084 Update `docs/runtime-learning-enforcement.md` with implementation status and VM validation notes
- [ ] T085 Push branch and record commit hashes for local and VM deployments

## Dependencies & Execution Order

- Phase 1 and Phase 2 must complete before any user story implementation.
- User Story 1 is the MVP because every serious task must go through deterministic supervisor orchestration and Spec Kit preservation.
- User Story 2 depends on foundational DB helpers and provides the learning approval gate.
- User Story 3 can begin after foundational DB helpers exist.
- User Story 4 can continue in parallel after tier fields and packet schemas are available.
- User Story 5 depends on approved memory from User Story 2 and retrieval/tier rules from User Story 4.
- User Story 6 can begin after job records are available and should expand as each sidecar path lands.

## Parallel Opportunities

- Test files for runtime orchestration, judge, bus, wiki, dreaming, and jobs can be developed in parallel.
- CLI contracts and docs can be updated in parallel with implementation after data-model fields stabilize.
- Dashboard/backend observability can start once `learning_jobs.py` exposes stable JSON.

## Implementation Strategy

### MVP First

1. Complete foundational config/state.
2. Implement supervisor orchestration protocol with Spec Kit gating.
3. Validate packet schemas, prompt templates, worker dispatch gates, and completion gates.
4. Stop and test on the VM before adding judge, bus, wiki, or dreaming.

### Incremental Delivery

1. Supervisor orchestration protocol.
2. Learning judge.
3. SQLite event bus.
4. Hybrid metadata/lexical/vector/graph retrieval and injection.
5. Wiki compiler.
6. Dreaming proposals.
7. Observability dashboard/API.
8. Future enforcement mode only after audit evidence, judge approval, and operator approval.
