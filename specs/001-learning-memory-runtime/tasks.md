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

**Purpose**: Shared state and config needed by all user stories.

- [ ] T004 Add config defaults for `supervisor.learning_judge`, `supervisor.learning_bus`, `supervisor.memory_tiers`, and `supervisor.learning_jobs` in `hermes_cli/config.py`
- [ ] T005 Create `hermes_cli/learning_jobs.py` for background job records and JSON status helpers
- [ ] T006 Add migration helpers for runtime learning tables in `hermes_cli/supervisor_memory.py` or a dedicated DB module
- [ ] T007 [P] Add tests for job records and migration idempotency in `tests/hermes_cli/test_learning_jobs.py`
- [ ] T008 [P] Add documentation of background execution limits in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Shared learning state can be initialized repeatedly without corrupting existing memory.

---

## Phase 3: User Story 1 - Judge Learning Candidates (Priority: P1)

**Goal**: Proposed candidates are judged by a separate fail-closed evaluator before promotion.

**Independent Test**: Run judge tests with approved, rejected, needs-human, timeout, and malformed output fixtures.

### Tests for User Story 1

- [ ] T009 [P] [US1] Add strict judge schema parse tests in `tests/hermes_cli/test_learning_judge.py`
- [ ] T010 [P] [US1] Add candidate approval/rejection transition tests in `tests/hermes_cli/test_learning_judge.py`
- [ ] T011 [P] [US1] Add CLI JSON smoke tests for `hermes memory judge-run --json` in `tests/hermes_cli/test_learning_judge.py`

### Implementation for User Story 1

- [ ] T012 [US1] Create `hermes_cli/learning_judge.py` with strict decision dataclasses and parser
- [ ] T013 [US1] Integrate auxiliary model task `learning_judge` with timeout and fail-closed handling in `hermes_cli/learning_judge.py`
- [ ] T014 [US1] Add candidate status transitions and judge decision persistence in `hermes_cli/supervisor_memory.py`
- [ ] T015 [US1] Add `hermes memory judge-run` CLI wiring in `hermes_cli/main.py`
- [ ] T016 [US1] Document judge/operator approval boundary in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Judge can approve low-risk candidates and reject malformed/risky candidates without enabling enforcement.

---

## Phase 4: User Story 2 - Durable Runtime Event Bus (Priority: P2)

**Goal**: Foreground runtime paths publish events that background consumers process asynchronously.

**Independent Test**: Publish and consume events with lease expiry, retry, failure, and idempotent duplicate handling.

### Tests for User Story 2

- [ ] T017 [P] [US2] Add event publish/consume tests in `tests/hermes_cli/test_learning_bus.py`
- [ ] T018 [P] [US2] Add lease reclaim and retry-limit tests in `tests/hermes_cli/test_learning_bus.py`
- [ ] T019 [P] [US2] Add CLI JSON smoke tests for `hermes memory bus` commands in `tests/hermes_cli/test_learning_bus.py`

### Implementation for User Story 2

- [ ] T020 [US2] Create `hermes_cli/learning_bus.py` with SQLite event table helpers
- [ ] T021 [US2] Add `hermes memory bus publish/list/consume` CLI wiring in `hermes_cli/main.py`
- [ ] T022 [US2] Publish policy audit events from `tools/terminal_tool.py` without blocking command execution
- [ ] T023 [US2] Publish task outcome and candidate events from existing learning rollup/reconcile paths in `hermes_cli/supervisor_memory.py`
- [ ] T024 [US2] Add bus metrics into sidecar output in `hermes_cli/supervisor_memory.py`

**Checkpoint**: Runtime learning events can be replayed and consumed after process restarts.

---

## Phase 5: User Story 3 - Retrieve And Inject Scoped Learning (Priority: P3)

**Goal**: Approved memory is retrieved by tier, scope, and evidence quality, then injected as advisory context.

**Independent Test**: Retrieval returns only scoped, approved, evidence-backed memory and excludes false positives.

### Tests for User Story 3

- [ ] T025 [P] [US3] Extend retrieval tier tests in `tests/hermes_cli/test_supervisor_memory.py`
- [ ] T026 [P] [US3] Add meta-search scope tests for tenant, repo, tool, and machine matching in `tests/hermes_cli/test_supervisor_memory.py`
- [ ] T027 [P] [US3] Add prompt injection budget tests in `tests/hermes_cli/test_kanban_db.py`

### Implementation for User Story 3

- [ ] T028 [US3] Add hot/warm/cold tier fields and transition helpers in `hermes_cli/supervisor_memory.py`
- [ ] T029 [US3] Extend `retrieve_learning_context` with tier-aware search and scoring in `hermes_cli/supervisor_memory.py`
- [ ] T030 [US3] Add config knobs for retrieval limits and tier thresholds in `hermes_cli/config.py`
- [ ] T031 [US3] Ensure worker context injection keeps the advisory warning in `hermes_cli/kanban_db.py`
- [ ] T032 [US3] Document retrieval and injection policy in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Retrieval improves prompt context without admitting unapproved or unrelated memory.

