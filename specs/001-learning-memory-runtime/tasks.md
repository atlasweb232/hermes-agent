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
- [x] T023 [US1] Integrate memory packet retrieval into supervisor task initialization using `hermes_cli/supervisor_memory.py`
- [x] T024 [US1] Document supervisor protocol, Spec Kit gating, planner/worker roles, and runtime gates in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Non-trivial implementation work cannot dispatch or complete without Spec Kit preservation, packet validation, and validation evidence.

---

## Phase 4: User Story 2 - Judge Learning Candidates (Priority: P2)

**Goal**: Proposed candidates are judged by a separate fail-closed evaluator before promotion.

**Independent Test**: Run judge tests with approved, rejected, needs-human, timeout, and malformed output fixtures.

### Tests for User Story 2

- [x] T025 [P] [US2] Add strict judge schema parse tests in `tests/hermes_cli/test_learning_judge.py`
- [x] T026 [P] [US2] Add candidate approval/rejection transition tests in `tests/hermes_cli/test_learning_judge.py`
- [x] T027 [P] [US2] Add CLI JSON smoke tests for `hermes memory judge-run --json` in `tests/hermes_cli/test_learning_judge.py`

### Implementation for User Story 2

- [x] T028 [US2] Create `hermes_cli/learning_judge.py` with strict decision dataclasses and parser
- [x] T029 [US2] Integrate auxiliary model task `learning_judge` with timeout and fail-closed handling in `hermes_cli/learning_judge.py`
- [x] T030 [US2] Add candidate status transitions and judge decision persistence in `hermes_cli/supervisor_memory.py`
- [x] T031 [US2] Add `hermes memory judge-run` CLI wiring in `hermes_cli/main.py`
- [x] T032 [US2] Document judge/operator approval boundary in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Judge can approve low-risk candidates and reject malformed/risky candidates without enabling enforcement.

---

## Phase 5: User Story 3 - Durable Runtime Event Bus (Priority: P3)

**Goal**: Foreground runtime paths publish events that background consumers process asynchronously.

**Independent Test**: Publish and consume events with lease expiry, retry, failure, and idempotent duplicate handling.

### Tests for User Story 3

- [x] T033 [P] [US3] Add event publish/consume tests in `tests/hermes_cli/test_learning_bus.py`
- [x] T034 [P] [US3] Add lease reclaim and retry-limit tests in `tests/hermes_cli/test_learning_bus.py`
- [x] T035 [P] [US3] Add CLI JSON smoke tests for `hermes memory bus` commands in `tests/hermes_cli/test_learning_bus.py`

### Implementation for User Story 3

- [x] T036 [US3] Create `hermes_cli/learning_bus.py` with SQLite event table helpers
- [x] T037 [US3] Add `hermes memory bus publish/list/consume` CLI wiring in `hermes_cli/main.py`
- [x] T038 [US3] Publish policy audit events from `tools/terminal_tool.py` without blocking command execution
- [x] T039 [US3] Publish task outcome and candidate events from existing learning rollup/reconcile paths in `hermes_cli/supervisor_memory.py`
- [x] T040 [US3] Add bus metrics into sidecar output in `hermes_cli/supervisor_memory.py`

**Checkpoint**: Runtime learning events can be replayed and consumed after process restarts.

---

## Phase 6: User Story 4 - Retrieve And Inject Scoped Learning (Priority: P4)

**Goal**: Approved memory is retrieved by tier, scope, and evidence quality, then injected as advisory context.

**Independent Test**: Retrieval returns only scoped, approved, evidence-backed memory and excludes false positives.

### Tests for User Story 4

