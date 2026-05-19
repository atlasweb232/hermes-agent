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

**Cost Gate**: Do not add production infrastructure or LLM-backed sidecars before the persisted-lesson loop proves value. The required loop is: event signature -> local hot/warm lookup -> persisted approved global lesson retrieval -> compact advisory packet/pre-curation decision -> cheap worker attempt -> outcome feedback -> strong judge/operator only for promotion or enforcement.

**Phase 11A Core Production Path**: Finish `T105D`, `T105E`, `T105F`, `T105H`, `T105I`, `T121`, `T122`, `T123`, `T124`, `T125`, `T129`, `T130`, and `T131` before starting scale-out work.

**Deferred Scale-Out Work**: Keep `T102`, `T103`, `T104`, `T105`, `T109`, `T110`, `T111`, and `T112` out of the immediate implementation path unless the core production path shows measurable value and a concrete deployment need.

### Tests for Production Runtime Surfaces

- [x] T099 [P] [US8] Add low-end model baseline eval fixtures for repeated command failure, branch triage, validation discipline, and worker handoff quality in `tests/hermes_cli/test_learning_value.py`
- [x] T100 [P] [US8] Add memory-injection improvement tests proving task classifier + metadata retrieval + compact packet reduce repeated mistakes for cheaper workers without leaking unrelated tenant/repo lessons
- [ ] T101 [P] [US8] Add observability UI/API tests for historical jobs, active jobs, tenant/repo/date filters, worker status, blocker reason, completion status, line-item drilldown, and scoped Ask analysis
- [ ] T102 [P] [US8] Add realtime voice config/transport tests for OpenAI `gpt-realtime-2`, MiniMax `speech-2.8`, and xAI/Grok provider selection, fallback reporting, and no secret leakage
- [ ] T103 [P] [US8] Add Kafka/Redpanda global bus integration tests behind optional dependency marks, proving idempotent publish/consume/replay/dead-letter behavior
- [ ] T104 [P] [US8] Add training corpus export tests for JSONL/Parquet bundles, redaction, approval provenance, tenant/shareability boundaries, and dataset-family filters
- [ ] T105 [P] [US8] Add memory wiki scale-out tests for object/state/lexical/vector/graph backend adapters using local fakes before production services
- [x] T105A [P] [US8] Add global pre-curation dedupe tests proving an exact approved global lesson suppresses local expensive curation, a near match creates only lightweight confirmation, and a miss allows local curation
- [x] T105B [P] [US8] Add global lesson reuse metric tests for `global_lesson_hit`, `global_lesson_near_hit`, `global_lesson_used`, `global_lesson_helped`, `global_lesson_ignored`, and `global_lesson_hurt`
- [x] T105C [P] [US8] Add local-vs-global dreaming tests proving local dreaming cannot publish globally, global dreaming reads only approved/shareable canonical memory, and neither path mutates live runtime state
- [x] T105D [P] [US8] Add persisted global lesson storage/retrieval tests proving approved command-repair lessons are written to the configured global memory backend and read back through `retrieve_global_lessons_for_event(...)`, not injected as in-process test dictionaries
- [x] T105E [P] [US8] Add runtime pre-curation integration tests proving local curator/dreaming calls are skipped only when retrieved persisted lessons produce exact/near approved matches, and still run on storage miss, wrong tenant, secret, rejected, or stale lessons
- [x] T105F [P] [US8] Add live failure-learn smoke fixture proving a fresh Hermes task retrieves the stored Claude router failure lesson before repeating the old bad command loop
- [x] T105G [P] [US8] Add cost-budget tests proving retrieval/pre-curation uses programmatic logic by default, enforces top-k memory caps, estimates injected token budget, and does not call curator/judge/dreaming LLMs on exact persisted lesson hits
- [x] T105H [P] [US8] Add local hot-cache tests proving top-k persisted global lessons can be materialized into task-local hot memory with TTL, tenant/repo/sensitivity gates, reuse counters, and no raw global evidence copy
- [x] T105I [P] [US8] Add task-start hydration tests proving task metadata first checks local hot cache, then global exact/simhash lookup, then writes bounded hot-cache entries and produces a compact merged memory packet

### Implementation for Production Runtime Surfaces

