# Tasks: Runtime Learning Memory Framework

**Input**: Design documents from `/specs/001-learning-memory-runtime/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Required for all runtime state transitions, safety gates, and CLI JSON contracts.

**Organization**: Tasks are grouped by user story so each slice can be implemented and validated independently.

## Phase 1: Setup

**Purpose**: Preserve upstream merge and Spec Kit baseline before feature work.

- [x] T001 Commit upstream merge and Spec Kit scaffolding in repository root
- [x] T002 [P] Update `docs/curator-policy-framework-architecture.md` to reference `specs/001-learning-memory-runtime/`
- [x] T003 [P] Add focused test fixtures for isolated Hermes home/state DB setup in `tests/hermes_cli/`

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

**Deferred Scale-Out Work**: Keep `T103`, `T104`, `T105`, `T110`, `T111`, and `T112` out of the immediate implementation path unless the core production path shows measurable value and a concrete deployment need.

### Tests for Production Runtime Surfaces

- [x] T099 [P] [US8] Add low-end model baseline eval fixtures for repeated command failure, branch triage, validation discipline, and worker handoff quality in `tests/hermes_cli/test_learning_value.py`
- [x] T100 [P] [US8] Add memory-injection improvement tests proving task classifier + metadata retrieval + compact packet reduce repeated mistakes for cheaper workers without leaking unrelated tenant/repo lessons
- [x] T101 [P] [US8] Add observability UI/API tests for historical jobs, active jobs, tenant/repo/date filters, worker status, blocker reason, completion status, line-item drilldown, and scoped Ask analysis
- [x] T103 [P] [US8] Add Kafka/Redpanda global bus integration tests behind optional dependency marks, proving backend config selection, broker health checks, topic verification, idempotent publish/consume/replay/dead-letter behavior, lag metrics, TLS/SASL config-shape validation without secrets, SQLite spool fallback when the broker is unavailable, and no foreground blocking
- [x] T104 [P] [US8] Reconcile legacy training corpus export tests with Phase 19 MLOps corpus remittance, proving JSONL/Parquet-compatible bundles, redaction, approval provenance, tenant/shareability boundaries, and dataset-family filters use the same safety boundary and do not create a second export path
- [x] T105 [P] [US8] Add memory wiki scale-out tests for object/state/lexical/vector/graph backend adapters using local fakes before production services
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
- [x] T107 [US8] Implement compact task-memory retrieval profiles for low-cost workers, including strict top-k caps, exact metadata filters, command/error signature matching, semantic fallback, and negative-feedback demotion
- [x] T108 [US8] Implement richer observability frontend/backend surfaces for active/historical jobs: tenant, repo, task description, worker, model, Spec Kit refs, architecture refs, task list refs, blocker status, completion status, evidence bundle, and scoped Ask analysis
- [x] T110 [US8] Implement production global-memory bus deployment helpers for Redpanda/Kafka while keeping SQLite as the default single-node backend, including Docker Compose staging template, optional Kubernetes/Helm or Terraform handoff docs, health/check CLI, dead-letter/replay tooling, SQLite-to-broker publish sidecar, broker-unavailable fallback to SQLite spool, and a staging soak-test checklist
- [x] T111 [US8] Implement production memory wiki backend adapters for configurable object storage, state store, vector index, and graph index; keep local filesystem/SQLite as default
- [x] T112 [US8] Reuse or adapt the Phase 19 MLOps corpus bundle writer for legacy/wiki training corpus exports with JSONL first, Parquet-compatible manifest metadata, redaction report, source refs, approval refs, and hash-based reproducibility, avoiding duplicate corpus writer semantics
- [x] T113 [US8] Add operator controls for approving export bundles and promoting low-end model eval findings into advisory policies only after judge/operator approval
- [x] T114 [US8] Update architecture docs with production deployment topology, low-end model eval loop, cost controls, and escalation path from cheap worker -> stronger judge -> operator
- [x] T115 [US8] Run VM smoke sequence with low-cost models as workers and Codex/strong reasoning as judge/curator, then record measured improvements and regressions in `docs/runtime-learning-enforcement.md`
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
- [x] T126 [US8] Implement low-cost model routing budget policy: programmatic retrieval first, cheap model for lightweight confirmation/extraction only, strong model for judge/curator only when confidence is low or promotion/enforcement is requested
- [x] T127 [US8] Add minimal JSON observability for cost/value before frontend work: per-task memory hits, token estimate, skipped curator count, repeated-error count, worker model, outcome, and whether memory helped/ignored/hurt
- [x] T128 [US8] Audit SQLite learning/global bus queues before Kafka/Redpanda work: list queued/leased/consumed/dead events, drain one batch idempotently, verify replay safety, and document whether a dedicated consumer sidecar is required
- [x] T129 [US8] Implement local hot-cache table/helpers for approved global lessons with compact text, signatures, confidence, TTL, last_used_at, reuse stats, source global lesson id, and tenant/repo/sensitivity gates
- [x] T130 [US8] Implement task-start hydration helper: classify task metadata, read local hot cache, retrieve persisted global lessons on miss, materialize top-k into hot cache, and return a compact global/local advisory packet
- [x] T131 [US8] Merge hydrated global hot-cache entries with local memory wiki/retrieval packets using strict token caps, source labels, evidence ids, and advisory wording so low-cost workers get the smallest useful context
- [x] T131A [US8] Implement supervisor-side generic runtime failure capture for long/repeated command-family failures and evidence-mismatch substitutions, writing mandatory `supervisor_runtime_failure` memory records with judge/operator gates
- [x] T131A1 [US8] Add supervisor runtime failure final-response gate and worker foreground timeout cap so failed/timed-out/empty worker calls are disclosed as degraded fallback instead of silently reported as successful worker completion
- [x] T131B [US8] Extend the same generic runtime failure capture contract to delegated agents/workers so worker hallucinations, false completions, and route substitutions are captured before curator/judge sidecars run
- [x] T131C [US8] Add specialized curator/judge handling for `supervisor_runtime_failure` records, producing advisory-only candidates until judge plus operator approve promotion or enforcement

### Deferred Phase 11B Global Indexing And Sync Sidecars

- [x] T132 [US8] Implement `global_indexer_sidecar` only after Phase 11A VM value is proven; it should index approved canonical global lessons into lexical/vector/graph backends behind config, never raw proposals
- [x] T133 [US8] Implement `local_sync_sidecar` only after Phase 11A VM value is proven; it should pull approved sync deltas relevant to configured tenants/repos/tools into warm cache without blocking foreground work
- [x] T134 [US8] Add sync-delta protocol tests for global-to-local cache updates, idempotency, TTL demotion, deleted/retired lesson removal, and no private/secret lesson sync
- [x] T135 [US8] Add optional vector/graph indexing tests for global lessons only after hash/signature/SQLite hot-cache retrieval shows measured low-end-worker improvement

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
- [x] T141 [P] [US9] Add `/goal resume` tests proving allocation state is recovered from `allocation:<session_id>:<task_id>` and unhealthy workers are skipped until cooldown expires
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

- [x] T154 [P] [US10] Add task graph schema tests for task/node status, dependency ordering, concurrency cap, owned-path conflict rejection, read-only nodes, validation-gated completion, and supervisor-only subtask acceptance
- [x] T155 [P] [US10] Add health sidecar tests for stale lease, missing heartbeat, repeated timeout/empty-output failures, no-progress loop, worker cooldown, allocation pause, idempotent duplicate runs, and no foreground blocking
- [x] T156 [P] [US10] Add restart recovery tests for active goal reload, task graph reload, active allocation reload, worker cooldown preservation, unknown in-flight attempt handling, approved-memory-only hydration, and no default expensive LLM sidecar call
- [x] T157 [P] [US10] Add workflow-agnostic tests proving chat, `/goal`, dashboard/API task, and worker delegation paths share allocator/degradation/health/recovery behavior
- [x] T168 [P] [US10] Add supervisor context gate tests proving raw stdout/stderr, unbounded terminal transcripts, worker watch streams, and log tails are rejected from supervisor context unless represented as bounded typed packets
- [x] T169 [P] [US10] Add worker runtime wrapper tests proving start, heartbeat, stream-ref, checkpoint, degraded/blocked, validation, and final events are emitted even when the worker model is unavailable, times out, or returns empty output
- [x] T170 [P] [US10] Add cheap progress summarizer sidecar tests proving low-cost reasoning tier use, timeout/budget enforcement, no foreground blocking, no task completion authority, and no policy/memory approval authority

### Implementation For Self-Healing Workflow Control Plane

- [x] T158 [US10] Implement task graph and task node schemas with JSON serialization suitable for `SessionDB.state_meta` or supervisor task ledger storage
- [x] T159 [US10] Implement task graph state helpers for create/update/list/get, dependency readiness, concurrency checks, owned-path conflict detection, and validation-gated completion
- [x] T160 [US10] Wire task graph ready-node dispatch into the allocator so parallel subtasks receive bounded worker allocation without overlapping unsafe ownership
- [x] T161 [US10] Implement health sidecar scanner for task ledger, task graph, allocations, worker health, heartbeats, and degradation events with bounded leases, timeout, scan limit, and idempotent actions
- [x] T162 [US10] Implement health sidecar recovery actions: update worker health, mark stale lease/no-progress, emit recovery packet, request reassignment, pause allocation with retry-after, and publish learning events
- [x] T163 [US10] Implement restart recovery loader for goals, task ledger, task graphs, allocations, worker health, hot memory, approved lessons, sidecar leases, and safe-to-resume decisions
- [x] T164 [US10] Add CLI/API observability: `hermes runtime health check --once --json`, `hermes runtime task-graph list/get --json`, and `hermes runtime recovery status/run --json`
- [x] T165 [US10] Run controlled upstream-vs-branch smoke tests proving the branch avoids repeated failed worker loops, preserves foreground responsiveness, and resumes safe work after restart
- [x] T171 [US10] Implement `SupervisorContextGate` helpers that accept only typed bounded worker packets and attach artifact refs instead of raw streams
- [x] T172 [US10] Wire worker runtime wrappers and worker-router/delegation paths to emit mandatory progress events and artifact refs into the runtime event bus/task ledger
- [x] T173 [US10] Implement progress summarizer sidecar that consumes worker progress events, uses the configured low-cost reasoning tier, emits compact checkpoints, and degrades to deterministic summaries when the model is unavailable
- [x] T174 [US10] Update Slack/dashboard/API observability to stream worker progress from event/log refs while keeping supervisor model context limited to accepted context-gate packets

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

- [x] T178 [P] [US11] Add benchmark environment tests proving upstream and branch runs use separate `HERMES_HOME`, separate artifact roots, shared workload definitions, and no cross-contamination
- [x] T179 [P] [US11] Add telemetry schema tests for token/cost/latency/context/path attribution across supervisor, planner, worker, judge, curator, dreaming, progress summarizer, QA, deployment, memory retrieval, and Slack/dashboard analysis
- [x] T180 [P] [US11] Add production gate tests proving rollout is blocked when branch quality regresses, sidecars block foreground work, urgent alerts are missing, memory approval boundaries are violated, or cost exceeds thresholds
- [x] T181 [P] [US11] Add workload pack fixture tests for review, implementation, QA, deployment, long-running goal, fallback, stale worker, repeated failure, multi-repo decomposition, and hallucinated completion cases

### Implementation For Production Evaluation Harness

- [x] T182 [US11] Implement benchmark workload dataclasses and JSON/YAML loader with repo refs, prompt, model/tool profile, expected artifacts, validation commands, and pass/fail rubric
- [x] T183 [US11] Implement isolated environment runner that can invoke upstream Hermes and branch Hermes with separate homes, worktrees, env files, and artifact roots
- [x] T184 [US11] Implement telemetry collector for model usage, latency, cost estimates, context admitted, raw bytes stored, worker attempts, sidecar runs, judge decisions, memory hits, validation results, notifications, and operator interventions
- [x] T185 [US11] Implement comparison report generator with upstream-vs-branch quality/cost/latency/context/self-learning metrics and production gate status
- [x] T186 [US11] Add CLI/API surfaces: `hermes runtime benchmark run --suite ... --json`, `hermes runtime benchmark report --run-id ... --json`, and `hermes runtime costs status --json`
- [x] T187 [US11] Add urgent Slack integration for benchmark failures and production-gate blocks
- [x] T188 [US11] Add CI/CD harness template that runs deterministic benchmark smoke on PRs and full long-horizon benchmark on scheduled/operator-triggered runs
- [x] T189 [US11] Run Azure VM side-by-side smoke: upstream clean Hermes vs branch Hermes on the Azure port workflow, recording token/cost/latency/quality/self-learning results

**Checkpoint**: Production readiness is based on measured upstream-vs-branch evidence, not anecdotal task success.

## Phase 15: Runtime Feature Toggles And E2E Runner (Priority: P12)

**Goal**: Add safe local/dev feature toggles and an end-to-end runner surface so runtime-affecting work can be tested without enabling enforcement or hidden sidecars by default.

**Independent Test**: Resolve all known runtime features from local state, set scoped overrides with bounded reasons, run CLI JSON commands, and verify experimental/runtime-affecting capabilities remain off unless explicitly enabled.

**Boundary**: Feature toggles do not rewrite commands, enable enforcement, call LLM sidecars, or introduce cloud production dependencies. Toggle state must be local, durable, tenant/repo scoped when requested, and safe to inspect through CLI/API-compatible JSON.

### Tests For Runtime Feature Toggles And E2E Runner

- [x] T192 [P] [US12] Add runtime feature definition/list JSON tests proving deterministic metadata, safe defaults, safety metadata, and no state writes for list-only inspection in `tests/hermes_cli/test_runtime_features.py`
- [x] T193 [P] [US12] Add default-off resolver and scoped durable override tests proving tenant/repo scoped state, restart persistence, source/default/override reporting, and enforcement disabled by default in `tests/hermes_cli/test_runtime_features.py`
- [x] T194 [P] [US12] Add reason safety tests proving `set` requires a reason, redacts secret-like values, bounds stored reason length, and never stores raw transcripts or unbounded logs in `tests/hermes_cli/test_runtime_features.py`
- [x] T195 [P] [US12] Add CLI JSON tests for `hermes runtime features list --json`, `status --json`, `set <feature_id> <on|off> --reason ... --json`, and unknown-feature failure in `tests/hermes_cli/test_runtime_features.py`
- [x] T196 [P] [US12] Add E2E runner schema tests for workload id, isolated `HERMES_HOME`, repo snapshot refs, feature-toggle snapshot, validation commands, and artifact roots
- [x] T197 [P] [US12] Add E2E runner safety tests proving no enforcement enablement, no raw transcript storage, no cross-tenant state reuse, and no default expensive sidecar calls
- [x] T198 [P] [US12] Add CLI/API JSON tests for `hermes runtime e2e run --suite ... --json` and `hermes runtime e2e status --run-id ... --json`
- [x] T199 [P] [US12] Add feature-gated smoke tests proving health sidecar, restart recovery, task graph, and benchmark harness remain skipped unless their toggles resolve enabled
- [x] T200 [P] [US12] Add state migration/idempotency tests for feature toggle records and E2E runner records in local `state.db`
- [x] T201 [P] [US12] Add docs contract tests or examples proving CLI JSON fields remain stable for dashboard/API callers

### Implementation For Runtime Feature Toggles And E2E Runner

- [x] T202 [US12] Define E2E runner dataclasses and JSON serialization for suites, runs, steps, validation evidence, artifacts, and feature snapshots
- [x] T203 [US12] Implement local E2E runner state helpers using `SessionDB.state_meta` or existing local state tables with bounded evidence only
- [x] T204 [US12] Implement isolated local/dev E2E runner execution that uses separate homes/artifact roots and records validation summaries without raw transcripts
- [x] T205 [US12] Add CLI/API-compatible JSON surfaces for E2E run/status with deterministic status, blockers, validation refs, and cost/context placeholders
- [x] T206 [US12] Wire feature-gated runtime smoke entry points so disabled features report skipped instead of running hidden background work
- [x] T207 [US12] Implement runtime feature definitions and resolver with safe/off defaults, source/default/override reporting, tenant/repo scoped durable local state, stable JSON, and unknown-feature errors in `hermes_cli/runtime_features.py`
- [x] T208 [US12] Add CLI wiring for `hermes runtime features list/status/set` with JSON output, required bounded reasons, secret redaction, and enforcement disabled by default in `hermes_cli/main.py`
- [x] T209 [US12] Document runtime feature toggle contract, local/dev storage, safety boundaries, and operator workflow in `docs/curator-policy-framework-architecture.md`
- [x] T210 [US12] Document E2E runner contract and example suites in `specs/001-learning-memory-runtime/contracts/`
- [x] T211 [US12] Run focused runtime feature, E2E runner, CLI JSON, py_compile, and diff hygiene validation
- [x] T212 [US12] Run a local/dev smoke proving features default skipped, scoped override enables only the requested tenant/repo, and enforcement remains false

**Checkpoint**: Runtime-affecting work is visible and testable through local feature toggles, but experimental features remain off until explicitly enabled and enforcement remains unavailable by default.

## Phase 16: Tenant Platform Onboarding And Scaling (Priority: P13)

**Goal**: Define and implement the tenant onboarding/control-plane layer so enterprise tenants and power users can connect repos, communication channels, toolsets, budgets, and isolated runtime cells before submitting jobs.

**Independent Test**: Onboard a tenant, register a repo, connect a communication route, assign a toolset profile, provision a runtime cell, submit a Spec Kit-backed job, and verify tenant-scoped observability, cost, memory, and fault records without cross-tenant leakage.

**Boundary**: Start with schemas, local/dev adapters, and E2E smoke. Do not require Kafka, Kubernetes, vector DB, graph DB, or full marketplace behavior before the control-plane shape is proven.

### Spec And Architecture Artifacts

- [x] T213 [US13] Add `docs/tenant-platform-architecture.md` defining control plane, tenant runtime cells, repo onboarding, communication connectors, toolset profiles, isolation, memory, admin dashboard, cost, deployment, and bus options
- [x] T214 [US13] Add tenant onboarding contract covering registry, repo registration, communication connector, toolset profile, runtime cell, budget, feature profile, and smoke-test schemas
- [x] T215 [US13] Link tenant onboarding architecture from dashboard, observability, memory, and deployment docs

### Tests For Tenant Onboarding

- [x] T216 [P] [US13] Add tenant registry schema tests for tenant status, isolation mode, users/roles, budgets, feature profile, runtime cell assignment, and audit metadata
- [x] T217 [P] [US13] Add repo onboarding tests for provider refs, clone URL, branch policy, protected paths, validation commands, deployment mapping, secret refs, Spec Kit policy, and memory sharing policy
- [x] T218 [P] [US13] Add communication connector tests for Slack, Telegram, WhatsApp, dashboard/API route registration, tenant/user/channel allowlists, urgent routes, approval routes, and unauthorized sender rejection
- [x] T219 [P] [US13] Add toolset profile tests for planner, Spec Kit creator, code workers, QA/browser, TinyFish API/browser agent, CI/CD, deployment, cloud, repo, voice/image tools, scopes, budgets, and approval requirements
- [x] T220 [P] [US13] Add runtime cell isolation tests proving tenant homes, worktrees, secrets, memory, connectors, sidecars, and cost ledgers do not cross boundaries
- [x] T221 [P] [US13] Add tenant budget tests proving token/model/tool/sidecar budget exhaustion pauses or degrades jobs without looping
- [x] T221A [P] [US13] Add connector onboarding tests proving provided Slack/Telegram/WhatsApp credentials are stored as secret references, verified with a test message, and activated only after channel access succeeds
- [x] T221B [P] [US13] Add CI/CD pipeline task tests proving workflow creation/repair uses Spec Kit, secret references, protected environment approvals, validation evidence, rollback expectations, and urgent failure notification

### Implementation For Tenant Platform

- [x] T222 [US13] Implement tenant registry DTOs/state helpers with local SQLite/dev adapter and JSON serialization
- [x] T223 [US13] Implement repo registration DTOs/state helpers and read-only repo preflight output
- [x] T224 [US13] Implement communication connector registration DTOs/state helpers with adapter-neutral route metadata
- [x] T225 [US13] Implement toolset profile DTOs/state helpers and merge logic with job-level overrides
- [x] T226 [US13] Implement runtime cell assignment model for dedicated and pooled modes with isolation metadata
- [x] T227 [US13] Implement tenant-scoped job submission packet builder that feeds the existing supervisor task packet path
- [x] T228 [US13] Add CLI/API-compatible surfaces for tenant onboarding: `hermes tenant create/status`, `hermes tenant repo add/preflight`, `hermes tenant connector add/status`, `hermes tenant toolset set/status`, and `hermes tenant smoke --json`
- [x] T229 [US13] Add admin dashboard DTOs for tenants, runtime cells, connectors, repos, jobs, faults, worker health, sidecar health, cost, memory flow, and urgent alerts
- [x] T230 [US13] Add E2E onboarding smoke fixture that proves a tenant can submit a Spec Kit-backed job through a registered connector with isolated runtime state
- [x] T231 [US13] Implement connector-normalized tenant message envelope and reply/approval/urgent route DTOs
- [x] T232 [US13] Implement CI/CD toolset profile DTOs and worker packet builder for pipeline create/repair/run/validate/report tasks

**Checkpoint**: Multiple tenants can be represented, isolated, observed, budgeted, and smoke-tested before production multi-tenant deployment begins.

## Phase 17: Skill And Memory Pipeline (Priority: P14)

**Goal**: Connect procedural skills to the memory pipeline so skills are selected, injected, validated, evolved, scoped, and optionally synced through SkillClaw without bypassing tenant, memory, or approval gates.

**Independent Test**: Run a tenant-scoped CI/CD or TinyFish QA task whose classifier matches an approved skill. Verify bounded skill packet injection, role-specific worker skill refs, validation feedback, and no cross-tenant leakage.

**Boundary**: Skills are advisory execution aids. They do not replace memory, policy, validation, or approval. SkillClaw is optional adapter infrastructure, not the source of truth for memory.

### Spec And Architecture Artifacts

- [x] T233 [US14] Add `docs/skill-memory-pipeline-architecture.md` defining memory vs skill boundaries, retrieval, injection points, authority, evolution, tenant/global libraries, SkillClaw modes, and E2E tests
- [x] T234 [US14] Add skill pipeline contract covering skill metadata, retrieval query, packet schema, outcome feedback, candidate state, and SkillClaw adapter interface
- [x] T235 [US14] Link skill pipeline architecture from tenant platform, memory wiki, dreaming, and E2E feature testing docs

### Tests For Skill Retrieval And Injection

- [x] T236 [P] [US14] Add skill metadata schema tests for id, version, scope, tenant/repo/toolset/worker/task metadata, approval state, safety state, content hash, source refs, validation refs, usage stats, and retirement state
- [x] T237 [P] [US14] Add skill retrieval tests proving tenant/repo/toolset/worker-role/safety/approval hard filters run before semantic ranking
- [x] T238 [P] [US14] Add bounded skill packet tests proving supervisor, planner, worker, QA, browser, and deployment contexts receive only relevant skill summaries or refs
- [x] T239 [P] [US14] Add disabled-skill-feature tests proving skill retrieval/injection can be turned off without breaking baseline memory retrieval or delegation
- [x] T240 [P] [US14] Add cross-tenant skill isolation tests proving tenant-private skills never appear in other tenant packets

### Tests For Skill Evolution And SkillClaw

- [x] T241 [P] [US14] Add skill outcome feedback tests for helpful, irrelevant, harmful, and unknown impact per task/session/skill version
- [x] T242 [P] [US14] Add skill candidate tests proving approved memory/wiki can propose skill creation/update but cannot publish without validation and approval
- [x] T243 [P] [US14] Add harmful skill demotion tests proving failed validation creates repair/retire candidates and lowers retrieval confidence
- [x] T244 [P] [US14] Add SkillClaw adapter tests for local bundle read/write, content hash/version preservation, validation result ingestion, and disabled shared sync by default
- [x] T245 [P] [US14] Add E2E skill test using a CI/CD or TinyFish QA skill from retrieval through worker dispatch, validation, feedback, and candidate evolution

### Implementation For Skill Pipeline

- [x] T246 [US14] Implement skill metadata DTOs/state helpers and local registry adapter
- [x] T247 [US14] Implement skill retrieval query builder using existing task classifier metadata
- [x] T248 [US14] Implement skill scorer with hard filters, lexical/semantic hooks, scope penalties, confidence, recency, and usage feedback
- [x] T249 [US14] Implement bounded skill packet builder for supervisor/planner/worker/QA/browser/deployment roles
- [x] T250 [US14] Add skill refs to supervisor task packets, planner packets, worker delegation packets, validation reports, and session summaries
- [x] T251 [US14] Implement skill outcome feedback recording and confidence/demotion helpers
- [x] T252 [US14] Implement skill candidate creation from approved memory/wiki records
- [x] T253 [US14] Implement optional SkillClaw adapter interface for local bundle read/write, validation status, and tenant/global sync hooks
- [x] T254 [US14] Add CLI/API-compatible surfaces for `hermes skills runtime search`, `hermes skills runtime packet`, `hermes skills feedback`, and `hermes skills candidates --json`

**Checkpoint**: Skills can improve repeated task execution without context bloat, cross-tenant leakage, raw-session publishing, or hidden enforcement.

## Phase 18: Dreaming Integration Revision (Priority: P15)

**Goal**: Update dreaming for tenant runtime cells, global memory, SkillClaw/skills, CI/CD automation, E2E testing, and dashboard review while keeping dreaming proposal-only.

**Independent Test**: Run local and global dreaming fixtures. Verify local proposals stay tenant/repo scoped, global proposals use only redacted shareable evidence, skill/CI/CD/test proposals require judge/operator conversion, and no proposal mutates runtime directly.

**Boundary**: This phase revises dreaming integration. It must not enable direct prompt injection, skill publishing, config mutation, goal queueing, policy enforcement, repo edits, deployment, or training export from dreaming output.

### Spec And Architecture Artifacts

- [x] T255 [US15] Add `docs/dreaming-integration-architecture.md` covering local/global dreaming, inputs, outputs, triggers, approval flow, skill integration, CI/CD/test proposals, dashboard review, toggles, E2E tests, and failure modes
- [x] T256 [US15] Add dreaming integration contract covering proposal types, evidence packet schema, conversion targets, validator output, judge/operator state, dashboard DTOs, and feature toggles
- [x] T257 [US15] Link dreaming integration architecture from skill pipeline, tenant platform, global memory wiki, E2E feature testing, and production evaluation docs

### Tests For Dreaming Integration

- [x] T258 [P] [US15] Add local dreaming tests proving proposals remain tenant/repo scoped and cannot publish globally
- [x] T259 [P] [US15] Add global dreaming tests proving only redacted approved shareable global memory/wiki evidence is consumed
- [x] T260 [P] [US15] Add proposal schema tests for skill candidate, skill repair, test gap, CI/CD hardening, memory wiki update, routing improvement, allocator policy candidate, observability gap, tenant onboarding improvement, toolset recommendation, cost optimization, training corpus candidate, and architecture review item
- [x] T261 [P] [US15] Add conversion-gate tests proving dreaming proposals require deterministic validation, judge review, and operator or tenant-admin approval before becoming memory/wiki/skill/test/policy/goal/training candidates
- [x] T262 [P] [US15] Add negative tests proving dreaming cannot inject prompts, publish skills, update wiki, change config, queue goals, enforce policy, edit repos, deploy code, or export training data directly
- [x] T263 [P] [US15] Add dashboard/API tests for listing proposals by tenant, repo, proposal type, risk, status, evidence refs, expected benefit, judge decision, and operator action history
- [x] T264 [P] [US15] Add feature-toggle tests proving disabled dreaming records skipped-by-toggle and produces no proposal

### Implementation For Dreaming Integration

- [x] T265 [US15] Extend dreaming proposal DTOs with proposal type, affected feature ids, conversion target, expected benefit, forbidden direct actions, suggested validation, and tenant/global role metadata
- [x] T266 [US15] Add local/global dreaming role resolver and input builder with strict evidence filters
- [x] T267 [US15] Add proposal validators for skill, CI/CD, test-gap, routing, cost, training, and architecture proposal types
- [x] T268 [US15] Add conversion helpers that create downstream candidates only after judge/operator approval
- [x] T269 [US15] Add dashboard/observability DTOs for dreaming proposal review and approval history
- [x] T270 [US15] Add CLI/API-compatible surfaces for `hermes memory dream proposals --json`, `hermes memory dream convert --json`, and proposal status filtering
- [x] T271 [US15] Add E2E fixture proving dreaming can propose a SkillClaw skill repair and CI/CD hardening task without mutating runtime until approved

**Checkpoint**: Dreaming can generate valuable improvement work while remaining isolated, reviewable, tenant-scoped, and non-authoritative.

## Phase 19: Lesser-Model Corpus Remittance For External MLOps (Priority: P16)

**Goal**: Create the Hermes-owned corpus collection, curation, approval, and remittance layer where lesser-model failures and stronger-model rectifications become approved training records for an external MLOps platform.

**Independent Test**: Export approved failure/repair and preference-pair records into a reproducible local JSONL bundle with manifest, redaction report, approval provenance, destination metadata, remittance receipt, and external training hints. Verify no raw transcript, secret, or unapproved tenant data is exported. Verify Hermes does not create training jobs, model registry entries, deployment gates, or model rollout decisions.

**Boundary**: Runtime sidecars may create training candidates and corpus bundles, but they must not train, register, deploy, promote, or schedule model jobs. Fine-tuning, model registry, validation gates, serving, and canary rollout run only in external MLOps infrastructure.

### Spec And Architecture Artifacts

- [x] T272 [US16] Add `docs/lesser-model-mlops-architecture.md` defining Hermes-owned failure/repair corpus collection, curation, remittance, external MLOps handoff, destination storage layout, and external training/evaluation responsibilities
- [x] T273 [US16] Add MLOps corpus remittance contract covering failure/repair records, preference pairs, destination metadata, external training hints, remittance receipts, and storage layouts
- [x] T274 [US16] Link MLOps architecture from training corpus, global memory wiki, benchmark harness, sidecar model-tier, and tenant platform docs

### Tests For Training Corpus MLOps

- [x] T275 [P] [US16] Add failure/repair training record schema tests covering lesser-model attempt summary, failure classification, evidence refs, strong-model diagnosis, correction refs, validation refs, distilled lesson, forbidden behavior, redaction, and approval provenance
- [x] T276 [P] [US16] Add SFT message record tests and preference-pair tests for chosen validated repair vs rejected lesser-model failure
- [x] T277 [P] [US16] Add local JSONL bundle tests for stable manifest, hashes, redaction report, approval provenance, dataset-family filters, tenant/shareability boundaries, and no raw transcript/secret export
- [x] T278 [P] [US16] Add Delta/Iceberg-compatible destination layout metadata tests using local fake paths only, proving partition fields and schema versions are stable without requiring production services
- [x] T279 [P] [US16] Add external training hint tests for target base model family, recommended method, corpus refs, eval refs, and approval state without creating Hermes-owned training jobs
- [x] T280 [P] [US16] Add remittance receipt tests for destination URI, bundle hash, schema version, approval refs, external pipeline id, submitted_at, and immutable audit status
- [x] T281 [P] [US16] Add boundary tests proving Hermes cannot register, deploy, promote, or route to a fine-tuned model from corpus remittance output alone

### Implementation For Training Corpus MLOps

- [x] T282 [US16] Implement MLOps training corpus DTOs for failure/repair records, SFT records, preference pairs, manifests, redaction reports, and approval provenance
- [x] T283 [US16] Implement local JSONL bundle writer with deterministic ordering, stable hashes, schema version, and reproducibility metadata
- [x] T284 [US16] Implement Delta/Iceberg-compatible destination layout planner without adding production storage dependencies
- [x] T285 [US16] Implement external training hint builder for SFT, DPO/ORPO, LoRA, QLoRA, and full fine-tune recommendations without scheduling jobs
- [x] T286 [US16] Implement remittance receipt writer for local/dev audit records after bundle handoff to configured storage
- [x] T287 [US16] Implement external MLOps handoff validator proving required approval, redaction, tenant/shareability, schema, and hash fields are present before remittance
- [x] T288 [US16] Add CLI/API-compatible surfaces for `hermes mlops corpus export`, `hermes mlops corpus remit`, `hermes mlops corpus receipts`, and `hermes mlops corpus validate --json`
- [x] T289 [US16] Add E2E fixture proving a Gemma-class lesser-model failure plus Codex/strong-model rectification can produce approved local training records and a remittance receipt, while Hermes remains unable to train or deploy a model

**Checkpoint**: Hermes can create and remit high-quality offline training data for cheaper coding models while keeping runtime memory, corpus export, external training, registry, and deployment separate.

## Phase 20: Azure Production Deployment Orchestration (Priority: P17)

**Goal**: Add a production-deployment-ready Azure workflow where Hermes chat can orchestrate plan, preflight, IaC artifact generation, apply, status, smoke, soak, promote, and rollback while requiring operator approval before paid or dangerous changes.

**Independent Test**: With fake Azure adapters and local templates only, produce a deployment plan with explicit Azure resource classes, generate Terraform-first artifacts, run preflight, block apply without approval, apply a staging plan with approval, emit smoke/soak checklists, refuse production promotion without evidence, and produce a rollback report. Verify no live Azure resources are created during default tests.

**Boundary**: This phase creates deployment orchestration contracts, DTOs, templates, CLI/API surfaces, and fake-adapter tests. It must not create live Azure resources by default. SQLite remains the default local bus/spool and Azure bus/storage failures must not block foreground runtime.

### Spec And Architecture Artifacts

- [x] T290 [US17] Add `contracts/azure-production-deployment.md` defining Azure deployment profiles, plan/preflight/apply/status/promote/rollback outputs, approval gates, and non-goals
- [x] T291 [US17] Add `docs/azure-production-deployment-architecture.md` covering local/dev, Azure staging, Azure production, chat orchestration, Event Hubs vs Redpanda choices, Azure object/state/secrets/observability resource targets, scalability, readiness gates, and first implementation slice
- [x] T292 [US17] Link Azure deployment orchestration from tenant platform, production evaluation harness, global memory wiki, runtime learning, and deployment docs

### Tests For Azure Deployment Orchestration

- [x] T293 [P] [US17] Add deployment profile schema tests for dev/staging/production, runtime-cell mode, bus backend, ADLS/Blob object storage containers, PostgreSQL/Cosmos state store, Key Vault, Azure Monitor/Application Insights, network/DNS, IaC format, and approval requirements
- [x] T294 [P] [US17] Add plan/preflight tests with fake Azure adapters covering subscription visibility, quota, resource providers, Key Vault, object storage, state store, bus, observability workspace, DNS/network, required secret refs, cost estimate, IaC artifact refs, and rollback path
- [x] T295 [P] [US17] Add approval gate tests proving apply/promote/destroy/DNS/secret-rotation operations fail closed without explicit operator approval
- [x] T296 [P] [US17] Add bus deployment readiness tests for Event Hubs Kafka protocol and Redpanda/Kafka helper templates, broker health, topic verification, dead-letter/replay, lag metrics, TLS/SASL config shape, and SQLite spool fallback
- [x] T297 [P] [US17] Add smoke/soak/promotion tests proving staging must pass health, event bus, sidecar, memory retrieval, urgent alert, cost/latency, and no-foreground-blocking checks before production promotion
- [x] T298 [P] [US17] Add rollback/status tests proving a failed deployment produces sanitized status, rollback refs, and operator action items without leaking secrets

### Implementation For Azure Deployment Orchestration

- [x] T299 [US17] Implement Azure deployment profile DTOs and local profile loader with explicit compute/bus/object-storage/state-store/secrets/observability/network/IaC sections and redacted JSON serialization
- [x] T300 [US17] Implement fake Azure adapter interfaces for plan/preflight tests without live Azure dependency
- [x] T301 [US17] Implement deployment plan builder with resource diff, Terraform-first artifact refs, cost estimate placeholder, required secret refs, risk list, smoke/soak plan, and rollback plan
- [x] T302 [US17] Implement preflight evaluator for Azure account/subscription/quota/provider/object-storage/state-store/Key Vault/bus/observability/network/DNS checks using fake adapters by default
- [x] T303 [US17] Implement approval-gated apply/promote/destroy decision helpers and immutable deployment run records
- [x] T304 [US17] Implement Event Hubs Kafka, Redpanda/Kafka, ADLS/Blob object storage, PostgreSQL/Cosmos state store, Key Vault, Azure Monitor/Application Insights, ingress/network, and SQLite spool fallback deployment helper templates, without creating live resources by default
- [x] T305 [US17] Implement smoke/soak checklist generator and production promotion gate evaluator
- [x] T306 [US17] Add CLI/API JSON surfaces for `hermes deploy plan/preflight/apply/status/smoke/soak/promote/rollback --target azure`
- [x] T307 [US17] Add E2E fixture proving chat/API can orchestrate Azure staging deployment flow with fake adapters, explicit approval, smoke/soak evidence, and blocked production promotion without approval

**Checkpoint**: Hermes can safely orchestrate Azure deployment workflows through gated artifacts while keeping live production resource creation, DNS changes, secret rotation, traffic promotion, and rollback under explicit operator control.

## Phase 21: Platform Hardening And Gap Closure (Priority: P18)

**Goal**: Close cross-cutting production loopholes that span memory, sidecars, dreaming, tenant runtime, workers, event bus, MLOps corpus, and Azure deployment.

**Independent Test**: Run a hardening suite that attempts approval replay, mismatched feature/deployment config, duplicate/replayed bus events, sidecar over-budget execution, raw worker stream injection, stale/harmful memory retrieval, dreaming proposal flood, and unsafe Azure production apply. Verify every case fails closed without blocking foreground runtime.

**Boundary**: This phase must not add new autonomous behavior. It adds shared deterministic gates, ledgers, effective-state views, budget checks, and lifecycle controls.

### Spec And Architecture Artifacts

- [x] T308 [US18] Add `contracts/platform-hardening.md` covering shared approval ledger, effective runtime profile, canonical bus envelope, sidecar budget governor, context-gate coverage, memory quality lifecycle, dreaming backlog control, and Azure production hardening
- [x] T309 [US18] Add `docs/platform-hardening-gap-review.md` summarizing closed gaps, remaining gaps, and mitigation principles

### Tests For Platform Hardening

- [x] T310 [P] [US18] Add shared approval ledger tests for memory promotion, dreaming conversion, deployment apply/promote/destroy, corpus remittance, policy enforcement, and protected CI/CD actions, proving approvals are actor/role/tenant/action/target-hash bound, expiring, non-replayable, and audit-linked
- [x] T311 [P] [US18] Add effective runtime profile tests proving feature toggles, sidecar tiers, tenant/repo policy, toolset profile, deployment profile, worker health, budgets, and memory retrieval mode merge into one explainable read-only view
- [x] T312 [P] [US18] Add canonical bus envelope/redrive tests for SQLite and Kafka-compatible paths, proving event id, idempotency key, partition key, redaction state, replay attempt, dead-letter reason, and consumer idempotency semantics
- [x] T313 [P] [US18] Add sidecar budget governor tests proving LLM-backed sidecars are denied or degraded when tenant/task/day/token/cost budgets are exceeded while exact-memory-hit programmatic paths still run
- [x] T314 [P] [US18] Add worker-path context gate integration tests proving Claude, Codex, DeepSeek, browser/TinyFish, and generic worker wrappers cannot stream raw stdout/stderr/watch/log tails into supervisor context
- [x] T315 [P] [US18] Add memory quality lifecycle tests for stale suppression, confidence decay, harmful/ignored feedback demotion, retirement, compaction, and audit history preservation
- [x] T316 [P] [US18] Add dreaming backlog control tests for tenant quota, proposal-type quota, risk quota, duplicate suppression, max-age archival, and operator-visible backlog summary
- [x] T317 [P] [US18] Add Azure hardening gate tests proving live production apply/promote is blocked unless managed identity, RBAC, private endpoints, VNet integration, ingress, diagnostics, storage lifecycle policy, Key Vault access, rollback artifacts, and explicit approval are valid

### Implementation For Platform Hardening

- [x] T318 [US18] Implement shared approval ledger DTOs/state helpers/CLI or API JSON inspection surface with redacted immutable approval records
- [x] T319 [US18] Implement effective runtime profile resolver and JSON surface for task dispatch and deployment preflight
- [x] T320 [US18] Implement canonical bus envelope helpers and idempotent redrive/dead-letter DTOs used by SQLite and Kafka-compatible adapters
- [x] T321 [US18] Implement sidecar budget governor integrated with sidecar role routing before LLM-backed sidecar calls
- [x] T322 [US18] Implement worker-path context gate audit helpers and wrapper compliance checks for all configured worker families
- [x] T323 [US18] Implement memory quality lifecycle compaction/demotion helpers and safe operator/status output
- [x] T324 [US18] Implement dreaming backlog controls and observability summaries
- [x] T325 [US18] Implement Azure production hardening evaluator and wire it into deployment preflight/promotion gates
- [x] T326 [US18] Add E2E hardening fixture proving all hardening gates fail closed and foreground runtime remains non-blocking

**Checkpoint**: Production hardening gates are shared, deterministic, observable, and fail closed without adding hidden loops or foreground drag.

## Phase 22: Operator Dashboard And Approval UI (Priority: P19)

**Goal**: Build a lean production operator dashboard over existing Hermes observability, tenant, memory, sidecar, bus, benchmark, approval, and Azure deployment surfaces.

**Independent Test**: Run a seeded dashboard fixture containing tenants, jobs, workers, sidecars, approvals, memory packets, corpus exports, bus events, benchmarks, and Azure deployment records. Verify list/detail/filter/approval/scoped-Ask flows return redacted bounded DTOs, perform no mutation without approval, and do not load raw transcripts into model context.

**Boundary**: The dashboard is not a second agent or a raw-log browser. It consumes bounded DTOs and routes dangerous actions through existing approval/deployment/memory/feature APIs.

### Spec And Architecture Artifacts

- [x] T327 [US19] Add `contracts/operator-dashboard.md` covering jobs, job detail, approval inbox, sidecar health, cost/context, deployment, and scoped Ask DTO boundaries
- [x] T328 [US19] Add `docs/operator-dashboard-architecture.md` defining lean UI principles, views, data flow, non-goals, and rollout order

### Tests For Operator Dashboard

- [x] T329 [P] [US19] Add dashboard seed fixture tests covering tenants, repos, jobs, worker attempts, sidecars, memory packets, approvals, corpus exports, bus events, benchmarks, and Azure deployments
- [x] T330 [P] [US19] Add jobs table API/UI DTO tests for tenant/repo/date/status/worker/model/blocker/cost/deployment filters and redacted row summaries
- [x] T331 [P] [US19] Add job detail tests for lazy Overview, Agents, Spec Kit, Memory, Validation, Sidecars, Bus Events, Costs, Deployment, and Ask tabs
- [x] T332 [P] [US19] Add approval inbox tests proving memory, dreaming, corpus, deployment, CI/CD, and policy actions write through the shared approval ledger and reject replay/mismatched target hash
- [x] T333 [P] [US19] Add sidecar and bus health panel tests for role/tier/model/budget/backlog/lag/DLQ/spool/degraded state without secrets
- [x] T334 [P] [US19] Add cost/context panel tests for token, estimated cost, latency, context admitted, sidecar calls, memory hits, worker attempts, and benchmark attribution
- [x] T335 [P] [US19] Add scoped Ask dashboard tests proving only read-only bounded evidence bundles are sent to the LLM and mutation tools are unavailable
- [x] T336 [P] [US19] Add Azure deployment panel tests for plan/preflight/apply/smoke/soak/promote/rollback state, hardening failures, costs, and required operator actions

### Implementation For Operator Dashboard

- [x] T337 [US19] Implement dashboard DTO aggregator using existing runtime observability, tenant, memory, sidecar, bus, benchmark, approval ledger, and Azure deployment surfaces
- [x] T338 [US19] Implement jobs list and lazy job-detail JSON routes or backend surfaces with strict tenant scoping and redaction
- [x] T339 [US19] Implement approval inbox backend surfaces backed by shared approval ledger actions
- [x] T340 [US19] Implement sidecar, bus, cost/context, and deployment dashboard summary surfaces
- [x] T341 [US19] Implement scoped Ask evidence-bundle builder for dashboard job analysis with read-only/no-mutation guarantees
- [x] T342 [US19] Implement minimal dashboard UI shell or existing-dashboard integration for jobs, detail drawer, approval inbox, sidecar/bus/cost/deployment panels, and scoped Ask
- [x] T343 [US19] Add E2E dashboard smoke fixture proving seeded state is visible, dangerous actions fail closed without approval, and raw logs/transcripts are never loaded

**Checkpoint**: Operator can inspect active and historical work, approve high-risk actions, see platform health/cost, and ask scoped analytical questions without raw context bloat or unsafe mutation paths.

## Phase 23: Production Runtime Closure (Priority: P20)

**Goal**: Convert live VM findings into production-grade runtime guarantees for Claude/Codex workers, goal judge, curator, learning judge, sidecars, skills, memory injection, Slack/dashboard alerts, and cost/context telemetry.

**Independent Test**: Run a service-equivalent production smoke that uses Claude as primary worker, Codex as fallback/judge path, curator and learning judge enabled, sidecars in bounded one-shot mode, Slack/dashboard notifications configured, and enforcement disabled. Verify no secrets persist, goal judge invokes the configured model role, runtime failures become advisory candidates, judge decisions fail closed, skill evolution is approval-gated, and follow-up task packets receive scoped approved guidance only.

**Boundary**: This phase must not enable enforcement or introduce a hidden autonomous loop. It closes unsafe integration gaps and proves advisory learning operates safely under production-like execution.

### Spec And Architecture Artifacts

- [x] T344 [US20] Add `contracts/production-runtime-closure.md` covering secret-safe capture, service-resolved model roles, goal judge invocation, sidecar service operation, rich runtime failure evidence, skill evolution, and production smoke gates
- [x] T345 [US20] Add `docs/production-runtime-closure-architecture.md` summarizing live VM findings, production principles, sidecar deployment, goal judge boundary, secret safety, skill evolution, and final smoke requirements

### Tests For Production Runtime Closure

- [x] T346A [P] [US20] Add context admission tests proving raw worker streams, long command outputs, sidecar logs, Slack mirrors, repeated status reports, and full Spec Kit artifacts are classified as summarize/store-only/reject instead of direct supervisor admission
- [x] T346B [P] [US20] Add worker event store tests proving full worker/tool/sidecar updates are persisted as redacted event/artifact refs and can be listed for UI/audit without entering model context
- [x] T346C [P] [US20] Add progress checkpoint tests proving bounded task checkpoints stay under configured token caps and contain current task, latest progress, blocker, next action, validation refs, memory refs, and artifact refs
- [x] T346D [P] [US20] Add supervisor prompt/context tests proving long worker update streams do not trigger preflight compression for simple follow-up questions because only checkpoints and refs are admitted
- [x] T346 [P] [US20] Add pre-persistence redaction tests proving provider-shaped secrets in commands, env files, tool output, worker excerpts, bus payloads, candidates, Slack/dashboard messages, and corpus records are scrubbed before storage
- [x] T347 [P] [US20] Add model-role doctor tests proving Codex/Claude/curator/learning_judge/goal_judge resolve consistently under CLI, SSH non-login shell, gateway service env, and sidecar service env
- [x] T348 [P] [US20] Add goal judge invocation tests proving `hermes runtime control goal` calls the configured `goal_judge` role when enabled and returns structured degraded status when unavailable
- [x] T349 [P] [US20] Add sidecar service-readiness tests for one-shot and daemon/timer modes, including lock acquisition, budget gate, interval/deadline, backlog limit, degraded reason, and foreground non-blocking behavior
- [x] T350 [P] [US20] Add rich `supervisor_runtime_failure` metadata tests covering supervisor, delegated worker, allocator, and goal paths with task id, tenant/repo, worker family, requested route, actual route, command family, status, latency, allocation refs, validation mismatch, and redacted evidence refs
- [ ] T351 [P] [US20] Add sparse-evidence curator/judge tests proving insufficient runtime failure records become diagnostics or needs-human outcomes, not reusable approved lessons
- [ ] T352 [P] [US20] Add skill evolution E2E tests for failure or approved memory -> skill candidate -> judge -> operator approval -> bounded skill packet -> outcome feedback -> demotion/repair on harmful feedback
- [ ] T353 [P] [US20] Add production learning-loop smoke tests for Claude primary, Claude degraded, Codex fallback/code-critical path, runtime capture, curator, judge, advisory memory injection, Slack/dashboard alert, and cost/context telemetry
- [x] T353A [P] [US20] Add runtime impact UI/API tests proving live sidecars are grouped by category and by job, memory activity is grouped by job, and foreground latency is separated from asynchronous sidecar latency
- [x] T353B [P] [US20] Add latency attribution tests for baseline task latency, memory retrieval latency, allocator latency, validation latency, notification latency, curator/judge latency, sidecar background latency, token cost, and context admitted

### Implementation For Production Runtime Closure

- [x] T354A [US20] Implement `hermes_cli/context_admission.py` with deterministic `admit`, `summarize`, `store_only`, and `reject` decisions plus token/size/repetition/raw-log rules
- [x] T354B [US20] Implement `hermes_cli/worker_event_store.py` for durable worker/tool/sidecar event storage with redacted event/artifact refs and bounded listing APIs
- [x] T354C [US20] Implement `hermes_cli/progress_checkpoint.py` for programmatic or cheap-tier checkpoint generation capped to 500-1000 tokens per task by default
- [x] T354D [US20] Patch supervisor context/prompt construction to inject only current task state, latest progress checkpoint, relevant memory packet, and evidence refs instead of every worker update
- [x] T354 [US20] Implement centralized pre-persistence redaction guard and apply it to runtime failure capture, memory records, evidence excerpts, learning bus events, candidates, sidecar jobs, Slack/dashboard DTOs, and corpus export inputs
- [x] T355 [US20] Implement model-role doctor JSON surface for provider/model/tier/path/auth readiness, degraded reason, timeout, budget, and service-environment parity without printing secrets
- [x] T356 [US20] Fix `goal_judge` Codex/auxiliary invocation so goal evaluation calls the configured model role or returns structured degraded status with audit metadata
- [x] T357 [US20] Implement sidecar service/timer readiness surfaces and service-equivalent one-shot runner for curator, learning judge, dreaming, wiki, bus consumer, sync, progress summarizer, and housekeeping
- [x] T358 [US20] Enrich `supervisor_runtime_failure` capture across supervisor, delegated worker, allocator, and goal paths with bounded metadata and redacted evidence refs
- [ ] T359 [US20] Tighten curator runtime-failure synthesis so sparse records cannot create high-confidence reusable lessons without sufficient evidence and judge/operator gates
- [ ] T360 [US20] Implement skill evolution conversion helpers and approval-gated publication path from approved memory/wiki/runtime failure candidates into scoped runtime skills
- [ ] T361 [US20] Implement production runtime smoke CLI/API surface, e.g. `hermes runtime production-smoke --json`, with pass/fail report and redacted artifacts
- [x] T361A [US20] Implement runtime impact DTO aggregator over live state for sidecars by category, sidecars by job, memory activity timeline, and foreground/background latency attribution
- [x] T361B [US20] Wire runtime impact JSON into dashboard/API surfaces and minimal UI panel, preserving lazy loading and redaction
- [ ] T362 [US20] Update release readiness report generation to include production closure gates, live VM command evidence, cost/context totals, runtime impact UI evidence, sidecar status, and known blockers
- [ ] T363 [US20] Run VM production closure smoke and runtime impact UI/API smoke, then record results in `docs/runtime-learning-release-readiness.md`

**Checkpoint**: Runtime-learning is production-closure-ready only after the VM smoke proves secret-safe capture, service-resolved model roles, model-backed goal judge or explicit degradation, sidecar readiness, skill evolution, advisory memory injection, runtime impact UI/API, and cost/context telemetry.

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
- User Story 12 depends on existing feature contracts and should run before User Story 11 aggregate benchmarking so each feature can be isolated and toggled safely.
- User Story 13 depends on supervisor packets, observability, memory scope, feature toggles, and E2E smoke enough to safely expose the platform to multiple tenants.
- User Story 14 depends on task classifier metadata, tenant scope, memory retrieval, feature toggles, and worker packet boundaries so skills can be injected safely.
- User Story 15 depends on existing dreaming storage, tenant/global scope, skill candidates, feature toggles, and observability so proposals can be reviewed without runtime mutation.
- User Story 16 depends on approved memory/wiki/training provenance, benchmark gates, and sidecar model-tier telemetry so offline fine-tuning data can be built safely.
- User Story 19 depends on observability, tenant DTOs, approval ledger, sidecar/bus/cost telemetry, Azure deployment DTOs, and platform hardening gates so the UI can stay bounded and safe.
- User Story 20 depends on User Stories 8, 9, 10, 14, 18, and 19 enough to prove the live production runtime loop with safe model roles, redaction, sidecars, skills, goal judge, and advisory learning.

## Parallel Opportunities

- Test files for runtime orchestration, judge, bus, wiki, dreaming, and jobs can be developed in parallel.
- Supervisor control-plane tests can be developed in parallel after runtime packet schemas and learning job helpers are stable.
- CLI contracts and docs can be updated in parallel with implementation after data-model fields stabilize.
- Dashboard/backend observability can start once `learning_jobs.py` exposes stable JSON.
- Low-end model eval fixtures and persisted lesson retrieval can be developed first. Realtime voice adapters, global bus adapters, production memory wiki backends, and training export tests are intentionally deferred until the core loop has measured value.
- Goal-allocation schema, decision, resume, and observability tests can be developed in parallel after the contract lands.
- Task graph, health sidecar, restart recovery, and workflow-agnostic tests can be developed in parallel after Phase 13 contracts land.
- Benchmark workload loader, telemetry schema, isolated runner, and report generator can be developed in parallel after Phase 14 contracts land.
- Feature toggle schema, E2E fixture definitions, and report writer can be developed in parallel after Phase 15 contracts land.
- Tenant registry, repo registration, connector registration, and toolset profile schemas can be developed in parallel after Phase 16 architecture lands.
- Skill metadata, retrieval, packet building, feedback, and SkillClaw adapter tests can be developed in parallel after Phase 17 architecture lands.
- Dreaming proposal-type validators, local/global input builders, dashboard DTOs, and conversion-gate tests can be developed in parallel after Phase 18 architecture lands.
- MLOps corpus schemas, local bundle writer, external training hints, and remittance receipt tests can be developed in parallel after Phase 19 architecture lands.
- Operator dashboard list, detail, approval inbox, sidecar/bus, cost, deployment, and scoped Ask tests can be developed in parallel after Phase 22 contracts land.
- Production closure redaction, model-role doctor, goal judge, sidecar service, runtime failure metadata, skill evolution, and production smoke tests can be developed in parallel after Phase 23 contracts land.

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
5. Revisit media/voice providers only as product-level connector work, not as core runtime-learning infrastructure.

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

### Phase 15 Order

1. Add feature toggle config schema, dependency validation, and safe defaults.
2. Add CLI/API-compatible feature list/status/set surfaces.
3. Add deterministic feature fixture registry and local E2E runner.
4. Add enabled/disabled tests for each major subsystem.
5. Add integrated failure-to-advisory-to-next-dispatch test with enforcement off.
6. Add Azure desktop chat/voice workload as an opt-in live-provider fixture.
7. Run deterministic E2E suite before Phase 14 aggregate benchmark.

### Phase 16 Order

1. Add tenant onboarding contract and schemas.
2. Add local/dev tenant registry and repo registration helpers.
3. Add communication connector and toolset profile helpers.
4. Add runtime cell assignment model and isolation checks.
5. Add tenant-scoped job submission into supervisor task packets.
6. Add admin observability DTOs.
7. Add tenant onboarding smoke test.
8. Decide production adapters for runtime cells, object storage, event bus, vector index, and graph index only after the local/dev model proves useful.

### Phase 17 Order

1. Add skill pipeline contract and metadata schema.
2. Add local skill registry adapter.
3. Add skill retrieval using task classifier metadata and hard scope filters.
4. Add bounded skill packets and packet refs.
5. Add skill feedback and demotion helpers.
6. Add skill candidates from approved memory/wiki records.
7. Add optional SkillClaw adapter.
8. Run E2E skill test for CI/CD or TinyFish QA.

### Phase 18 Order

1. Add dreaming integration contract and proposal type schema.
2. Add local/global role resolver and strict input builder.
3. Add validators for skill, CI/CD, test-gap, routing, cost, training, and architecture proposals.
4. Add conversion helpers behind judge/operator gates.
5. Add dashboard/API proposal review DTOs.
6. Add CLI/API proposal list/convert/status surfaces.
7. Add E2E fixture for skill repair and CI/CD hardening proposals.

### Phase 19 Order

1. Add MLOps corpus remittance contract.
2. Add failure/repair, SFT, and preference-pair schemas.
3. Add local JSONL bundle writer with manifest/redaction/approval metadata.
4. Add Delta/Iceberg-compatible destination layout planner.
5. Add external training hint metadata and remittance receipts.
6. Add boundary tests proving Hermes does not train, register, deploy, or promote models.
7. Add CLI/API surfaces.
8. Add E2E fixture for lesser-model failure -> strong-model repair -> training record -> external remittance receipt.

### Phase 20 Order

1. Add Azure deployment contract and architecture docs.
2. Add deployment profile and fake Azure adapter tests.
3. Add plan/preflight builders.
4. Add approval-gated apply/promote/rollback run records.
5. Add Event Hubs/Redpanda, object storage, state store, Key Vault, observability, ingress/network helper templates and SQLite fallback config.
6. Add smoke/soak/promotion gate outputs.
7. Add CLI/API JSON surfaces.
8. Add E2E fake-adapter staging deployment fixture.

### Phase 21 Order

1. Add shared approval ledger.
2. Add effective runtime profile resolver.
3. Add canonical bus envelope/redrive helpers.
4. Add sidecar budget governor.
5. Add worker-path context gate compliance checks.
6. Add memory quality lifecycle compaction/demotion.
7. Add dreaming backlog controls.
8. Add Azure production hardening evaluator.
9. Add integrated hardening E2E fixture.

### Phase 22 Order

1. Add operator dashboard contract and architecture.
2. Add seeded dashboard fixture covering jobs, workers, sidecars, memory, approvals, bus, costs, and deployments.
3. Add jobs table and lazy detail DTO tests.
4. Add approval inbox tests backed by shared approval ledger.
5. Add sidecar, bus, cost/context, deployment, and scoped Ask tests.
6. Implement dashboard DTO aggregator and JSON routes.
7. Implement minimal UI shell or existing-dashboard integration.
8. Add E2E dashboard smoke proving redaction, fail-closed approval, and no raw context bloat.

### Phase 23 Order

1. Add context admission, worker event store, progress checkpoint, and supervisor prompt tests first to stop context bloat immediately.
2. Add pre-persistence redaction tests and fix runtime capture before any more live smoke.
3. Add model-role doctor and service-environment parity checks for Codex, Claude, curator, learning judge, and goal judge.
4. Fix goal judge invocation so unavailable auxiliary clients produce structured degradation instead of implicit continuation.
5. Add sidecar service-readiness tests and one-shot service-equivalent runner.
6. Enrich runtime failure records and tighten sparse-evidence curator/judge behavior.
7. Prove skill evolution loop with judge/operator gates.
8. Add production runtime smoke command.
9. Add runtime impact UI/API for sidecars, memory activity, and latency attribution.
10. Run VM production closure smoke and update release readiness report.