- [x] T041 [P] [US4] Extend retrieval tier tests in `tests/hermes_cli/test_supervisor_memory.py`
- [x] T042 [P] [US4] Add meta-search scope tests for tenant, repo, tool, and machine matching in `tests/hermes_cli/test_supervisor_memory.py`
- [x] T043 [P] [US4] Add prompt injection budget tests in `tests/hermes_cli/test_kanban_db.py`
- [x] T044 [P] [US4] Add task classifier tests for tenant, repo, tool, task type, intent, entities, and signatures in `tests/hermes_cli/test_memory_retrieval.py`
- [x] T045 [P] [US4] Add lexical index tests for commands, flags, file paths, branch names, tool names, and error signatures in `tests/hermes_cli/test_memory_index.py`
- [x] T046 [P] [US4] Add vector index tests proving vector matches cannot bypass hard scope/status/evidence filters in `tests/hermes_cli/test_memory_index.py`
- [x] T047 [P] [US4] Add graph index tests for node/edge creation, graph expansion, and explanation paths in `tests/hermes_cli/test_memory_graph.py`
- [x] T048 [P] [US4] Add relevance scorer tests for exact match, lexical match, vector similarity, graph proximity, recency, confidence, and cross-scope penalties in `tests/hermes_cli/test_memory_retrieval.py`
- [x] T049 [P] [US4] Add retrieval-run audit tests for filters, lexical/vector/graph candidates, rerank features, and packet output in `tests/hermes_cli/test_memory_retrieval.py`
- [x] T050 [P] [US4] Add memory packet builder tests for top-k compaction, evidence labels, scope labels, and advisory header in `tests/hermes_cli/test_memory_retrieval.py`
- [x] T051 [P] [US4] Add policy escalation tests for deterministic approved memory in `tests/hermes_cli/test_policy_engine.py`
- [x] T052 [P] [US4] Add outcome feedback tests for helpful, irrelevant, harmful, and unknown memory in `tests/hermes_cli/test_memory_retrieval.py`

### Implementation for User Story 4

- [x] T053 [US4] Create `hermes_cli/memory_retrieval.py` with task classifier, metadata normalizer, relevance scorer, retrieval-run audit, and memory packet builder
- [x] T054 [US4] Create `hermes_cli/memory_index.py` with SQLite metadata, FTS5 lexical, and optional local vector backend abstractions
- [x] T055 [US4] Create `hermes_cli/memory_graph.py` with SQLite node/edge tables and graph expansion helpers
- [x] T056 [US4] Add hot/warm/cold tier fields and transition helpers in `hermes_cli/supervisor_memory.py`
- [x] T057 [US4] Extend `retrieve_learning_context` to consume metadata filters, lexical/vector/graph candidates, reranking, and packet building in `hermes_cli/supervisor_memory.py`
- [x] T058 [US4] Add config knobs for retrieval limits, scope penalties, lexical search, vector backend, graph expansion, packet size, and tier thresholds in `hermes_cli/config.py`
- [x] T059 [US4] Add outcome feedback persistence and confidence/tier adjustment helpers in `hermes_cli/supervisor_memory.py`
- [x] T060 [US4] Add deterministic policy escalation from approved memory to audit/advisory candidates in `hermes_cli/policy_engine.py`
- [x] T061 [US4] Ensure worker context injection keeps the advisory warning in `hermes_cli/kanban_db.py`
- [x] T062 [US4] Document hybrid retrieval, packet building, feedback, and escalation policy in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Retrieval improves prompt context without admitting unapproved or unrelated memory.

---

## Phase 7: User Story 5 - Memory Wiki And Dreaming (Priority: P5)

**Goal**: Approved memory can be compiled into scoped wiki claims for retrieval/indexing/training-data pipelines, and offline dreaming can emit proposals only.

**Independent Test**: Wiki claims and dreaming proposals are created from approved evidence, wiki claims are eligible for advisory retrieval/indexing, and dreaming proposals do not affect runtime until converted through judge/operator gates.

### Tests for User Story 5

- [x] T063 [P] [US5] Add memory wiki compiler tests in `tests/hermes_cli/test_memory_wiki.py` covering scoped evidence-backed claims, deduplication, confidence, safety metadata, index payloads, and training payloads
- [x] T063A [P] [US5] Add migration training-corpus tests in `tests/hermes_cli/test_memory_wiki.py` covering legacy repo refs, target repo refs, before/after commit refs, diff summaries, validation evidence, failure/repair labels, and drift-evaluation anchors
- [x] T064 [P] [US5] Add dreaming proposal tests in `tests/hermes_cli/test_memory_dreaming.py` covering strict JSON schema parsing, proposal generation from wiki claims, repeated failures, job history, policy audits, worker outcomes, manual trigger metadata, and sidecar-interval trigger metadata
- [x] T065 [P] [US5] Add negative tests proving dreaming proposals are not injected, indexed as approved memory, applied to config, queued as goals, or enforced in `tests/hermes_cli/test_memory_dreaming.py`
- [x] T065A [P] [US5] Add deterministic dreaming validator tests for missing evidence refs, secret leakage, destructive commands, unsupported scope broadening, duplicate proposals, cross-tenant sharing, enforcement/config mutation requests, direct wiki writes, direct training exports, and direct goal queueing
- [x] T065B [P] [US5] Add sidecar scheduling tests proving dreaming is skipped by default, runs only when `supervisor.dreaming.enabled=true`, respects `interval_seconds`, records learning jobs, and never blocks rollup/monitor/policy/housekeeping results