- [x] T106 [US8] Implement a low-end model eval runner that records baseline vs memory-assisted metrics: task success, tool error count, repeated error signatures, validation completeness, token estimate, wall time, and escalation count
- [ ] T107 [US8] Implement compact task-memory retrieval profiles for low-cost workers, including strict top-k caps, exact metadata filters, command/error signature matching, semantic fallback, and negative-feedback demotion
- [ ] T108 [US8] Implement richer observability frontend/backend surfaces for active/historical jobs: tenant, repo, task description, worker, model, Spec Kit refs, architecture refs, task list refs, blocker status, completion status, evidence bundle, and scoped Ask analysis
- [ ] T109 [US8] Implement realtime voice transport behind the existing `voice.realtime` config, with provider adapters for OpenAI realtime first and MiniMax/xAI-compatible extension points
- [ ] T110 [US8] Implement production global-memory bus deployment helpers for Redpanda/Kafka while keeping SQLite as the default single-node backend
- [ ] T111 [US8] Implement production memory wiki backend adapters for configurable object storage, state store, vector index, and graph index; keep local filesystem/SQLite as default
- [ ] T112 [US8] Implement training corpus bundle writer with JSONL first, Parquet optional, manifest metadata, redaction report, source refs, approval refs, and hash-based reproducibility
- [ ] T113 [US8] Add operator controls for approving export bundles, enabling realtime providers, and promoting low-end model eval findings into advisory policies only after judge/operator approval
- [ ] T114 [US8] Update architecture docs with production deployment topology, low-end model eval loop, cost controls, and escalation path from cheap worker -> stronger judge -> operator
- [ ] T115 [US8] Run VM smoke sequence with low-cost models as workers and Codex/strong reasoning as judge/curator, then record measured improvements and regressions in `docs/runtime-learning-enforcement.md`
- [x] T116 [US8] Resolve VM retrieval gap for command-repair policies: either intentionally keep policy-engine audit separate from compact memory packets and document that boundary, or add relevant approved `command_repair_policy` candidates to task memory packets with strict top-k and audit-only wording
- [x] T117 [US8] Implement `should_curate_locally(event)` with local hot/warm lookup, approved global exact/near matching, scope/sensitivity gates, and deterministic skip/confirm/curate decisions before any expensive local curator call
- [x] T118 [US8] Implement global lesson reuse counters and feedback updates so globally approved lessons gain confidence when they help, decay when ignored or harmful, and never import private local evidence without approval
- [x] T119 [US8] Split local dreaming and global dreaming role/config/lease definitions so local dreaming stays tenant/repo scoped and global dreaming consumes only approved redacted global memory
- [x] T120 [US8] Update VM smoke to include a duplicate-failure scenario where a global approved command-repair lesson suppresses local recuration and records a global lesson hit
- [x] T121 [US8] Implement `persist_global_lesson(...)` and local SQLite-backed global memory state schema for approved canonical lessons with failure/success/scope/evidence signatures, confidence, reuse stats, approval provenance, tenant/scope/sensitivity gates, text hash, simhash, and stale/retired status
- [x] T122 [US8] Implement `retrieve_global_lessons_for_event(...)` with hard metadata filters first, exact signature/hash lookup second, near simhash/lexical fallback third, strict top-k caps, and audit output showing which backend rows were considered or rejected
- [x] T123 [US8] Wire retrieved persisted global lessons into the pre-curation path before local curator and local dreaming, recording `global_lesson_hit`, `global_lesson_near_hit`, or `global_lesson_miss` as aggregate feedback without copying private local evidence globally
- [x] T124 [US8] Add CLI/API surfaces for operator testing: `hermes memory global lesson add/list/get`, `hermes memory global retrieve --event-json`, and JSON output suitable for backend/dashboard invocation
- [x] T125 [US8] Update VM smoke to persist the Claude router repair lesson in the real global memory backend, restart Hermes, run a fresh retrieval/pre-curation check, and then run a live Hermes task to verify the stored lesson is found before the old failure loop repeats
- [x] T125A [US8] Run VM persisted-memory smoke through CLI add/retrieve/hydrate and curator pre-curation, proving durable global lesson retrieval suppresses expensive curator recuration before live-chat validation
- [ ] T126 [US8] Implement low-cost model routing budget policy: programmatic retrieval first, cheap model for lightweight confirmation/extraction only, strong model for judge/curator only when confidence is low or promotion/enforcement is requested
- [x] T127 [US8] Add minimal JSON observability for cost/value before frontend work: per-task memory hits, token estimate, skipped curator count, repeated-error count, worker model, outcome, and whether memory helped/ignored/hurt
- [ ] T128 [US8] Audit SQLite learning/global bus queues before Kafka/Redpanda work: list queued/leased/consumed/dead events, drain one batch idempotently, verify replay safety, and document whether a dedicated consumer sidecar is required
- [x] T129 [US8] Implement local hot-cache table/helpers for approved global lessons with compact text, signatures, confidence, TTL, last_used_at, reuse stats, source global lesson id, and tenant/repo/sensitivity gates
- [x] T130 [US8] Implement task-start hydration helper: classify task metadata, read local hot cache, retrieve persisted global lessons on miss, materialize top-k into hot cache, and return a compact global/local advisory packet
- [x] T131 [US8] Merge hydrated global hot-cache entries with local memory wiki/retrieval packets using strict token caps, source labels, evidence ids, and advisory wording so low-cost workers get the smallest useful context
- [x] T131A [US8] Implement supervisor-side generic runtime failure capture for long/repeated command-family failures and evidence-mismatch substitutions, writing mandatory `supervisor_runtime_failure` memory records with judge/operator gates
- [x] T131A1 [US8] Add supervisor runtime failure final-response gate and worker foreground timeout cap so failed/timed-out/empty worker calls are disclosed as degraded fallback instead of silently reported as successful worker completion
- [x] T131B [US8] Extend the same generic runtime failure capture contract to delegated agents/workers so worker hallucinations, false completions, and route substitutions are captured before curator/judge sidecars run
- [x] T131C [US8] Add specialized curator/judge handling for `supervisor_runtime_failure` records, producing advisory-only candidates until judge plus operator approve promotion or enforcement

