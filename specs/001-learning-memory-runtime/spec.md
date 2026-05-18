# Feature Specification: Runtime Learning Memory Framework

**Feature Branch**: `132-learning-memory-runtime`

**Created**: 2026-05-16

**Status**: Draft

**Input**: User description: "Merge Hermes with online upstream and use Spec Kit to implement the rest of the runtime learning work: learning judge, event bus, memory wiki, dreaming phase, injection/meta-based search, hot/warm/cold memory model, observability, and strict separation between raw events, curator candidates, wiki knowledge, dreaming proposals, and enforcement policies."

## User Scenarios & Testing

### User Story 1 - Supervisor Orchestration Protocol (Priority: P1)

As a Hermes operator or dashboard user, I want Hermes to turn ambiguous requests into scoped, memory-aware, Spec Kit-preserved work before dispatching agents, so implementation is reviewable, resumable, and consistent even when the user is non-technical.

**Why this priority**: This is the entry point for all serious work. Without a deterministic supervisor protocol, memory retrieval, planning, worker delegation, and git preservation remain prompt-dependent and hard to audit.

**Independent Test**: Submit a dashboard-style non-technical request and verify the supervisor runs initialization, asks scope questions when required, creates or updates Spec Kit artifacts, builds a memory packet, creates planner and worker packets, records validation, and refuses to mark work complete without required artifacts.

**Acceptance Scenarios**:

1. **Given** a non-trivial implementation request, **When** the supervisor initializes the task, **Then** it loads the constitution, classifies the task, retrieves relevant memory, creates a task packet, and routes planning through Spec Kit.
2. **Given** an ambiguous dashboard request, **When** required scope is missing, **Then** the supervisor asks concise clarification questions before planner/worker dispatch.
3. **Given** a task above the configured complexity threshold, **When** planning begins, **Then** the supervisor creates or updates a numbered branch/worktree and Spec Kit `spec.md`, `plan.md`, and `tasks.md`.
4. **Given** a worker is selected, **When** the task is dispatched, **Then** the worker receives a bounded delegation packet with repo, branch/worktree, objective, constraints, validation commands, memory packet, owned files, and return schema.
5. **Given** a worker returns results, **When** the supervisor validates completion, **Then** it checks the result against Spec Kit tasks, git diff, tests/logs, and memory outcome requirements before final response.

---

### User Story 2 - Judge Learning Candidates (Priority: P2)

As the Hermes operator, I want proposed learning candidates to be reviewed by a separate judge before they can become approved memory or enforcement policy, so that noisy or unsafe lessons do not alter future agent behavior.

**Why this priority**: This is the safety gate required before expanding self-learning beyond advisory retrieval.

**Independent Test**: Create proposed candidates with valid evidence, missing evidence, malformed judge output, and risky enforcement requests; run the judge command and verify approved, rejected, and needs-human states are deterministic.

**Acceptance Scenarios**:

1. **Given** a proposed candidate with valid evidence and low risk, **When** the learning judge approves it, **Then** the candidate records the judge decision and becomes eligible for approved memory.
2. **Given** a proposed candidate with missing evidence, **When** the learning judge evaluates it, **Then** the candidate is rejected or marked needs-human and is not enforced.
3. **Given** malformed judge output, **When** the judge runner parses the result, **Then** the system fails closed and records a parse failure without approving the candidate.

---

### User Story 3 - Durable Runtime Event Bus (Priority: P3)

As the Hermes supervisor, I want runtime events to be written to a durable local bus so sidecars can consume learning signals asynchronously without blocking chat, delegation, or tool execution.

**Why this priority**: Continuous work needs in-session learning signals, but foreground agents must not wait on curation or dreaming.

**Independent Test**: Publish tool-result, task-outcome, policy-audit, and candidate events; run a consumer once; verify lease, retry, consumed, and failed state transitions.

**Acceptance Scenarios**:

1. **Given** a terminal policy audit event, **When** the bus consumer runs, **Then** it creates or updates a candidate without blocking the original command.
2. **Given** a crashed consumer lease, **When** the lease expires, **Then** another consumer can reclaim the event.
3. **Given** repeated processing failures, **When** retry limits are reached, **Then** the event is marked failed with structured error metadata.

---

### User Story 4 - Retrieve And Inject Scoped Learning (Priority: P4)

As a worker or supervisor, I want only relevant approved learning context injected into a task prompt, so prior lessons help current work without overriding explicit instructions or current evidence.

**Why this priority**: Retrieval is already partially implemented; meta-based search, tiering, and source separation need to make it reliable.

**Independent Test**: Invoke tasks with different tenants, repos, tools, task types, and error signatures; verify the classifier creates a structured query, the scorer ranks only relevant approved memory, the packet builder injects a compact top-k advisory packet, and unrelated memory is excluded.

**Acceptance Scenarios**:

1. **Given** approved routing memory matching a task, **When** worker context is built, **Then** a compact advisory memory packet is included.
2. **Given** archived, proposed, rejected, or low-confidence candidates, **When** retrieval runs, **Then** they are not injected.
3. **Given** a task whose tokens only partially overlap a memory item, **When** retrieval runs, **Then** substring-only false positives are excluded.
4. **Given** a prior mistake from another repo and tenant with the same tool and error signature, **When** a new task has the same task type and tool, **Then** the memory may be retrieved with cross-scope penalty but is labeled advisory and never treated as repo-specific truth.
5. **Given** a deterministic approved memory item such as a known bad command pattern and known working replacement, **When** policy escalation runs, **Then** it creates an audit/advisory policy candidate and requires judge plus operator approval before enforcement.
6. **Given** semantically similar memory from the wrong tenant, repo, machine, or scope, **When** vector retrieval finds it, **Then** hard metadata filters exclude it or downgrade it before packet construction.
7. **Given** approved memory connected to matching tool, task type, and error-signature graph nodes, **When** graph expansion runs, **Then** the graph can add explainable candidates but cannot bypass approval, scope, or evidence gates.

---

### User Story 5 - Compile Memory Wiki And Dreaming Proposals (Priority: P5)

As the Hermes operator, I want stable lessons promoted into a memory wiki and offline dreaming proposals, so repeated work becomes easier without letting speculative ideas control live execution.

**Why this priority**: Wiki and dreaming are high-value but must stay downstream of judged, approved evidence.

**Independent Test**: Promote approved memory into wiki claims, run a manual dreaming cycle, run the sidecar with dreaming due, and verify dreaming creates proposals only, not applied policies.

**Acceptance Scenarios**:

1. **Given** approved durable memory, **When** the wiki compiler runs, **Then** it creates or updates evidence-backed wiki claims.
2. **Given** wiki claims and recent failures, **When** dreaming runs manually or becomes due on the sidecar interval, **Then** it emits proposal records with rationale and risk.
3. **Given** a dreaming proposal, **When** the next session starts, **Then** it is not injected unless separately approved through the judge/operator path.
4. **Given** `supervisor.dreaming.enabled=false`, **When** the sidecar ticks, **Then** dreaming is skipped and the foreground runtime is unaffected.

---

### User Story 6 - Observe Runtime Learning (Priority: P6)

As the Hermes operator, I want tenant-scoped historical and active learning jobs visible by date, repo, task, worker, status, completions, blockers, and system overrides, so I can audit effectiveness and diagnose failures without crossing tenant boundaries.

**Why this priority**: Observability is required to trust the learning loop and evaluate whether it improves future sessions.

**Independent Test**: Run sidecar, judge, wiki, dreaming, and housekeeping jobs; verify JSON CLI and backend endpoints expose tenant/repo-filtered active jobs, historical jobs, line-item drilldown, evidence bundles, metrics, failures, and read-only scoped analysis.

**Acceptance Scenarios**:

1. **Given** active background jobs, **When** status is queried, **Then** each job reports owner, lease, progress, and last heartbeat.
2. **Given** completed jobs, **When** history is queried by date and repo, **Then** results include counts, decisions, failures, and candidate changes.
3. **Given** a blocked task, **When** observability data is requested, **Then** the current blocker and next recovery action are visible.
4. **Given** a tenant and repo filter, **When** the job/task list is queried, **Then** only records in the requested scope are returned unless the operator has explicit cross-tenant permission.
5. **Given** a job or task line item, **When** the operator opens detail, **Then** the response includes the original task description, supervisor packet, initial assignment, active/past agents, Spec Kit refs, architecture/task-list refs, memory packet, validation evidence, sidecar events, and blockers.
6. **Given** an operator asks a question about one task, **When** the scoped analysis endpoint runs, **Then** the LLM receives only a compact read-only evidence bundle for that tenant/repo/task and returns an analytical answer with evidence links; it cannot mutate repo, config, memory, policy, or task state.

---

### User Story 7 - Convergent Supervisor Control Plane (Priority: P7)

As the Hermes operator, I want long-running delegated work to converge through deterministic leases, heartbeats, drift detection, validation gates, and worker reallocation, so a stuck or looping agent cannot degrade the task indefinitely.

**Why this priority**: `/goal` can continue a session, but it is not enough to guarantee convergence. The supervisor needs a durable task ledger and override policy that can reclaim stale work, summarize partial progress, reassign workers, and require validation evidence before completion.

**Independent Test**: Start a delegated task, simulate stale heartbeats, repeated errors, no-progress loops, and failed validation, then verify the supervisor reclaims or reassigns the task with a recovery packet while preserving Spec Kit/git evidence.

**Acceptance Scenarios**:

1. **Given** a worker has a task lease, **When** the heartbeat becomes stale, **Then** the supervisor marks the lease stale, records a recovery packet, and makes the task eligible for reassignment.
2. **Given** the same error signature repeats beyond policy, **When** the loop detector runs, **Then** retries stop, the task is marked blocked or needs replan, and a recovery candidate is emitted.
3. **Given** a worker makes no observable progress across the configured window, **When** the progress evaluator runs, **Then** the supervisor interrupts, requests status, or reallocates according to policy.
4. **Given** validation fails after the retry budget, **When** recovery runs, **Then** the task escalates to a stronger planner/reviewer or alternate worker and preserves the failed validation evidence.
5. **Given** `/goal` is active, **When** the supervisor control plane runs, **Then** `/goal` may enqueue continuation prompts but cannot override task leases, validation gates, Spec Kit state, or reallocation policy.

---

### User Story 8 - Production Runtime Surfaces And Low-End Model Validation (Priority: P8)

As the Hermes operator, I want persisted global lessons, compact task memory, cost metrics, and low-end model evals, so cheaper workers can improve without bloating runtime infrastructure or giving sidecars enforcement authority.

**Why this priority**: The memory architecture only has operational value if it measurably reduces repeated mistakes, token waste, and unnecessary strong-model calls.

**Independent Test**: Run controlled tasks before and after persisted lesson retrieval and compact packet injection; verify fewer repeated errors, bounded token use, and no unauthorized policy/config mutation.

**Acceptance Scenarios**:

1. **Given** an approved global lesson exactly matches a new failure signature, **When** pre-curation runs, **Then** local expensive curation is skipped and a compact advisory packet is produced.
2. **Given** a low-cost worker receives a task packet, **When** relevant memory exists, **Then** only top-k scoped advisory lessons are injected.
3. **Given** the task completes, **When** feedback is recorded, **Then** lesson usefulness and cost/value metrics are updated without copying private local evidence globally.

---

### User Story 9 - Goal-Based Multi-Agent Allocation (Priority: P9)

As the Hermes operator, I want `/goal`-backed workloads to allocate across available workers with health checks, latency budgets, fallback, and resumable state, so one unhealthy worker route cannot trap or degrade the whole task.

**Why this priority**: Upstream `/goal` is useful for continuation, but it does not choose workers, enforce per-turn latency budgets, suppress repeated failed routes, or recover from quota/network/auth failures.