### Implementation for User Story 5

- [x] T066 [US5] Create `hermes_cli/memory_wiki.py` for evidence-backed wiki claims with tenant/repo/platform/tool scope, safety/shareability flags, index payloads, curated training payloads, and migration intelligence records
- [x] T066A [US5] Add training corpus export builders for dataset families: `repo_migration_plan`, `migration_failure_repair`, `before_after_diff`, `validation_recipe`, `architecture_pattern`, and `policy_playbook`
- [x] T066B [US5] Add redaction/export eligibility validators so training records are derived from curated wiki/approved-memory records, never raw transcripts or raw logs, and preserve cross-tenant shareability boundaries
- [x] T067 [US5] Create `hermes_cli/memory_dreaming.py` for proposal-only synthesis with evidence-only input packets, strict output schema, deterministic validators, stable proposal ids, duplicate detection, narrow default scope, risk labels, trigger metadata, audit trail, and kill-switch config
- [x] T068 [US5] Add separate dreaming proposal storage/status helpers so proposals cannot be returned by approved-memory retrieval, wiki compilation, training export, goal queueing, or the policy engine until converted through judge/operator gates
- [x] T069 [US5] Add `hermes memory wiki compile/status` CLI wiring in `hermes_cli/main.py`, publishing wiki events to the learning bus and recording wiki learning jobs
- [x] T070 [US5] Add `hermes memory dream run/status` CLI wiring in `hermes_cli/main.py`, publishing proposal events to the learning bus and recording dreaming learning jobs; manual CLI is for testing/operator runs, not the primary production trigger
- [x] T070A [US5] Add config knobs for `supervisor.dreaming.enabled`, `provider`, `model`, `allow_llm`, `allow_cross_tenant`, `allow_policy_proposals`, `require_judge`, `require_operator_approval`, `max_proposals_per_run`, `evidence_window`, `timeout_seconds`, `run_on_start`, and `interval_seconds`; default `enabled=false`
- [x] T070D [US5] Extend `run_learning_sidecar` so service-driven sidecar ticks call dreaming only when enabled and due, include dreaming status/metrics in sidecar JSON, and continue other sidecar blocks if dreaming fails or times out
- [x] T070E [US5] Add judge/operator conversion path for dreaming proposals so approved proposals may become memory candidates, wiki updates, tests/playbooks, or policy candidates only after both gates pass
- [x] T070B [US5] Add wiki, dreaming, training-data, native goal-loop integration, and risk-mitigation sections to `docs/curator-policy-framework-architecture.md`
- [x] T070C [US5] Document migration intelligence corpus design, required repo/commit/evidence refs, dataset families, and drift-evaluation anchors in `docs/curator-policy-framework-architecture.md`
- [x] T070F [US5] Add configurable discussion memory wiki storage root, local capacity guardrails, raw retention settings, hot-cache TTL, and backend choices for local/S3/Postgres/vector/graph storage
- [x] T070G [US5] Add discussion capture, claim extraction, citation validation, wiki compilation, index update, and sync sidecar task definitions with bounded leases, timeouts, and non-blocking learning-job observability
- [x] T070H [US5] Add discussion-level wiki schemas for session summaries, extracted claims, citations/evidence refs, domain/global scope, approval provenance, sensitivity labels, and cross-device sync eligibility
- [x] T070I [US5] Add hybrid index update path for discussion wiki claims: lexical FTS, vector payloads, graph edges, and scoped retrieval packets for global Hermes consumption
- [x] T070J [US5] Add separate configured model roles for LLM-backed discussion sidecars: discussion capture, claim extractor, wiki compiler, dreaming, curator, learning judge, and deterministic-first citation validator
- [x] T070K [US5] Add tests proving generated artifacts cannot be approved by the same sidecar invocation/session that created them, even when both roles use Codex
- [x] T070L [US5] Create `docs/global-memory-wiki-architecture.md` covering central global wiki storage, configurable object/state/index backends, Kafka-compatible bus strategy, metadata schema, dedupe/reconcile workflow, and global sidecars
- [x] T070M [US5] Add global memory config defaults for object store, state store, lexical/vector/graph indexes, local cache, raw retention, and sync eligibility
- [x] T070N [US5] Add global memory bus adapter interface with SQLite local backend and Kafka/Redpanda-compatible backend options
- [x] T070O [US5] Add global proposal metadata validators and idempotency keys for randomly arriving chunks from many Hermes instances
- [x] T070P [US5] Add global dedupe/reconcile sidecar tests for exact duplicate, near duplicate, same evidence, same topic, conflict, and supersedes classes
- [x] T070Q [US5] Add global index fanout tasks for lexical, vector, and graph stores after canonical approval
- [x] T070R [US5] Add tiered sidecar model deployment config so programmatic, low-cost reasoning, balanced reasoning, and strong reasoning roles can be routed transparently to DeepSeek, MiniMax, Codex, Ollama, or future hosted/local providers
- [x] T070S [US5] Update model-role tests and architecture docs to prove role-specific overrides win over tier defaults and judges/approval gates remain on the strong reasoning tier by default
- [x] T070T [US5] Add CLI/backend tier configuration surfaces so operators can change a tier once through `hermes config tier set ...` or `/api/model/tiers/{tier}` instead of editing every sidecar role
- [x] T070U [US5] Add configurable media toolset surfaces for voice/realtime providers, MiniMax `speech-2.8`, xAI/Grok voice, OpenAI `gpt-realtime-2`, and direct Nano Banana Pro image-generation selection