### Deferred Phase 11B Global Indexing And Sync Sidecars

- [ ] T132 [US8] Implement `global_indexer_sidecar` only after Phase 11A VM value is proven; it should index approved canonical global lessons into lexical/vector/graph backends behind config, never raw proposals
- [ ] T133 [US8] Implement `local_sync_sidecar` only after Phase 11A VM value is proven; it should pull approved sync deltas relevant to configured tenants/repos/tools into warm cache without blocking foreground work
- [ ] T134 [US8] Add sync-delta protocol tests for global-to-local cache updates, idempotency, TTL demotion, deleted/retired lesson removal, and no private/secret lesson sync
- [ ] T135 [US8] Add optional vector/graph indexing tests for global lessons only after hash/signature/SQLite hot-cache retrieval shows measured low-end-worker improvement

**Checkpoint**: Lower-cost workers can be evaluated against deterministic baselines, receive compact relevant memory, and show measurable improvement without gaining authority over memory approval, policy enforcement, config mutation, or cross-tenant sharing.

## Phase 12: Goal-Based Multi-Agent Allocation (Priority: P9)

**Goal**: Use upstream `/goal` as the continuation/pause/resume loop for long-running workloads, while adding a deterministic allocator that manages worker health, latency budgets, ranked fallback, recovery pauses, and evidence disclosure inside each bounded goal/task turn.

**Independent Test**: Start a `/goal`-backed task with Claude Code as primary and Codex/DeepSeek as fallbacks. Simulate quota exhaustion, auth failure, network degradation, timeout, empty worker output, and repeated-route failure. Verify the allocator records attempts, updates worker health, respects latency budget, chooses fallback or pauses with retry-after, and lets `/goal resume` recover state without retrying unhealthy routes.

**Boundary**: This phase must not create a second autonomous loop. `/goal` owns continuation; the allocator owns worker selection and attempt recovery. Foreground chat must never sleep indefinitely for network or quota recovery.

### Spec And Architecture Artifacts

- [x] T136 [US9] Document upstream `/goal` integration model: goal state is stored in `SessionDB.state_meta` as `goal:<session_id>`, continuation prompts remain user-role messages, and multi-agent allocation must extend this lifecycle rather than create a second loop
- [x] T137 [US9] Add `contracts/goal-allocation.md` defining allocation state keys, `WorkerAllocationPlan`, `WorkerAttemptResult`, `WorkerHealth`, lifecycle, invariants, observability, and tests
- [x] T138 [US9] Link the goal-allocation phase from `plan.md`, `spec.md`, and `docs/multi-agent-allocation-architecture.md`