**Independent Test**: Start a `/goal`-backed task with one failing primary worker and healthy fallback workers; verify the allocator records failed attempts, updates worker health, falls back within budget, or pauses with retry-after when no safe worker remains.

**Acceptance Scenarios**:

1. **Given** a primary worker times out, **When** budget remains, **Then** the allocator records the failed attempt, updates worker health, and tries the next ranked fallback.
2. **Given** a worker reports quota, auth, or network degradation, **When** no safe fallback remains, **Then** the allocator pauses the allocation with retry-after instead of foreground sleeping.
3. **Given** `/goal resume` runs after a restart, **When** allocation state exists, **Then** the allocator resumes from `allocation:<session_id>:<task_id>` and skips workers still in cooldown.
4. **Given** the supervisor uses fallback evidence, **When** it answers the operator, **Then** it discloses degraded worker evidence and does not claim the failed worker completed successfully.

### Edge Cases

- Judge provider is unavailable, times out, or returns non-JSON.
- Event bus contains duplicate events or events from older schema versions.
- Candidate evidence references missing memory packets or missing kanban records.
- Background job is killed while holding a lease.
- Retrieved memory conflicts with explicit operator instructions or current git/test evidence.
- Dreaming proposes a risky or destructive change.
- Hot memory grows beyond prompt budget.
- Supervisor receives a vague dashboard request from a non-technical user.
- Planner or Spec Kit creator fails or returns incomplete artifacts.
- Worker starts without a valid worktree, owned file scope, validation command, or return schema.
- User explicitly requests no Spec Kit for a task that would normally require it.
- Worker heartbeat becomes stale while holding a task lease.
- Worker loops on the same command/error signature.
- Worker produces no git/test/progress delta across the configured window.
- `/goal` continues a session after the supervisor has already reclaimed or blocked the task.
- Reassignment sees partial uncommitted work in the worker worktree.
- `/goal resume` finds an active allocation whose primary worker is still in cooldown.
- All configured workers are unhealthy, unauthenticated, over quota, or over latency budget.
- A worker wrapper returns empty output or progress-only logs after a long run.

## Requirements

### Functional Requirements