**Checkpoint**: Durable knowledge and proposals exist, but speculative output cannot control live execution.

---

## Phase 8: User Story 6 - Observe Runtime Learning (Priority: P6)

**Goal**: Operators can inspect tenant-scoped active and historical learning/task work across jobs, candidates, decisions, policy audits, evidence bundles, and read-only scoped analysis.

**Independent Test**: JSON status commands and backend endpoints return tenant/repo/task-filtered active/history records, line-item detail bundles, and read-only scoped analysis responses.

### Tests for User Story 6

- [x] T071 [P] [US6] Add learning job list/filter tests in `tests/hermes_cli/test_learning_jobs.py` for tenant, repo, task, worker, status, date range, blocker, and job type filters
- [x] T071A [P] [US6] Add observability line-item and evidence-bundle tests in `tests/hermes_cli/test_observability.py` covering task description, initial assignment, agents, Spec Kit refs, validation refs, memory refs, event refs, blockers, and no raw transcript leakage
- [x] T071B [P] [US6] Add scoped analysis tests in `tests/hermes_cli/test_observability.py` proving tenant/repo/task scope, read-only repo mode, evidence citations, and no mutation authority
- [x] T072 [P] [US6] Add dashboard/backend API tests for tenant-scoped job/task list, line-item detail, evidence bundle, and Ask analysis endpoints in `tests/plugins/test_kanban_dashboard_observability.py`
- [x] T073 [P] [US6] Add sidecar metrics regression tests in `tests/hermes_cli/test_supervisor_memory.py`

### Implementation for User Story 6

- [x] T074 [US6] Add `hermes memory jobs list/status` CLI wiring in `hermes_cli/main.py`
- [x] T075 [US6] Record learning jobs for sidecar, judge, bus consumer, wiki, dreaming, housekeeping, and reconcile paths
- [x] T075A [US6] Create `hermes_cli/observability.py` for tenant-scoped line items, evidence bundles, filter DTOs, and read-only analysis request helpers
- [x] T075B [US6] Add `hermes memory observe list/detail/ask --json` CLI surfaces for tenant-scoped list rows, line-item drilldown, and scoped read-only LLM analysis
- [x] T076 [US6] Add backend endpoints for active jobs, historical jobs, candidates, decisions, policy audits, line-item detail, evidence bundles, and scoped analysis under `plugins/kanban/dashboard/`
- [x] T077 [US6] Add lean dashboard DTOs and lazy detail tabs for tenant selector, repo filter, task/job list, Overview, Agents, Spec Kit, Memory, Validation, Events, and Ask
- [x] T077A [US6] Add read-only repo query integration for scoped analysis, guarded by tenant/repo/task scope and disabled mutation tools
- [x] T078 [US6] Document tenant-scoped observability, line-item drilldown, evidence bundles, scoped Ask analysis, and no-mutation guardrails in `docs/curator-policy-framework-architecture.md`