---

## Phase 6: User Story 4 - Memory Wiki And Dreaming (Priority: P4)

**Goal**: Approved memory can be compiled into wiki claims, and offline dreaming can emit proposals only.

**Independent Test**: Wiki claims and dreaming proposals are created from approved evidence but do not affect runtime until approved.

### Tests for User Story 4

- [ ] T033 [P] [US4] Add memory wiki compiler tests in `tests/hermes_cli/test_memory_wiki.py`
- [ ] T034 [P] [US4] Add dreaming proposal tests in `tests/hermes_cli/test_memory_dreaming.py`
- [ ] T035 [P] [US4] Add negative tests proving dreaming proposals are not injected or enforced in `tests/hermes_cli/test_memory_dreaming.py`

### Implementation for User Story 4

- [ ] T036 [US4] Create `hermes_cli/memory_wiki.py` for evidence-backed wiki claims
- [ ] T037 [US4] Create `hermes_cli/memory_dreaming.py` for proposal-only synthesis
- [ ] T038 [US4] Add `hermes memory wiki compile/status` CLI wiring in `hermes_cli/main.py`
- [ ] T039 [US4] Add `hermes memory dream run/status` CLI wiring in `hermes_cli/main.py`
- [ ] T040 [US4] Add wiki and dreaming sections to `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Durable knowledge and proposals exist, but speculative output cannot control live execution.

---

## Phase 7: User Story 5 - Observe Runtime Learning (Priority: P5)

**Goal**: Operators can inspect active and historical learning work across jobs, candidates, decisions, and policy audits.

**Independent Test**: JSON status commands and backend endpoints return filterable active/history records.

### Tests for User Story 5

- [ ] T041 [P] [US5] Add learning job list/filter tests in `tests/hermes_cli/test_learning_jobs.py`
- [ ] T042 [P] [US5] Add dashboard/backend API tests for learning jobs in `tests/plugins/test_kanban_dashboard_plugin.py`
- [ ] T043 [P] [US5] Add sidecar metrics regression tests in `tests/hermes_cli/test_supervisor_memory.py`

### Implementation for User Story 5

- [ ] T044 [US5] Add `hermes memory jobs list/status` CLI wiring in `hermes_cli/main.py`
- [ ] T045 [US5] Record learning jobs for sidecar, judge, bus consumer, wiki, dreaming, housekeeping, and reconcile paths
- [ ] T046 [US5] Add backend endpoints for active jobs, historical jobs, candidates, decisions, and policy audits under `plugins/kanban/dashboard/`
- [ ] T047 [US5] Add dashboard-facing DTOs and filters for date, repo, task, worker, status, and blocker fields
- [ ] T048 [US5] Document observability workflow in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Operator can see what ran, why it changed memory, what is blocked, and what remains advisory.

---

## Phase 8: Polish And Integration

- [ ] T049 Run focused learning and policy tests: `pytest tests/hermes_cli/test_supervisor_memory.py tests/hermes_cli/test_policy_engine.py tests/hermes_cli/test_config.py -q`
- [ ] T050 Run new learning framework tests under `tests/hermes_cli/test_learning_*.py`
- [ ] T051 Run VM smoke sequence for sidecar, judge, bus, retrieval, and policy audit
- [ ] T052 Update `docs/runtime-learning-enforcement.md` with implementation status and VM validation notes
- [ ] T053 Push branch and record commit hashes for local and VM deployments

## Dependencies & Execution Order

- Phase 1 and Phase 2 must complete before any user story implementation.
- User Story 1 is the MVP because judge approval is the safety gate.
- User Story 2 can begin after foundational DB helpers exist.
- User Story 3 can continue in parallel after tier fields are available.
- User Story 4 depends on approved memory from User Story 1 and retrieval/tier rules from User Story 3.
- User Story 5 can begin after job records are available and should expand as each sidecar path lands.

## Parallel Opportunities

- Test files for judge, bus, wiki, dreaming, and jobs can be developed in parallel.
- CLI contracts and docs can be updated in parallel with implementation after data-model fields stabilize.
- Dashboard/backend observability can start once `learning_jobs.py` exposes stable JSON.

## Implementation Strategy

### MVP First

1. Complete foundational config/state.
2. Implement learning judge with fail-closed behavior.
3. Validate candidate approval/rejection transitions.
4. Stop and test on the VM before adding bus, wiki, or dreaming.

### Incremental Delivery

1. Learning judge.
2. SQLite event bus.
3. Tiered retrieval and injection.
4. Wiki compiler.
5. Dreaming proposals.
6. Observability dashboard/API.
7. Future enforcement mode only after audit evidence, judge approval, and operator approval.