- **FR-001**: System MUST define a supervisor initialization protocol loaded for non-trivial task invocation.
- **FR-002**: System MUST provide prompt templates for supervisor intake, initialization, memory packet injection, Spec Kit planning, worker delegation, worker result, validation report, and session summary.
- **FR-003**: System MUST require a structured supervisor task packet before planner or worker dispatch.
- **FR-004**: System MUST require Spec Kit artifacts for non-trivial implementation work unless the user explicitly opts out or the task matches a configured trivial-work exception.
- **FR-005**: System MUST record when Spec Kit is skipped and why.
- **FR-006**: System MUST support planner and Spec Kit creator roles, with Codex/GPT-5.5-class reasoning as the preferred planner and configurable fallback providers.
- **FR-007**: System MUST support implementation worker routing across configured workers such as Claude Code Sonnet, Minimax via Claude Code, DeepSeek TUI, Cursor, or Codex, without hardcoding one vendor as the architecture.
- **FR-008**: System MUST validate worker delegation packets before dispatch and reject packets missing repo, branch/worktree, objective, constraints, validation, owned files, memory packet, or return schema.
- **FR-009**: System MUST prevent the supervisor from marking a non-trivial implementation task complete without validation evidence and git/spec preservation status.
- **FR-010**: System MUST provide a learning judge runner with strict structured output validation.
- **FR-011**: System MUST fail closed when judge output is missing, malformed, risky, or unsupported.
- **FR-012**: System MUST record judge decisions separately from curator candidates and approved memory.
- **FR-013**: System MUST keep enforcement disabled unless both judge approval and operator approval are present.
- **FR-014**: System MUST provide a durable local event bus for runtime learning events.
- **FR-015**: System MUST process event bus work asynchronously with leases, retries, and failure states.
- **FR-016**: System MUST keep raw events, curator candidates, judge decisions, approved memory, wiki claims, dreaming proposals, and enforcement policies in separate records or tables.
- **FR-017**: System MUST support hot, warm, and cold memory tiers with explicit promotion and demotion rules.
- **FR-018**: System MUST classify each task invocation into a structured retrieval query that includes tenant, repo, task type, tools, intent, entities, error signatures, success signatures, and scope.
- **FR-019**: System MUST store approved memory with metadata fields sufficient for targeted retrieval, including tenant, repo, tool, task type, error signature, success signature, confidence, tier, scope, source, and verification timestamps.
- **FR-020**: System MUST score memory relevance using exact scope matches, task type, tool, error/success signatures, semantic similarity, confidence, recency, and cross-tenant/repo penalties.
- **FR-021**: System MUST maintain structured metadata indexes, lexical indexes, vector indexes, and graph edges for approved memory without embedding raw secrets, raw logs, or full transcripts.
- **FR-022**: System MUST apply hard metadata filters before vector similarity can affect retrieval ranking.
- **FR-023**: System MUST support lexical search for exact identifiers, commands, files, branches, error signatures, and tool names.
- **FR-024**: System MUST support vector search over compact approved memory summaries, failure patterns, success patterns, task types, tool context, and evidence summaries.
- **FR-025**: System MUST support graph expansion over approved memory relationships such as tenant, repo, machine, tool, worker, provider, model, task type, error signature, success signature, wiki claim, and policy.
- **FR-026**: System MUST rerank retrieval candidates using structured match features, lexical match, vector similarity, graph proximity, confidence, recency, tier, and penalties.
- **FR-027**: System MUST build compact top-k memory packets from scored approved memory and include evidence, scope, confidence, and advisory priority labels.
- **FR-028**: System MUST provide policy escalation for deterministic approved memory, producing audit/advisory/enforcement candidates without enabling enforcement automatically.
- **FR-029**: System MUST record outcome feedback that marks injected memory as helpful, irrelevant, harmful, or unknown and adjusts confidence or tier according to policy.
- **FR-030**: System MUST retrieve learning context using quality gates, evidence requirements, scope filters, and exact or semantic matching rules that avoid substring-only false positives.
- **FR-031**: System MUST label injected learning context as advisory and lower priority than current evidence and explicit instructions.
- **FR-032**: System MUST compile approved durable memory into evidence-backed memory wiki claims.
- **FR-033**: Memory wiki claims MUST carry scope, confidence, evidence references, and safety metadata suitable for future lexical, vector, graph, and training-data pipelines.
- **FR-034**: System MUST keep wiki claims advisory unless they are converted into judge/operator-approved policy candidates.
- **FR-035**: System MUST run dreaming as proposal-only synthesis that can be invoked manually for testing and scheduled by the learning sidecar when `supervisor.dreaming.enabled=true` and its interval is due.
- **FR-036**: Dreaming MUST be disabled by default until validators, judge gating, operator approval, and storage isolation are present.
- **FR-037**: Dreaming proposals MUST NOT be injected into prompts, applied to config, queued as goals, written to the wiki, exported as training data, or enforced directly.
- **FR-038**: Dreaming sidecar execution MUST be asynchronous and bounded by interval, timeout, evidence window, and maximum proposals per run so foreground chat, terminal, and delegation paths never wait on dreaming.
- **FR-039**: Dreaming proposal promotion MUST require judge review and operator approval before conversion into approved memory, wiki claims, training corpus candidates, playbooks, tests, goals, or policy candidates.
- **FR-040**: Training-data exports MUST use curated wiki/approved-memory records rather than raw transcripts or raw logs, and MUST preserve tenant/shareability boundaries.
- **FR-041**: Training-data exports for migration intelligence MUST preserve source repository refs, target repository refs, branch names, before/after commit refs, Spec Kit artifact refs, task/worker/model refs, failure signatures, successful repair signatures, validation evidence refs, redaction status, and approval provenance.
- **FR-042**: System MUST support training dataset families for `repo_migration_plan`, `migration_failure_repair`, `before_after_diff`, `validation_recipe`, `architecture_pattern`, and `policy_playbook`.
- **FR-043**: System MUST require redaction, scope checks, and operator approval before any wiki claim or approved memory is exported as training data.
- **FR-044**: System MUST support drift-evaluation anchors for exported training records, including regression prompts, expected behavior, forbidden bad fixes, and required validation evidence.
- **FR-045**: System MUST expose CLI and backend-compatible JSON status for active jobs, historical jobs, candidates, decisions, and policy audits.
- **FR-046**: System MUST expose housekeeping for stale, noisy, low-quality, duplicate, or invalid candidates without deleting audit history.
- **FR-047**: System MUST document operator approval points, automated promotion points, and forbidden automatic actions.
- **FR-048**: Observability list and detail endpoints MUST support tenant, repo, task, worker, status, date range, blocker, and job type filters.
- **FR-049**: Observability MUST expose line-item detail bundles for jobs/tasks including task description, supervisor packet, initial assignment, planner/Spec Kit refs, worker packets, branch/worktree refs, validation evidence, memory/wiki/dreaming/candidate refs, events, overrides, and summaries.
- **FR-050**: Observability MUST expose a read-only scoped analysis endpoint that builds a compact evidence bundle and optionally queries the repository in read-only mode before calling an LLM.
- **FR-051**: The scoped analysis endpoint MUST be tenant/repo/task-scoped, must not include raw secrets, raw logs, or full transcripts, and MUST NOT mutate repo, config, task state, memory, wiki, dreaming proposals, candidates, or policies.
- **FR-052**: Dashboard UI SHOULD remain lean initially: tenant selector, repo filter, job/task list, detail drawer, lazy-loaded evidence tabs, and an optional Ask tab backed by the read-only analysis endpoint.
- **FR-053**: System MUST maintain a durable supervisor task ledger with task state, active worker, lease expiry, heartbeat, retry budget, validation status, Spec Kit refs, git/worktree refs, memory packet id, and recovery history.
- **FR-054**: System MUST require workers to emit heartbeat/progress events for delegated work and MUST detect stale leases without waiting on the worker process.
- **FR-055**: System MUST detect no-progress loops using repeated command/error signatures, unchanged git/test/progress state, retry count, elapsed time, and repeated invalid worker results.
- **FR-056**: System MUST support supervisor override actions: interrupt, request status, pause, block, reclaim lease, summarize partial work, reassign worker, escalate planner/reviewer, and abandon with evidence.
- **FR-057**: System MUST produce a recovery packet before reassignment that includes objective, original packet refs, worker history, partial diff/log summary, failed commands, validation failures, memory used, and next recommended action.
- **FR-058**: System MUST keep `/goal` as an optional continuation controller only; `/goal` MUST NOT override task leases, validation gates, worker ownership, Spec Kit preservation, or supervisor reallocation policy.
- **FR-059**: System MUST prevent task completion after reclaim/reassignment unless final validation evidence, git/spec preservation, and session summary are present.
- **FR-060**: System MUST add goal-based multi-agent allocation as a separate control-plane phase that reuses upstream `/goal` state instead of creating another autonomous loop.
- **FR-061**: System MUST persist `WorkerAllocationPlan`, `WorkerAttemptResult`, and `WorkerHealth` state beside goal state using `allocation:<session_id>:<task_id>` and `worker_health:<worker_id>` keys.
- **FR-062**: System MUST enforce total latency budget, per-worker timeout, retry budget, repeated-route suppression, and cooldown/retry-after decisions before each worker attempt.
- **FR-063**: System MUST pause or schedule recovery rather than foreground sleep-loop when quota, network, auth, timeout, or repeated empty-output failures exhaust the allocation budget.
- **FR-064**: System MUST expose allocator status through CLI/API-compatible JSON including active allocation, goal linkage, attempts, worker health, cooldowns, consumed latency budget, fallback reason, and next recovery action.