**Checkpoint**: Operator can see what ran, open each line item, inspect evidence, and ask scoped analytical questions without giving the analysis path mutation authority.

---

## Phase 9: User Story 7 - Convergent Supervisor Control Plane (Priority: P7)

**Goal**: Long-running delegated work converges through leases, heartbeats, drift detection, validation gates, recovery packets, and worker reallocation.

**Independent Test**: Simulate stale workers, repeated errors, no-progress loops, failed validation, and `/goal` continuation; verify supervisor override/reassignment behavior is deterministic and preserves evidence.

### Tests for User Story 7

- [x] T079 [P] [US7] Add supervisor task ledger schema tests in `tests/hermes_cli/test_supervisor_control_plane.py` covering task states, worker ownership, lease expiry, heartbeat, retry budget, Spec Kit refs, git refs, and recovery history
- [x] T080 [P] [US7] Add stale heartbeat and lease reclaim tests proving stale tasks are marked reclaimable without blocking on worker processes
- [x] T081 [P] [US7] Add loop/drift detector tests for repeated command/error signatures, unchanged git/test/progress state, invalid worker results, and retry budget exhaustion
- [x] T082 [P] [US7] Add recovery packet tests covering partial diff/log summaries, failed commands, validation failures, memory packet refs, and next-worker recommendations
- [x] T083 [P] [US7] Add `/goal` integration tests proving goal continuation cannot override reclaimed, blocked, validation-failed, or reassigned task state

### Implementation for User Story 7

- [x] T084 [US7] Create `hermes_cli/supervisor_control_plane.py` with task ledger, heartbeat, lease, recovery packet, override action, and reassignment helpers
- [x] T085 [US7] Add SQLite tables for supervisor task ledger entries, worker heartbeats, recovery packets, and override actions
- [x] T086 [US7] Add progress evaluator and loop detector using heartbeat age, repeated signatures, git/test delta, invalid result count, elapsed time, and retry budget
- [x] T087 [US7] Add supervisor override actions: interrupt, request status, pause, block, reclaim, reassign, escalate, and abandon with audit records
- [x] T088 [US7] Add reallocation policy config for lease duration, heartbeat timeout, no-progress window, retry budget, worker fallback order, and escalation reviewer
- [x] T089 [US7] Add CLI/backend-compatible JSON surfaces for task ledger status, heartbeat list, recovery packets, and override actions
- [x] T090 [US7] Integrate `/goal` as optional continuation metadata only, ensuring supervisor ledger/validation/reassignment remains authoritative
- [x] T091 [US7] Update `docs/curator-policy-framework-architecture.md` with convergence workflow, `/goal` boundaries, override rules, and reassignment sequence

**Checkpoint**: Stuck or drifting delegated work can be reclaimed and reassigned with evidence, and only supervisor validation can complete the task.

---

## Phase 9A: Native Goal Continuation And Judge Sidecar Integration (Priority: P7)

**Goal**: Pull the useful upstream `/goal` judge behavior into the supervisor control plane so long-running tasks can continue toward a goal without giving the goal loop authority over validation, reassignment, policy, memory, or operator approval.

**Independent Test**: Create a supervisor task with a task-level goal, evaluate a worker response with a fake judge, verify continuation prompts are produced only for healthy active tasks, verify blocked/reclaimed/reassigned tasks stop before the judge runs, and verify `done` does not auto-complete the supervisor ledger.

### Tests for Goal Continuation Integration

- [x] T091A [P] [US7] Add goal prompt tests proving upstream goal judge prompts include current time context in `tests/hermes_cli/test_goals.py`
- [x] T091B [P] [US7] Add supervisor task goal tests for continuation, blocked-state guardrails, budget pause, done-without-auto-completion, and upsert preservation in `tests/hermes_cli/test_supervisor_control_plane.py`
- [x] T091C [P] [US7] Add observability tests proving supervisor task line items expose goal status and goal judge references in `tests/hermes_cli/test_observability.py`