### Tests For Goal-Based Allocation

- [x] T139 [P] [US9] Add schema tests for `WorkerAllocationPlan`, `WorkerAttemptResult`, and `WorkerHealth`, including invalid status, missing budget, missing validation requirement, and unsafe fallback eligibility
- [x] T140 [P] [US9] Add allocator decision tests for ranked fallback, repeated-route suppression, worker cooldown, all-workers-unhealthy pause, and no foreground sleep on network degradation
- [ ] T141 [P] [US9] Add `/goal resume` tests proving allocation state is recovered from `allocation:<session_id>:<task_id>` and unhealthy workers are skipped until cooldown expires
- [x] T142 [P] [US9] Add observability tests for active allocations, worker health, attempt history, consumed latency budget, fallback reason, retry-after, and goal/session linkage

### Implementation For Goal-Based Allocation

- [x] T143 [US9] Implement `WorkerAllocationPlan`, `WorkerAttemptResult`, and `WorkerHealth` schemas with JSON serialization suitable for `SessionDB.state_meta`
- [x] T144 [US9] Implement allocation state helpers for `allocation:<session_id>:<task_id>` and worker health helpers for `worker_health:<worker_id>`
- [x] T145 [US9] Implement allocator decision logic that consults runtime memory and worker health, selects primary worker, enforces latency/retry budgets, skips unhealthy workers, tries ranked fallbacks, and pauses/schedules recovery instead of foreground sleeping on degradation
- [x] T146 [US9] Wire allocator into the supervisor delegation path before direct fallback so Claude/Codex/DeepSeek/Cursor/Minimax can be reallocated under policy while final responses still disclose degraded worker evidence
- [x] T147 [US9] Add allocator CLI/API observability: `hermes runtime allocations list/get --json` and `hermes runtime workers health --json`
- [x] T148 [US9] Extend generic runtime failure capture to delegated agents/workers so worker hallucinations, false completions, empty outputs, timeouts, and route substitutions are captured before curator/judge sidecars run
- [x] T149 [US9] Add specialized curator/judge handling for allocator and `supervisor_runtime_failure` records, producing advisory-only candidates until judge plus operator approve promotion or enforcement
- [x] T149A [US9] Add scoped runtime advisory packet retrieval for approved/applied `supervisor_runtime_failure_advisory` candidates, including tenant/repo/task/worker/tool/route filtering, secret redaction, confidence, recency, and token bounds
- [x] T149B [US9] Inject runtime failure advisory packets before `delegate_task` dispatch as warning/recovery context without command rewriting, auto-approval, or blocking
- [x] T149C [US9] Expose allocator runtime advisory packets while preserving retry, cooldown, and latency-budget decisions
- [x] T149D [US9] Document the capture -> curator -> judge/operator -> advisory retrieval -> dispatch flow and why `supervisor_runtime_failure` remains curator-only during generic rollup

**Checkpoint**: `/goal` can continue serious work without trapping Hermes in one failed worker route; allocation attempts are bounded, observable, resumable, and separated from memory/policy enforcement.

## Phase 13: Self-Healing Workflow Control Plane (Priority: P10)

**Goal**: Add the stability layer around goal allocation: supervisor-owned parallel task graph, asynchronous health sidecar, and restart recovery. This prevents long-running agentic work from drifting, blocking, or looping while preserving supervisor authority and foreground responsiveness.

**Independent Test**: Create a multi-node task graph with Claude/Codex/DeepSeek workers, simulate stale lease, missing heartbeat, no-progress loop, network degradation, and service restart. Verify ready subtasks dispatch within ownership/concurrency rules, the health sidecar emits bounded recovery actions, and restart recovery resumes only safe work.

**Boundary**: This phase must be workflow-agnostic. Chat, `/goal`, dashboard, API, and worker delegation should all use the same task graph, health sidecar, recovery, allocator, and degradation vocabulary.

### Spec And Architecture Artifacts