### Key Entities

- **Runtime Event**: Durable record of a foreground or sidecar signal such as tool result, task outcome, policy audit, or candidate proposal.
- **Learning Candidate**: Curator-generated proposed lesson with evidence, score, kind, scope, and status.
- **Judge Decision**: Structured approval, rejection, or needs-human decision for a candidate or policy proposal.
- **Approved Memory**: Candidate promoted for retrieval after passing quality, judge, and operator gates.
- **Memory Wiki Claim**: Curated durable knowledge derived from approved memory with scope, evidence, confidence, safety metadata, and indexing/training suitability.
- **Dreaming Proposal**: Offline suggestion for playbooks, routing, tests, cleanup, architecture, or policies that cannot affect runtime until approved.
- **Policy Audit**: Non-enforcing evaluation that records what a policy would have done.
- **Memory Tier**: Hot, warm, or cold storage classification that controls retrieval latency, prompt budget, and summarization.
- **Learning Job**: Background execution record for sidecar, judge, wiki, dreaming, housekeeping, or reconcile work.
- **Task Retrieval Query**: Structured representation of a task invocation used to find relevant approved memory.
- **Memory Packet**: Compact prompt-ready advisory context built from top-ranked approved memory.
- **Outcome Feedback**: Post-task record describing whether injected memory helped, was irrelevant, was harmful, or had unknown impact.
- **Memory Index Document**: Redacted compact text and metadata used for lexical and vector search.
- **Memory Graph Node**: Typed node representing tenant, repo, machine, tool, worker, provider, model, task type, signature, memory, wiki claim, proposal, or policy.
- **Memory Graph Edge**: Typed relationship explaining where memory applies, what it avoids, what it recommends, and what evidence produced it.
- **Training Corpus Record**: Sanitized, scoped, evidence-backed export derived from wiki claims or approved memory, never raw transcripts. For migration work, it preserves source/target repo refs, before/after commit refs, Spec Kit refs, failure/repair labels, validation evidence, and drift-evaluation anchors.
- **Retrieval Run**: Audit record for a retrieval request, including filters, lexical/vector/graph candidates, rerank scores, and packet output.
- **Supervisor Task Packet**: Structured intake record for a user or dashboard request before planning or delegation.
- **Planner Packet**: Bounded request sent to the planner agent to create or update Spec Kit artifacts.
- **Spec Kit Artifact Set**: Branch/worktree plus `spec.md`, `plan.md`, `tasks.md`, and related design docs.
- **Worker Delegation Packet**: Bounded execution request sent to an implementation worker.
- **Worker Result**: Structured response from an implementation worker with changes, commands, validation, blockers, and memory notes.
- **Validation Report**: Supervisor-owned evidence that the work matches Spec Kit tasks, tests/logs, git diff, and user success criteria.
- **Session Summary**: Durable summary of master instructions, decisions, delegation, validation, and memory outcome.
- **Worktree Assignment**: Mapping between branch/worktree, agent, owned files, task scope, and cleanup state.
- **Observability Line Item**: Tenant-scoped list row for a job/task with repo, status, worker, blocker, updated time, and completion/validation state.
- **Observability Evidence Bundle**: Compact read-only detail packet for a job/task containing task metadata, packets, Spec Kit refs, events, validation, memory refs, and artifact pointers.
- **Scoped Analysis Request**: Tenant/repo/task-scoped read-only LLM question over an evidence bundle and optional read-only repo query.
- **Supervisor Task Ledger Entry**: Durable state record for task progress, lease, heartbeat, worker ownership, retry budget, validation, recovery, and reassignment.
- **Worker Heartbeat**: Lightweight progress signal emitted by a worker or wrapper with timestamp, current action, progress markers, command/error signature, and optional git/test delta.
- **Recovery Packet**: Reassignment-ready summary of original task, partial work, worker history, failed validation, blockers, and next recommended action.
- **Supervisor Override Action**: Audited action that interrupts, pauses, blocks, reclaims, reassigns, escalates, or abandons task work.
- **Worker Allocation Plan**: Durable control-plane record describing candidate workers, ranked fallback order, memory packet, validation requirement, total latency budget, per-worker timeout, retry limits, cooldown policy, and goal/session linkage.
- **Worker Attempt Result**: Structured attempt outcome containing worker, route, status, duration, output excerpts, artifact refs, error signature, validation status, fallback eligibility, and recovery hint.
- **Worker Health Record**: Durable per-worker status containing success/failure timestamps, timeout/empty/quota/network counters, cooldown timestamps, last error signature, and confidence.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Judge runner approves or rejects a controlled candidate set with 100% deterministic status transitions in tests.
- **SC-002**: Foreground terminal/chat/delegation paths do not wait for event bus consumers, curator, judge, wiki, dreaming, or housekeeping work.
- **SC-003**: Retrieval injects only approved/applied, evidence-backed, scope-matching memory in focused tests.
- **SC-004**: Sidecar and job status commands return machine-readable JSON for active and historical work.
- **SC-005**: No enforcement policy can actively rewrite a command unless a test fixture includes both judge approval and operator approval.
- **SC-006**: No raw secrets or raw transcripts are stored in approved memory, wiki claims, or dreaming proposals in safety tests.
- **SC-007**: Housekeeping can reduce noisy active candidate lists without deleting archived audit history.
- **SC-008**: Non-trivial implementation tasks produce Spec Kit artifacts and a git branch/worktree record before worker execution in protocol tests.
- **SC-009**: Worker dispatch is rejected in tests when required delegation packet fields are missing.
- **SC-010**: Supervisor completion is rejected in tests when validation evidence, git preservation, or session summary is missing.
- **SC-011**: Vector retrieval cannot inject semantically similar memory that fails hard scope, status, evidence, or approval filters.
- **SC-012**: Retrieval run audits explain why each injected memory item was selected, including metadata, lexical/vector/graph, and rerank contributions.
- **SC-013**: Tenant/repo filters prevent observability list, detail, and analysis endpoints from returning out-of-scope records in tests.
- **SC-014**: Line-item detail bundles include task description, agents, initial assignment, Spec Kit refs, validation, memory refs, events, and blockers without raw transcripts.
- **SC-015**: Scoped analysis answers cite evidence refs and cannot mutate repo, config, task state, memory, wiki, candidates, proposals, or policy.
- **SC-016**: Stale worker leases are reclaimed deterministically in tests without losing Spec Kit/git/task history.
- **SC-017**: Repeated error/no-progress loops trigger recovery or reassignment before exhausting the task indefinitely.
- **SC-018**: `/goal` continuation cannot mark reclaimed, blocked, or validation-failed work as complete.
- **SC-019**: Goal-based allocation tests prove quota exhaustion, auth failure, network degradation, timeout, empty worker output, and repeated-route failures either choose a ranked fallback or pause with retry-after before the foreground turn exceeds budget.
- **SC-020**: `/goal resume` can recover persisted allocation state and worker health without repeating an unhealthy route before its cooldown expires.

## Assumptions

- SQLite `state.db` remains the first durable event bus implementation.
- Redis Streams or Kafka are future options only after local SQLite bus limits are proven.
- Codex can be the initial learning judge provider; Qwen or Cerebras-backed models can be configured later.
- Existing Hermes CLI and dashboard/backend patterns should be reused instead of introducing a separate service.
- Existing learning sidecar, curator policy runner, housekeeping, retrieval, and policy audit code remain the base implementation.
- Operator approval means explicit user or admin action through CLI/API/config, not implicit model confidence.
- Non-trivial implementation work defaults to Spec Kit preservation; trivial fixes and explicit user opt-out are recorded as exceptions.
- SQLite metadata and FTS5 are the first retrieval index layer; vector and graph backends must be optional/configurable and can start with SQLite-backed implementations.