### Implementation for Goal Continuation Integration

- [x] T091D [US7] Port upstream goal judge current-time prompt context into `hermes_cli/goals.py`
- [x] T091E [US7] Add `goal_json` to the supervisor task ledger for task-level goal state, turn budget, judge metadata, and bounded judge history
- [x] T091F [US7] Add `set_task_goal()` and `evaluate_task_goal_continuation()` helpers that reuse the configured auxiliary goal judge while respecting supervisor ledger gates
- [x] T091G [US7] Add `hermes runtime control create --goal ...` and `hermes runtime control goal --set|--last-response|--status --json` CLI-compatible surfaces
- [x] T091H [US7] Surface goal status, last verdict, last reason, and turn budget in observability line items and evidence bundles
- [x] T091I [US7] Update `docs/curator-policy-framework-architecture.md` with task-level goal continuation, judge sidecar identity, authority boundaries, and error handling
- [x] T091J [US7] Add named model-role config helpers for `curator`, `learning_judge`, and `goal_judge` so each can use a separate Codex instance/persona
- [x] T091K [US7] Add CLI surfaces `hermes config roles --json` and `hermes config role set <role> ... --json`
- [x] T091L [US7] Add backend surfaces `GET /api/model/roles` and `PUT /api/model/roles/{role}` for dashboard/service configuration

**Checkpoint**: Native goal continuation is available as a supervisor-owned task loop, but completion authority remains with deterministic validation and operator/judge-approved control-plane actions.

---

## Phase 10: Polish And Integration

- [x] T092 Run focused learning and policy tests: `pytest tests/hermes_cli/test_supervisor_memory.py tests/hermes_cli/test_policy_engine.py tests/hermes_cli/test_config.py -q`
- [x] T093 Run new learning framework tests under `tests/hermes_cli/test_learning_*.py`
- [x] T094 Run runtime orchestration tests under `tests/hermes_cli/test_runtime_*.py`
- [x] T095 Run hybrid retrieval tests under `tests/hermes_cli/test_memory_index.py tests/hermes_cli/test_memory_graph.py tests/hermes_cli/test_memory_retrieval.py`
- [x] T096 Run VM smoke sequence for supervisor protocol, sidecar, judge, bus, retrieval, policy audit, dreaming, and supervisor control-plane recovery
- [x] T097 Update `docs/runtime-learning-enforcement.md` with implementation status and VM validation notes
- [x] T098 Push branch and record commit hashes for local and VM deployments

## Phase 11: Production Runtime Surfaces And Low-End Model Validation (Priority: P8)

**Goal**: Turn the architecture into production-ready surfaces that can be tested with lower-cost models. The system should prove that memory packets, judge gates, sidecars, observability, and policy hints improve task convergence for weaker/cheaper workers without bloating runtime infrastructure.

**Independent Test**: Run the same branch-inspection, repair, and form-fill planning tasks with a low-cost worker model before and after memory/judge/sidecar injection. Verify fewer repeated mistakes, fewer failed tool calls, better validation evidence, bounded token use, and no unauthorized memory/policy/config mutation.

### Tests for Production Runtime Surfaces

- [ ] T099 [P] [US8] Add low-end model baseline eval fixtures for repeated command failure, branch triage, validation discipline, and worker handoff quality in `tests/hermes_cli/test_low_end_model_evals.py`
- [ ] T100 [P] [US8] Add memory-injection improvement tests proving task classifier + metadata retrieval + compact packet reduce repeated mistakes for cheaper workers without leaking unrelated tenant/repo lessons
- [ ] T101 [P] [US8] Add observability UI/API tests for historical jobs, active jobs, tenant/repo/date filters, worker status, blocker reason, completion status, line-item drilldown, and scoped Ask analysis
- [ ] T102 [P] [US8] Add realtime voice config/transport tests for OpenAI `gpt-realtime-2`, MiniMax `speech-2.8`, and xAI/Grok provider selection, fallback reporting, and no secret leakage
- [ ] T103 [P] [US8] Add Kafka/Redpanda global bus integration tests behind optional dependency marks, proving idempotent publish/consume/replay/dead-letter behavior
- [ ] T104 [P] [US8] Add training corpus export tests for JSONL/Parquet bundles, redaction, approval provenance, tenant/shareability boundaries, and dataset-family filters
- [ ] T105 [P] [US8] Add memory wiki scale-out tests for object/state/lexical/vector/graph backend adapters using local fakes before production services