- [x] T150 [US10] Add `contracts/task-graph.md` defining supervisor-owned parallel subtasks, dependencies, ownership, concurrency caps, worktree refs, validation refs, and completion rules
- [x] T151 [US10] Add `contracts/health-sidecar.md` defining stale lease, heartbeat, no-progress, repeated failure, cooldown, and bounded recovery sidecar behavior
- [x] T152 [US10] Add `contracts/restart-recovery.md` defining startup recovery for goals, task graphs, allocations, worker health, sidecar leases, hot memory, and safe-to-resume work
- [x] T153 [US10] Link Phase 13 from `plan.md`, `spec.md`, and `super-architecture.md`
- [x] T166 [US10] Add `contracts/azure-runtime-deployment.md` documenting that Azure VM deployment must run `132-learning-memory-runtime`, keep upstream as comparison-only, and validate allocator/degradation/goal-loop behavior through branch-owned runtime smoke tests
- [x] T167 [US10] Add `contracts/worker-progress-context-gate.md` defining store-only worker streams, mandatory wrapper progress events, supervisor context admission rules, Slack/UI projection, and low-cost progress summarizer behavior

### Tests For Self-Healing Workflow Control Plane

- [ ] T154 [P] [US10] Add task graph schema tests for task/node status, dependency ordering, concurrency cap, owned-path conflict rejection, read-only nodes, validation-gated completion, and supervisor-only subtask acceptance
- [ ] T155 [P] [US10] Add health sidecar tests for stale lease, missing heartbeat, repeated timeout/empty-output failures, no-progress loop, worker cooldown, allocation pause, idempotent duplicate runs, and no foreground blocking
- [ ] T156 [P] [US10] Add restart recovery tests for active goal reload, task graph reload, active allocation reload, worker cooldown preservation, unknown in-flight attempt handling, approved-memory-only hydration, and no default expensive LLM sidecar call
- [ ] T157 [P] [US10] Add workflow-agnostic tests proving chat, `/goal`, dashboard/API task, and worker delegation paths share allocator/degradation/health/recovery behavior
- [ ] T168 [P] [US10] Add supervisor context gate tests proving raw stdout/stderr, unbounded terminal transcripts, worker watch streams, and log tails are rejected from supervisor context unless represented as bounded typed packets
- [ ] T169 [P] [US10] Add worker runtime wrapper tests proving start, heartbeat, stream-ref, checkpoint, degraded/blocked, validation, and final events are emitted even when the worker model is unavailable, times out, or returns empty output
- [ ] T170 [P] [US10] Add cheap progress summarizer sidecar tests proving low-cost reasoning tier use, timeout/budget enforcement, no foreground blocking, no task completion authority, and no policy/memory approval authority

### Implementation For Self-Healing Workflow Control Plane

- [ ] T158 [US10] Implement task graph and task node schemas with JSON serialization suitable for `SessionDB.state_meta` or supervisor task ledger storage
- [ ] T159 [US10] Implement task graph state helpers for create/update/list/get, dependency readiness, concurrency checks, owned-path conflict detection, and validation-gated completion
- [ ] T160 [US10] Wire task graph ready-node dispatch into the allocator so parallel subtasks receive bounded worker allocation without overlapping unsafe ownership
- [ ] T161 [US10] Implement health sidecar scanner for task ledger, task graph, allocations, worker health, heartbeats, and degradation events with bounded leases, timeout, scan limit, and idempotent actions
- [ ] T162 [US10] Implement health sidecar recovery actions: update worker health, mark stale lease/no-progress, emit recovery packet, request reassignment, pause allocation with retry-after, and publish learning events
- [ ] T163 [US10] Implement restart recovery loader for goals, task ledger, task graphs, allocations, worker health, hot memory, approved lessons, sidecar leases, and safe-to-resume decisions
- [ ] T164 [US10] Add CLI/API observability: `hermes runtime health check --once --json`, `hermes runtime task-graph list/get --json`, and `hermes runtime recovery status/run --json`
- [ ] T165 [US10] Run controlled upstream-vs-branch smoke tests proving the branch avoids repeated failed worker loops, preserves foreground responsiveness, and resumes safe work after restart
- [ ] T171 [US10] Implement `SupervisorContextGate` helpers that accept only typed bounded worker packets and attach artifact refs instead of raw streams
- [ ] T172 [US10] Wire worker runtime wrappers and worker-router/delegation paths to emit mandatory progress events and artifact refs into the runtime event bus/task ledger
- [ ] T173 [US10] Implement progress summarizer sidecar that consumes worker progress events, uses the configured low-cost reasoning tier, emits compact checkpoints, and degrades to deterministic summaries when the model is unavailable
- [ ] T174 [US10] Update Slack/dashboard/API observability to stream worker progress from event/log refs while keeping supervisor model context limited to accepted context-gate packets

**Checkpoint**: Long-running workflows can run as supervisor-owned task graphs, recover from worker/platform degradation out of band, and restart from durable state without retrying unsafe routes or blocking foreground work.

## Phase 14: Production Evaluation Harness (Priority: P11)

**Goal**: Build a side-by-side upstream-vs-branch evaluation harness that proves whether memory wrapping, sidecars, judges, allocator fallback, QA workers, and context gates improve long-horizon task quality without unacceptable token/cost/latency overhead.

**Independent Test**: Run the same workload pack against upstream Hermes and `132-learning-memory-runtime` with isolated homes and shared repo snapshots. Verify comparison output includes quality, validation, latency, token/cost, context growth, sidecar overhead, memory usefulness, urgent alerts, operator interventions, and production gate result.

**Boundary**: This is the production-readiness gate. Do not productionize self-learning, global memory, CI/CD automation, or multi-agent clusters until the harness shows value over upstream.

### Spec And Architecture Artifacts

- [x] T175 [US11] Add `contracts/production-evaluation-harness.md` defining upstream-vs-branch environments, workload classes, telemetry, sidecar/judge assertions, quality metrics, storage, and human-in-the-loop gates
- [x] T176 [US11] Add `docs/production-evaluation-harness-architecture.md` covering message bus/storage flow, Delta/object-store evolution, cost/context telemetry, sidecar verification, QA toolsets, and production gate reporting
- [x] T177 [US11] Link Phase 14 from `plan.md`, `spec.md`, and `tasks.md`

### Tests For Production Evaluation Harness

- [ ] T178 [P] [US11] Add benchmark environment tests proving upstream and branch runs use separate `HERMES_HOME`, separate artifact roots, shared workload definitions, and no cross-contamination
- [ ] T179 [P] [US11] Add telemetry schema tests for token/cost/latency/context/path attribution across supervisor, planner, worker, judge, curator, dreaming, progress summarizer, QA, deployment, memory retrieval, and Slack/dashboard analysis
- [ ] T180 [P] [US11] Add production gate tests proving rollout is blocked when branch quality regresses, sidecars block foreground work, urgent alerts are missing, memory approval boundaries are violated, or cost exceeds thresholds
- [ ] T181 [P] [US11] Add workload pack fixture tests for review, implementation, QA, deployment, long-running goal, fallback, stale worker, repeated failure, multi-repo decomposition, and hallucinated completion cases

### Implementation For Production Evaluation Harness

- [ ] T182 [US11] Implement benchmark workload dataclasses and JSON/YAML loader with repo refs, prompt, model/tool profile, expected artifacts, validation commands, and pass/fail rubric
- [ ] T183 [US11] Implement isolated environment runner that can invoke upstream Hermes and branch Hermes with separate homes, worktrees, env files, and artifact roots
- [ ] T184 [US11] Implement telemetry collector for model usage, latency, cost estimates, context admitted, raw bytes stored, worker attempts, sidecar runs, judge decisions, memory hits, validation results, notifications, and operator interventions
- [ ] T185 [US11] Implement comparison report generator with upstream-vs-branch quality/cost/latency/context/self-learning metrics and production gate status
- [ ] T186 [US11] Add CLI/API surfaces: `hermes runtime benchmark run --suite ... --json`, `hermes runtime benchmark report --run-id ... --json`, and `hermes runtime costs status --json`
- [ ] T187 [US11] Add urgent Slack integration for benchmark failures and production-gate blocks
- [ ] T188 [US11] Add CI/CD harness template that runs deterministic benchmark smoke on PRs and full long-horizon benchmark on scheduled/operator-triggered runs
- [ ] T189 [US11] Run Azure VM side-by-side smoke: upstream clean Hermes vs branch Hermes on the Azure port workflow, recording token/cost/latency/quality/self-learning results

**Checkpoint**: Production readiness is based on measured upstream-vs-branch evidence, not anecdotal task success.

## Dependencies & Execution Order