### Implementation for Production Runtime Surfaces

- [ ] T106 [US8] Implement a low-end model eval runner that records baseline vs memory-assisted metrics: task success, tool error count, repeated error signatures, validation completeness, token estimate, wall time, and escalation count
- [ ] T107 [US8] Implement compact task-memory retrieval profiles for low-cost workers, including strict top-k caps, exact metadata filters, command/error signature matching, semantic fallback, and negative-feedback demotion
- [ ] T108 [US8] Implement richer observability frontend/backend surfaces for active/historical jobs: tenant, repo, task description, worker, model, Spec Kit refs, architecture refs, task list refs, blocker status, completion status, evidence bundle, and scoped Ask analysis
- [ ] T109 [US8] Implement realtime voice transport behind the existing `voice.realtime` config, with provider adapters for OpenAI realtime first and MiniMax/xAI-compatible extension points
- [ ] T110 [US8] Implement production global-memory bus deployment helpers for Redpanda/Kafka while keeping SQLite as the default single-node backend
- [ ] T111 [US8] Implement production memory wiki backend adapters for configurable object storage, state store, vector index, and graph index; keep local filesystem/SQLite as default
- [ ] T112 [US8] Implement training corpus bundle writer with JSONL first, Parquet optional, manifest metadata, redaction report, source refs, approval refs, and hash-based reproducibility
- [ ] T113 [US8] Add operator controls for approving export bundles, enabling realtime providers, and promoting low-end model eval findings into advisory policies only after judge/operator approval
- [ ] T114 [US8] Update architecture docs with production deployment topology, low-end model eval loop, cost controls, and escalation path from cheap worker -> stronger judge -> operator
- [ ] T115 [US8] Run VM smoke sequence with low-cost models as workers and Codex/strong reasoning as judge/curator, then record measured improvements and regressions in `docs/runtime-learning-enforcement.md`
- [ ] T116 [US8] Resolve VM retrieval gap for command-repair policies: either intentionally keep policy-engine audit separate from compact memory packets and document that boundary, or add relevant approved `command_repair_policy` candidates to task memory packets with strict top-k and audit-only wording

**Checkpoint**: Lower-cost workers can be evaluated against deterministic baselines, receive compact relevant memory, and show measurable improvement without gaining authority over memory approval, policy enforcement, config mutation, or cross-tenant sharing.

## Dependencies & Execution Order

- Phase 1 and Phase 2 must complete before any user story implementation.
- User Story 1 is the MVP because every serious task must go through deterministic supervisor orchestration and Spec Kit preservation.
- User Story 2 depends on foundational DB helpers and provides the learning approval gate.
- User Story 3 can begin after foundational DB helpers exist.
- User Story 4 can continue in parallel after tier fields and packet schemas are available.
- User Story 5 depends on approved memory from User Story 2 and retrieval/tier rules from User Story 4.
- User Story 6 can begin after job records are available and should expand as each sidecar path lands.
- User Story 7 depends on runtime packet schemas, learning jobs, event bus, and observability surfaces so stale/looping work can be audited and recovered.
- User Story 8 depends on Phase 10 validation and should start with low-end model eval instrumentation before production backend scale-out.

## Parallel Opportunities

- Test files for runtime orchestration, judge, bus, wiki, dreaming, and jobs can be developed in parallel.
- Supervisor control-plane tests can be developed in parallel after runtime packet schemas and learning job helpers are stable.
- CLI contracts and docs can be updated in parallel with implementation after data-model fields stabilize.
- Dashboard/backend observability can start once `learning_jobs.py` exposes stable JSON.
- Low-end model eval fixtures, realtime voice adapters, global bus adapters, memory wiki backends, and training export tests can be developed in parallel because they share only config contracts and DTOs.

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
8. Supervisor convergence control plane.
9. Future enforcement mode only after audit evidence, judge approval, and operator approval.
10. Production runtime surfaces and low-end model validation after Phase 10 smoke tests.