- Phase 1 and Phase 2 must complete before any user story implementation.
- User Story 1 is the MVP because every serious task must go through deterministic supervisor orchestration and Spec Kit preservation.
- User Story 2 depends on foundational DB helpers and provides the learning approval gate.
- User Story 3 can begin after foundational DB helpers exist.
- User Story 4 can continue in parallel after tier fields and packet schemas are available.
- User Story 5 depends on approved memory from User Story 2 and retrieval/tier rules from User Story 4.
- User Story 6 can begin after job records are available and should expand as each sidecar path lands.
- User Story 7 depends on runtime packet schemas, learning jobs, event bus, and observability surfaces so stale/looping work can be audited and recovered.
- User Story 8 depends on Phase 10 validation and must finish persisted lesson storage/retrieval plus cost-budget instrumentation before production backend scale-out.
- User Story 9 depends on the Phase 11 runtime-degradation gate and persisted memory retrieval, then adds deterministic allocation around upstream `/goal` continuation.
- User Story 10 depends on User Story 9 allocator state and adds task graph, health sidecar, and restart recovery around it.
- User Story 11 depends on User Stories 8 through 10 enough to measure them and becomes the gate for production rollout.

## Parallel Opportunities

- Test files for runtime orchestration, judge, bus, wiki, dreaming, and jobs can be developed in parallel.
- Supervisor control-plane tests can be developed in parallel after runtime packet schemas and learning job helpers are stable.
- CLI contracts and docs can be updated in parallel with implementation after data-model fields stabilize.
- Dashboard/backend observability can start once `learning_jobs.py` exposes stable JSON.
- Low-end model eval fixtures and persisted lesson retrieval can be developed first. Realtime voice adapters, global bus adapters, production memory wiki backends, and training export tests are intentionally deferred until the core loop has measured value.
- Goal-allocation schema, decision, resume, and observability tests can be developed in parallel after the contract lands.
- Task graph, health sidecar, restart recovery, and workflow-agnostic tests can be developed in parallel after Phase 13 contracts land.
- Benchmark workload loader, telemetry schema, isolated runner, and report generator can be developed in parallel after Phase 14 contracts land.

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
11. Goal-based multi-agent allocation after runtime degradation evidence is reliable.
12. Self-healing workflow control plane after allocator state exists.

### Phase 11A Immediate Order

1. Persist and retrieve approved global lessons using SQLite/local storage.
2. Wire persisted retrieval into pre-curation before local curator/dreaming.
3. Add CLI/API operator surfaces for adding, listing, retrieving, and auditing global lessons.
4. Add cost-budget counters and minimal JSON observability.
5. Run VM restart smoke and live failure-learn smoke.
6. Run low-end model before/after eval.

### Phase 11B Deferred Order

1. Resolve command-repair compact packet gap if live smoke shows prompt injection is required in addition to pre-curation.
2. Audit and drain SQLite bus queues before adding Kafka/Redpanda.
3. Add production bus/object/vector/graph adapters only when a multi-instance deployment requires them.
4. Add training corpus export only after approved memory provenance is stable.
5. Add realtime voice after runtime learning correctness is proven.

### Phase 12 Order

1. Add allocation schemas and state persistence.
2. Add worker health registry and status updates from attempt results.
3. Add allocator decision policy with budgets, cooldowns, and ranked fallback.
4. Wire allocator into supervisor delegation while preserving degraded-response gates.
5. Add CLI/API observability for allocations and worker health.
6. Run controlled upstream-vs-branch smoke tests to prove reduced looping and clearer degradation disclosure.

### Phase 13 Order

1. Add supervisor context gate tests and helpers so raw worker streams cannot enter model context.
2. Add wrapper-emitted worker progress events and artifact refs.
3. Add cheap progress summarizer sidecar and Slack/dashboard projection.
4. Add task graph schemas and state helpers.
5. Add dependency, concurrency, and owned-path safety checks.
6. Wire ready task nodes through the generic allocator.
7. Add health sidecar scanner and bounded recovery actions.
8. Add restart recovery loader and safe-to-resume decisions.
9. Add CLI/API observability for task graph, health, and recovery.
10. Run restart and degraded-worker smoke tests.

### Phase 14 Order

1. Add benchmark workload schema and telemetry schema tests.
2. Add isolated upstream/branch runner with separate homes and artifact roots.
3. Add token/cost/latency/context telemetry collection.
4. Add sidecar/judge/memory assertion checks.
5. Add comparison report and production gate.
6. Add CI/CD smoke and scheduled long-horizon benchmark harness.
7. Run Azure VM upstream-vs-branch benchmark and record results.
