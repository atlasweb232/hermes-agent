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

---

### User Story 10 - Self-Healing Workflow Control Plane (Priority: P10)

As the Hermes operator, I want long-running work to run as a supervisor-owned task graph with background health monitoring and restart recovery, so parallel agent work can survive drift, loops, outages, and process restarts without blocking the active workload.

**Why this priority**: The allocator prevents a single worker route from trapping one turn, but production workflows also need durable parallel task ownership, background degradation monitoring, and safe recovery after VM/service restarts.

**Independent Test**: Create a task graph with multiple subtasks, assign work through the allocator, simulate a stale worker lease, no-progress loop, network outage, and process restart, then verify the health sidecar emits bounded recovery actions and restart recovery resumes only safe work.

**Acceptance Scenarios**:

1. **Given** independent subtasks, **When** the graph runs, **Then** the supervisor dispatches only ready nodes within concurrency and owned-path constraints.
2. **Given** a worker stops heartbeating, **When** the health sidecar runs, **Then** it marks the lease stale, updates worker health, emits a recovery packet, and leaves foreground chat unaffected.
3. **Given** repeated no-progress or timeout signals, **When** the health sidecar evaluates the task, **Then** it blocks, pauses, or requests reassignment without marking the task complete.
4. **Given** Hermes restarts, **When** recovery runs, **Then** active goals, task graphs, allocations, worker health, hot memory, and safe-to-resume tasks are reloaded without retrying unhealthy workers.

---

### User Story 11 - Production Evaluation Harness (Priority: P11)

As the Hermes operator, I want an isolated upstream-vs-branch benchmark harness with cost, latency, memory, sidecar, judge, and quality telemetry, so production rollout is based on concrete evidence over long-horizon workloads.

**Why this priority**: The platform must prove that memory wrapping, sidecars, judges, allocator fallback, and QA agents improve task quality without increasing context bloat, cost, drift, or operational risk.

**Independent Test**: Run the same workload suite against upstream Hermes and `132-learning-memory-runtime`, then compare task success, validation pass rate, false completions, repeated errors, latency, token/cost usage, sidecar overhead, memory usefulness, Slack urgent alerts, and operator interventions.

**Acceptance Scenarios**:

1. **Given** a workload pack and two isolated Hermes homes, **When** the harness runs, **Then** upstream and branch execute the same tasks against the same repo snapshots with separate artifacts and telemetry.
2. **Given** the branch environment completes tasks, **When** telemetry is collected, **Then** model/provider/task/session token usage, estimated cost, latency, context admitted, raw bytes stored, sidecar runs, judge decisions, memory hits, and validation results are recorded.
3. **Given** a blocked/degraded/fallback-exhausted task, **When** the harness evaluates notifications, **Then** urgent Slack delivery is recorded and missing alerts fail the benchmark.
4. **Given** a self-learning candidate is produced, **When** the benchmark checks memory state, **Then** candidates, judge decisions, approved memory, wiki claims, dreaming proposals, and policies remain separated.
5. **Given** branch quality or cost is worse than upstream beyond threshold, **When** the production gate runs, **Then** rollout is blocked with a concrete comparison report.

---

### User Story 12 - End-to-End Feature Testing and Feature Toggles (Priority: P12)

As the Hermes operator, I want a feature-by-feature end-to-end test matrix with runtime toggles, so each platform capability can be validated, isolated, disabled, and compared before the full system is enabled.

**Why this priority**: The platform now has multiple interacting subsystems. Operators need to prove each subsystem adds value without dragging foreground work, increasing context bloat, or hiding failures.

**Independent Test**: Run `hermes runtime e2e run --suite feature-matrix --json` with selected feature toggles enabled and disabled. Verify each feature has pass/fail evidence, expected side effects, telemetry, and safe fallback behavior when disabled.

**Acceptance Scenarios**:

1. **Given** all optional features are disabled, **When** a baseline chat/delegation task runs, **Then** Hermes still responds and records that memory, sidecars, allocator fallback, dreaming, wiki, urgent notifications, and enforcement were skipped by toggle.
2. **Given** runtime failure capture is enabled but curator/judge/advisory retrieval are disabled, **When** a worker fails or returns empty output, **Then** only the raw structured failure record is created and no memory packet is injected.
3. **Given** curator and judge are enabled but enforcement is disabled, **When** a runtime failure candidate is approved, **Then** the candidate becomes advisory-only memory and cannot rewrite commands or block dispatch.
4. **Given** allocator fallback is enabled with a latency budget, **When** the primary worker times out, **Then** Hermes records the failure, respects cooldown, attempts the next eligible worker, or pauses with recovery instructions instead of looping.
5. **Given** goal continuation is enabled, **When** Hermes restarts during an active goal, **Then** `/goal resume` reloads safe state and does not retry unhealthy workers.
6. **Given** context gate and progress summarizer are enabled, **When** a worker emits large streams, **Then** raw streams remain store-only and the supervisor receives only bounded typed packets.
7. **Given** memory wiki, dreaming, global memory, urgent notifications, telemetry, and dashboard observability are enabled, **When** the E2E suite runs, **Then** each feature produces separate artifacts and no proposal, wiki claim, or telemetry item becomes enforcement without approval.

---

### User Story 13 - Tenant Platform Onboarding and Scaling (Priority: P13)

As a platform operator, I want tenants to onboard repositories, communication channels, toolsets, budgets, and isolated runtime cells, so Hermes can run enterprise and power-user workloads safely at scale.

**Why this priority**: Scaling the platform requires tenancy boundaries, repo onboarding, communication adapters, cost controls, and runtime isolation before multiple organizations can safely assign production jobs.

**Independent Test**: Create a tenant, connect a repo, register Slack/Telegram/WhatsApp-style communication bindings, assign a toolset profile, provision an isolated runtime cell, submit a Spec Kit-backed job, and verify tenant-scoped observability, cost, memory, and fault records without cross-tenant leakage.

**Acceptance Scenarios**:

1. **Given** a new tenant, **When** onboarding completes, **Then** the tenant has users/roles, repo registrations, communication bindings, toolset profile, budget policy, feature profile, and runtime cell assignment.
2. **Given** a tenant connects a repository, **When** the repo preflight runs, **Then** Hermes records clone refs, branch policy, protected paths, validation commands, secrets references, Spec Kit policy, and memory sharing policy before write-capable work is allowed.
3. **Given** a tenant submits work from Slack, Telegram, WhatsApp, dashboard, or API, **When** the adapter receives it, **Then** the request becomes a tenant-scoped supervisor task packet with reply routing and approval routing.
4. **Given** enterprise isolation mode, **When** a job starts, **Then** Hermes runs in a dedicated runtime cell with separate home/state/worktree/secrets/memory/cost ledger.
5. **Given** pooled mode, **When** a job starts, **Then** tenant boundaries still apply to state rows, worktree roots, secret namespaces, memory retrieval, communication routes, and cost telemetry.
6. **Given** global admin opens the dashboard, **When** tenant jobs are active or blocked, **Then** admin can see tenant activity, faults, cost, worker health, sidecar health, memory flow, and urgent alerts without exposing tenant secrets or unauthorized raw data.
7. **Given** a tenant enables the CI/CD toolset, **When** a user asks Hermes to create or repair a deployment pipeline, **Then** Hermes uses Spec Kit, references secrets safely, respects protected environments, emits validation evidence, and routes approval requests through the tenant connector.

---

### User Story 14 - Skill And Memory Pipeline (Priority: P14)

As the Hermes operator, I want skills to be retrieved, injected, validated, evolved, and scoped through the same memory and tenant safety model, so reusable procedures improve agents without becoming unsafe hidden policy.

**Why this priority**: Skills are how repeated work becomes procedural competence, but they must be evidence-backed, tenant-scoped, versioned, and bounded like memory packets.

**Independent Test**: Run a task whose classifier matches a tenant-approved CI/CD or TinyFish QA skill. Verify only relevant skill summaries are injected, the worker receives role-specific skill refs, validation evidence records whether the skill helped, and harmful/irrelevant skill use creates feedback without cross-tenant leakage.

**Acceptance Scenarios**:

1. **Given** a tenant has a private skill for CI/CD workflow creation, **When** a matching job starts, **Then** the supervisor receives a bounded skill packet and the CI/CD worker receives the role-specific skill reference.
2. **Given** skill injection is disabled, **When** the same job starts, **Then** no skill packet is injected and a skipped-by-toggle audit event is recorded.
3. **Given** approved memory or wiki evidence identifies a recurring workflow, **When** the skill compiler runs, **Then** it creates a skill candidate but does not publish it until validation and approval pass.
4. **Given** a skill causes drift, invalid commands, or failed validation, **When** outcome feedback runs, **Then** Hermes records harmful feedback and creates a demotion or repair candidate for that skill version.
5. **Given** a global skill exists, **When** another tenant runs a similar task, **Then** the skill is retrieved only if redaction, shareability, tenant opt-in, safety, and relevance gates pass.

---

### User Story 19 - Operator Dashboard And Approval UI (Priority: P19)

As a Hermes operator or tenant admin, I want a lean dashboard that exposes jobs, worker activity, sidecars, memory, approvals, costs, and deployments, so I can operate the platform without reading raw logs or bloating supervisor context.

**Why this priority**: The backend now has observability, approval, tenant, memory, sidecar, bus, benchmark, and Azure deployment surfaces. Operators need a bounded UI that consumes those surfaces, makes decisions auditable, and prevents Slack/chat transcripts from becoming the only control plane.

**Independent Test**: Run a seeded dashboard fixture with tenants, jobs, worker attempts, sidecar events, approvals, memory packets, corpus exports, and Azure deployment records. Verify list/detail/filter/approval/scoped-Ask flows return redacted bounded DTOs, perform no mutation without approval, and do not load raw transcripts into model context.

**Acceptance Scenarios**:

1. **Given** multiple tenants have active and historical jobs, **When** the operator opens the dashboard, **Then** the jobs table supports tenant, repo, date, status, worker, model, blocker, cost, and deployment filters.
2. **Given** an operator opens a job line item, **When** the detail drawer loads, **Then** it shows task packet, Spec Kit refs, worker attempts, sidecar activity, memory packet, validation evidence, artifacts, blocker reason, and completion state using bounded DTOs only.
3. **Given** approvals are pending, **When** the approval inbox loads, **Then** memory promotion, dreaming conversion, corpus export, deployment apply/promote/destroy, and protected CI/CD actions are grouped by tenant, risk, expiry, target hash, and evidence refs.
4. **Given** an operator approves or rejects an item, **When** the UI submits the action, **Then** it writes through the shared approval ledger and cannot replay, escalate scope, or mutate unrelated targets.
5. **Given** sidecars are running, **When** the sidecar panel loads, **Then** it shows role, tier, model, budget state, queue/backlog, last run, failure state, and disabled/degraded reason without exposing secrets.
6. **Given** the operator asks a scoped question about a job, **When** dashboard Ask runs, **Then** the LLM receives only the read-only compact evidence bundle for that job and cannot mutate repo, memory, policy, deployment, or config.
7. **Given** Azure deployment orchestration is enabled, **When** the deployment panel loads, **Then** it shows plan/preflight/apply/smoke/soak/promote/rollback state, hardening failures, costs, and required operator actions.
8. **Given** runtime telemetry exists, **When** the cost panel loads, **Then** it shows token, model, latency, sidecar, worker, memory-hit, and budget attribution by tenant/repo/job without raw transcript storage.

---

### User Story 20 - Production Runtime Closure (Priority: P20)

As the Hermes operator, I want the VM-proven runtime-learning loop to be production-grade before rollout, so Claude/Codex workers, goal judge, curator, learning judge, sidecars, skills, memory injection, Slack alerts, and cost/context telemetry operate deterministically without secret leakage or foreground drag.

**Why this priority**: Live VM smoke showed the framework exists, but production blockers remain: Codex was not on the service path, goal judge returned `auxiliary client unavailable`, curator depended on dead Ollama until reconfigured, sidecars were not proven as services, runtime failure evidence was too sparse, skill evolution was not proven E2E, and one capture path persisted secret-bearing command text before manual redaction.

**Independent Test**: Run `hermes runtime production-smoke --json` in a service-equivalent VM environment. Verify Claude primary and Codex fallback/judge paths, goal judge model invocation, curator and learning judge, secret-safe runtime capture, sidecar one-shot service mode, failure-to-advisory-to-next-task memory injection, skill evolution, Slack/dashboard alerts, and cost/context telemetry.

**Acceptance Scenarios**:

1. **Given** a worker emits a long update stream, repeated status report, raw command output, sidecar log, or Slack mirror, **When** the supervisor prepares context, **Then** the context admission gate stores the raw content outside model context and injects only a bounded checkpoint plus evidence refs.
1. **Given** a command or worker attempt contains provider-shaped secrets, **When** runtime learning captures the failure, **Then** all persisted memory, evidence, bus, candidate, Slack, dashboard, and corpus outputs contain only redacted values.
2. **Given** Codex is installed under a user npm prefix, **When** Hermes runs from SSH non-login shell, gateway service, sidecar, or CLI, **Then** the model-role doctor resolves the same executable/provider state without relying on interactive shell profile side effects.
3. **Given** a supervisor task has a goal and `goal_judge` is enabled, **When** `hermes runtime control goal` evaluates a worker response, **Then** the configured model role is invoked or a structured degraded result is returned without pretending a model-backed judgment occurred.
4. **Given** curator and learning judge are enabled, **When** runtime-failure records exist, **Then** curator creates advisory candidates and learning judge approves, rejects, or marks needs-human fail-closed based on bounded evidence quality.
5. **Given** a runtime failure is captured, **When** the record is stored, **Then** it includes tenant/repo/task/worker/route/status/latency/evidence-ref metadata where available so curator and judge are not forced into sparse-evidence decisions.
6. **Given** a repeated failure implies a reusable procedure, **When** the skill evolution loop runs, **Then** a skill candidate can be created, judged, operator-approved, retrieved as a bounded skill packet, and updated by outcome feedback.
7. **Given** sidecars are configured for production, **When** their service-equivalent smoke runs, **Then** each sidecar reports lock, budget, interval, last run, degraded reason, backlog, and foreground-nonblocking status.
8. **Given** a live primary worker failure and healthy fallback, **When** the production learning-loop smoke runs, **Then** Hermes records the failure, falls back or pauses under budget, creates advisory learning, and injects only scoped approved guidance on a follow-up task.
9. **Given** sidecars, memory retrieval, curator, judge, and notifications run during a task, **When** the operator opens runtime impact UI, **Then** sidecars are grouped by category and job, memory activity is shown by job, and foreground latency is separated from asynchronous sidecar latency.

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
- A feature is disabled after prior state exists and must not leak stale state into runtime.
- A feature is enabled without required provider credentials and must fail closed without blocking baseline chat/delegation.
- Two enabled features conflict on one runtime path and the lower-risk advisory behavior must win.
- A test suite asks for enforcement while judge or operator approval is missing.
- A tenant communication channel receives a message from an unauthorized user or wrong channel.
- A repo onboarding preflight finds missing credentials, protected branch policy, or no Spec Kit path.
- A pooled runtime cell accidentally sees another tenant's memory, worktree, channel, or cost ledger.
- A tenant exceeds token, model, tool, or sidecar budget during a job.
- A global memory candidate is useful across tenants but lacks explicit shareability approval.
- A connector credential is valid but the bot lacks access to the configured channel.
- A CI/CD provider is connected but protected environment approval blocks deployment.
- A user asks to speak directly to a worker and expert mode is disabled.
- A skill exists for the same task type but wrong tenant, repo, toolset, worker role, or safety status.
- A skill version was helpful historically but conflicts with current repo evidence or operator instruction.
- SkillClaw proposes a skill from raw session data without approved memory/wiki provenance.
- A model role works in an interactive shell but fails under systemd, SSH non-login shell, or sidecar execution because PATH or trust state differs.
- Goal judge returns a fallback continuation because the auxiliary client is unavailable; this must be reported as degraded and must not count as model-backed judgment.
- A command captures `.env` creation or provider configuration; secrets must be scrubbed before persistence.
- Curator creates candidates from sparse runtime failure records; judge must reject or require human review unless evidence is sufficient.
- Sidecar backlog grows while foreground work is active; sidecars must throttle, defer, or fail closed without blocking chat/delegation.

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
- **FR-065**: System MUST maintain a supervisor-owned task graph for parallel subtasks, dependencies, ownership, concurrency limits, allocation refs, validation refs, and completion state.
- **FR-066**: System MUST prevent parallel workers from writing overlapping owned paths unless the supervisor explicitly marks the overlap safe.
- **FR-067**: System MUST run a health sidecar out of band to detect stale leases, missing heartbeats, no-progress loops, repeated failures, and worker degradation without blocking foreground chat, tool execution, or delegation.
- **FR-068**: Health sidecar actions MUST be bounded to worker health updates, recovery packet emission, task/lease state updates, allocation pause/retry-after, and learning events; it MUST NOT edit code, complete tasks, approve memory, or enforce policy.
- **FR-069**: System MUST provide restart recovery that loads active goals, supervisor task ledger, task graphs, allocations, worker health, sidecar leases, hot memory, and approved lessons before resuming work.
- **FR-070**: Restart recovery MUST resume only safe ready work, skip cooled-down workers, avoid expensive LLM sidecars by default, and expose recovery status through CLI/API JSON.
- **FR-071**: System MUST keep raw worker streams, stdout/stderr bodies, unbounded terminal transcripts, and log tails as store-only artifacts; they MUST NOT be appended directly to supervisor model context.
- **FR-072**: Worker runtime wrappers MUST emit mandatory typed progress events independent of worker model cooperation, including start, heartbeat, stream reference, checkpoint, degraded/blocked, validation, and final-result events.
- **FR-073**: System MUST provide a supervisor context gate that admits only bounded typed packets at decision boundaries, such as worker checkpoints, blocked/degraded packets, validation packets, allocation decisions, recovery packets, and final worker results.
- **FR-074**: System MUST support a non-blocking cheap progress summarizer sidecar configured through the low-cost reasoning tier; it may summarize progress for UI/Slack/supervisor checkpoints but MUST NOT complete tasks, approve memory, or enforce policy.
- **FR-075**: System MUST provide an isolated upstream-vs-branch benchmark harness with separate Hermes homes, shared workload definitions, shared repo snapshots, and comparable model/tool configurations.
- **FR-076**: System MUST record realtime token, cost, latency, context, worker, sidecar, judge, memory, validation, notification, and operator-intervention telemetry per task/session/model/path.
- **FR-077**: System MUST attribute telemetry to runtime paths including supervisor, planner, worker, judge, curator, dreaming, progress summarizer, QA/test worker, deployment worker, Slack/dashboard analysis, and memory retrieval.
- **FR-078**: System MUST support benchmark workload packs for branch review, implementation, QA validation, deployment, long-running goals, fallback, stale worker, repeated failure, multi-repo decomposition, and hallucinated completion cases.
- **FR-079**: System MUST produce an upstream-vs-branch comparison report with quality, latency, cost, context growth, repeated-error, false-completion, memory-usefulness, sidecar-overhead, and urgent-alert metrics.
- **FR-080**: System MUST block production-readiness status unless benchmark gates pass under configured thresholds and memory/judge/operator boundaries remain intact.
- **FR-081**: System MUST expose runtime feature toggles for memory retrieval, global memory, runtime failure capture, runtime failure advisories, allocator fallback, goal continuation, health sidecar, context gate, progress summarizer, learning sidecar, curator, learning judge, memory wiki, dreaming, urgent notifications, telemetry, benchmark harness, and enforcement.
- **FR-082**: Feature toggles MUST be visible through CLI/API-compatible JSON with configured value, effective value, source, default, risk level, dependencies, and last change metadata.
- **FR-083**: Risky features MUST default to safe advisory/off behavior, and enforcement MUST default to disabled.
- **FR-084**: Disabling a feature MUST prevent its runtime behavior while preserving audit history and baseline chat/delegation functionality.
- **FR-085**: System MUST provide an E2E feature test matrix where every feature toggle has at least one enabled test, one disabled test, expected artifacts, expected telemetry, and pass/fail criteria.
- **FR-086**: E2E tests MUST support selective execution by feature, suite, tenant, repo, workload, and risk profile.
- **FR-087**: E2E test results MUST record feature states, runtime path, worker/model/provider, latency budget, token/cost estimates, memory injected/skipped, sidecars run/skipped, notifications, validation evidence, and final status.
- **FR-088**: E2E tests MUST prove that raw events, curator candidates, judge decisions, approved memory, wiki claims, dreaming proposals, telemetry, and enforcement policies remain separate.
- **FR-089**: E2E tests MUST include a workload fixture for the Azure desktop chat/voice port so platform behavior can be validated against a real production-style task.
- **FR-090**: E2E test reports MUST identify whether failures are product defects, environment/auth issues, provider quota/network issues, missing feature implementation, or expected toggle-disabled behavior.
- **FR-091**: System MUST provide a tenant registry with tenant status, isolation mode, users/roles, budgets, feature profile, runtime cell assignment, and audit metadata.
- **FR-092**: System MUST provide repository onboarding records with provider, clone refs, branch policy, protected paths, validation commands, deployment mapping, secret references, Spec Kit policy, and memory sharing policy.
- **FR-093**: System MUST provide communication connector registrations for Slack, Telegram, WhatsApp, dashboard, API, and future adapters with tenant/user/channel allowlists and urgent/approval routes.
- **FR-094**: System MUST provide toolset profiles that control planner, Spec Kit creator, code workers, QA/browser tools, TinyFish API/browser agents, deployment tools, cloud tools, repo tools, voice/image tools, credentials, scopes, budgets, and approvals.
- **FR-095**: System MUST support tenant runtime cells with isolated Hermes home/state/worktree/secrets/memory/cost ledger and optional dedicated container/volume deployment.
- **FR-096**: System MUST support pooled runtime mode only when tenant IDs, worktrees, secrets, communication routes, memory retrieval, and cost ledgers remain isolated.
- **FR-097**: Tenant-submitted jobs MUST become supervisor task packets with tenant, repo, requester, objective, constraints, toolset profile, model budget, validation policy, approval policy, reply route, and memory policy.
- **FR-098**: Admin observability MUST expose tenant activity, faults, worker health, sidecar health, communication connector state, cost, token/context usage, memory flow, judge decisions, policy audits, and deployment status.
- **FR-099**: System MUST keep tenant-private memory private and allow global/cross-tenant memory only after redaction, judge/operator approval, shareability metadata, and sensitivity gates.
- **FR-100**: Tenant onboarding MUST include a smoke test proving repo access, communication reply route, toolset availability, budget policy, feature profile, runtime cell isolation, and baseline job execution.
- **FR-101**: Communication connectors MUST normalize Slack, Telegram, WhatsApp, dashboard/API, email, and webhook messages into tenant-scoped task/message envelopes with authenticated user, channel/thread, permissions, reply route, and approval route.
- **FR-102**: System MUST keep direct worker chat disabled by default; optional expert mode MUST remain tenant-scoped, audited, and unable to bypass supervisor validation, repo ownership, secret policy, memory policy, or approval gates.
- **FR-103**: System MUST provide CI/CD toolset support for creating, inspecting, repairing, running, and validating pipelines across supported providers such as GitHub Actions, GitLab CI, Azure DevOps Pipelines, Jenkins, Buildkite, and cloud-native deployment pipelines.
- **FR-104**: CI/CD automation MUST use secret references, protected environment policy, approval gates, validation evidence, rollback expectations, and urgent failure notifications.
- **FR-105**: System MUST maintain skill metadata with skill id, name, version, scope, tenant/repo/toolset/worker/task metadata, approval state, safety state, content hash, source memory/wiki refs, validation refs, usage stats, and retirement state.
- **FR-106**: System MUST retrieve skills using task classifier metadata and hard filters for tenant visibility, repo visibility, tool compatibility, worker role, approval state, safety state, and feature toggles before semantic ranking.
- **FR-107**: System MUST inject only bounded skill packets into supervisor/planner/worker context, including skill id, version, scope, summary, match reason, confidence, and validation hooks.
- **FR-108**: Skills MUST remain advisory execution aids and MUST NOT override user instructions, tenant policy, repo protection, current evidence, validation gates, memory policy, or approval requirements.
- **FR-109**: System MUST record skill outcome feedback as helpful, irrelevant, harmful, or unknown per task/session/skill version and use it for confidence, demotion, repair, or retirement.
- **FR-110**: Skill candidates derived from memory/wiki evidence MUST require validation and approval before publishing to tenant or global skill libraries.
- **FR-111**: SkillClaw integration MUST be optional and adapter-based, supporting local, tenant, and global/shared modes without making raw session data the source of truth for published skills.
- **FR-112**: Dreaming MUST support separate local and global roles, where local dreaming remains tenant/repo scoped and global dreaming consumes only redacted approved shareable global memory/wiki evidence.
- **FR-113**: Dreaming MAY propose skill candidates, skill repairs, CI/CD hardening tasks, test gaps, observability gaps, routing improvements, toolset recommendations, cost optimizations, training corpus candidates, and architecture review items, but MUST NOT apply them directly.
- **FR-114**: Dreaming proposals MUST include proposal type, scope, evidence refs, risk level, expected benefit, affected feature ids, approval path, forbidden direct actions, and suggested validation.
- **FR-115**: Dreaming proposal conversion MUST route through deterministic validation, judge review, and operator or tenant-admin approval before becoming approved memory, wiki update, skill candidate, test task, policy candidate, goal, or training corpus candidate.
- **FR-116**: Dashboard/API observability MUST expose dreaming proposals by tenant, repo, proposal type, risk, status, evidence refs, expected benefit, judge decision, and operator action history.
- **FR-117**: System MUST support a separate corpus remittance loop for lesser-model failure/repair records, distinct from runtime memory and prompt retrieval, for consumption by external MLOps infrastructure.
- **FR-118**: Training corpus records for lesser-model improvement MUST include task packet summary, lesser-model attempt summary, failure classification, failure evidence refs, teacher/strong-model diagnosis, corrected output refs, validation evidence, distilled lesson, forbidden future behavior, redaction state, and approval provenance.
- **FR-119**: System MUST support SFT message records and preference-pair records for validated failure/repair examples.
- **FR-120**: Training corpus storage MUST support local JSONL/manifests first and Delta Lake or Iceberg-compatible production destination layouts later.
- **FR-121**: Hermes MUST emit external training hints with target base model family, recommended training method, corpus refs, eval refs, approval refs, and destination metadata, but MUST NOT schedule fine-tuning jobs.
- **FR-122**: Hermes MUST record immutable remittance receipts for exported bundles, including destination URI, bundle hash, schema version, approval refs, external pipeline id when available, submitted_at, and audit status.
- **FR-123**: Fine-tuning, model registry, model evaluation gates, serving, and rollout decisions MUST be owned by external MLOps infrastructure, not by Hermes runtime or sidecars.
- **FR-124**: Runtime sidecars MAY create training candidates and approved corpus bundles but MUST NOT train, register, deploy, route to, or promote fine-tuned models directly.
- **FR-125**: System MUST support Azure production deployment planning for Hermes platform infrastructure through a gated plan/preflight/apply/status/rollback workflow.
- **FR-126**: Azure deployment planning MUST include runtime cells, sidecars, event bus backend, object storage, state store, secrets, observability, communication connectors, network/DNS, IaC artifacts, quota, and cost estimate checks.
- **FR-127**: Hermes chat MAY orchestrate Azure deployment workflows, but MUST require explicit operator approval before creating paid resources, changing DNS, rotating secrets, enabling production traffic, deleting infrastructure, or promoting staging to production.
- **FR-128**: Azure deployment helpers MUST keep SQLite as the default local spool/fallback and MUST NOT block foreground runtime when Azure Event Hubs, Kafka, Redpanda, storage, or sidecar infrastructure is unavailable.
- **FR-129**: Azure production deployment MUST support staging first, production promotion only after smoke/soak gates pass, and rollback to the prior known-good deployment profile.
- **FR-130**: Azure production profiles MUST explicitly classify object storage containers for artifacts, memory/wiki/index data, corpus remittance bundles, and audit records.
- **FR-131**: Azure production profiles MUST prefer managed Azure services first: Container Apps for runtime cells, Event Hubs Kafka protocol for managed bus, ADLS Gen2 or Blob Storage for object storage, PostgreSQL Flexible Server for relational state, Key Vault for secrets, and Azure Monitor/Application Insights for observability, while allowing AKS/Redpanda/Cosmos alternatives by explicit profile.
- **FR-132**: System MUST provide a shared approval ledger for memory promotion, dreaming conversion, deployment apply/promote/destroy, corpus remittance, policy enforcement, and protected CI/CD operations.
- **FR-133**: System MUST provide an effective runtime profile resolver that explains the combined state of feature toggles, sidecar tiers, tenant policy, deployment profile, worker health, budgets, toolsets, and memory retrieval mode before task dispatch or deployment.
- **FR-134**: Runtime event buses MUST use one canonical event envelope with event id, idempotency key, partition key, redaction state, replay attempt, and dead-letter reason across SQLite, Event Hubs, Redpanda, and Kafka paths.
- **FR-135**: LLM-backed sidecars MUST pass a sidecar budget governor before execution, with per-tenant, per-task, per-day, role-tier, token, and cost checks.
- **FR-136**: All worker execution paths MUST be covered by the supervisor context gate so raw worker streams cannot enter supervisor model context.
- **FR-137**: Approved memory MUST support quality lifecycle operations including confidence decay, stale suppression, retirement, compaction, and preserved audit history.
- **FR-138**: Dreaming proposal creation MUST enforce quota, dedupe, age, and backlog controls by tenant, proposal type, and risk.
- **FR-139**: Azure live deployment hardening MUST explicitly validate managed identity, RBAC, private endpoints, VNet integration, ingress mode, diagnostics, storage lifecycle policy, Key Vault access model, and rollback artifacts before production apply or promotion.
- **FR-140**: Operator dashboard UI MUST consume bounded redacted backend DTOs only and MUST NOT read raw worker logs, raw transcripts, provider logs, secrets, or unbounded event streams.
- **FR-141**: Dashboard job views MUST support tenant, repo, date, status, worker, model, blocker, cost, and deployment filters plus lazy-loaded line-item detail.
- **FR-142**: Dashboard approval actions MUST write through the shared approval ledger and preserve actor, role, tenant, action, target hash, expiry, evidence refs, and non-replay guarantees.
- **FR-143**: Dashboard scoped Ask MUST use read-only evidence bundles and MUST NOT have mutation authority over repo, memory, policy, deployment, task, or config state.
- **FR-144**: Dashboard cost and health panels MUST display token, latency, cost, worker, sidecar, memory, bus, budget, and degradation attribution by tenant/repo/job.
- **FR-145**: System MUST scrub secret-like values before persisting runtime-learning records, evidence excerpts, candidates, bus events, sidecar jobs, Slack/dashboard payloads, or training corpus artifacts.
- **FR-145A**: System MUST provide a context admission gate that prevents raw worker streams, long command outputs, sidecar logs, Slack mirrors, repeated status reports, and full artifacts from entering supervisor model context.
- **FR-145B**: System MUST store full worker/tool/sidecar updates outside model context with durable event or artifact refs.
- **FR-145C**: System MUST provide bounded progress checkpoints with current task state, latest progress, blocker, next action, validation refs, memory refs, and artifact refs within a configured token cap.
- **FR-146**: System MUST provide a model-role doctor that resolves provider/model/tier/path/auth readiness from service-equivalent environments without printing secrets.
- **FR-147**: System MUST ensure `goal_judge` model invocation is explicit and observable; unavailable auxiliary clients MUST return structured degraded status instead of silent prompt-dependent continuation.
- **FR-148**: System MUST provide service-equivalent sidecar status and one-shot execution surfaces with locks, budgets, intervals, degraded reasons, and foreground-nonblocking guarantees.
- **FR-149**: `supervisor_runtime_failure` records MUST include bounded tenant/repo/task/worker/route/status/latency/evidence metadata where available and MUST classify sparse evidence as insufficient for automatic approval.
- **FR-150**: System MUST prove one skill evolution loop from failure or approved memory to skill candidate, judge decision, operator approval, scoped skill packet, and outcome feedback.
- **FR-151**: System MUST provide a production runtime smoke that validates Claude primary, Codex fallback/judge, curator, learning judge, goal judge, sidecars, memory injection, skill retrieval, Slack/dashboard alerts, and cost/context telemetry with enforcement disabled.
- **FR-152**: System MUST expose live runtime impact UI/API surfaces showing sidecars by category, sidecars by job, memory activity timelines, foreground/background latency attribution, and cost/context attribution from real state.
- **FR-153**: Runtime impact surfaces MUST distinguish foreground-blocking latency from asynchronous sidecar latency and MUST keep raw logs, raw transcripts, provider logs, and secrets out of default UI/API responses.

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
- **Failure Repair Training Record**: Approved training item that pairs a lesser-model failure with stronger-model diagnosis, corrected output, validation evidence, and distilled future behavior.
- **Preference Training Pair**: Training item with one prompt, a validated chosen response, and a rejected lesser-model response that failed validation or policy.
- **External Training Hint**: Non-executing metadata emitted by Hermes that recommends target model family, training method, corpus refs, evaluation refs, and approval refs for an external MLOps pipeline.
- **Corpus Remittance Receipt**: Immutable Hermes audit record showing an approved corpus bundle was handed off to configured storage or an external MLOps endpoint.
- **External MLOps Platform**: Separate infrastructure that owns batch or streaming fine-tuning, model registry, evaluation gates, serving, and rollout decisions.
- **Azure Deployment Profile**: Versioned deployment intent for dev, staging, or production containing region, subscription, resource group, runtime-cell mode, bus backend, storage, secrets, observability, network, DNS, connector, and cost settings.
- **Deployment Plan**: Read-only artifact showing resources to create/change, estimated cost, risks, required secrets, approval gates, smoke tests, and rollback path.
- **Deployment Preflight Report**: Validation result for Azure login, subscription, quotas, resource providers, DNS, Key Vault, storage, network, container/runtime capacity, and optional bus availability.
- **Deployment Apply Run**: Operator-approved execution record for Azure resource creation or update, with step status, artifacts, logs, and rollback refs.
- **Deployment Promotion Gate**: Staging-to-production decision requiring smoke tests, soak metrics, health checks, cost/latency checks, and operator approval.
- **Azure Object Storage Plane**: ADLS Gen2 or Blob Storage containers used for deployment artifacts, memory/wiki/index artifacts, corpus remittance bundles, benchmark outputs, and audit reports.
- **Azure State Store Plane**: PostgreSQL or Cosmos-backed durable control-plane state for tenants, repos, jobs, allocations, memory metadata, deployment profiles, deployment runs, approvals, and cost ledgers.
- **Shared Approval Ledger Entry**: Durable authorization record binding actor, role, tenant, action, target ref, target hash, expiry, approval channel, replay policy, and audit refs.
- **Effective Runtime Profile**: Read-only merged view of runtime feature toggles, sidecar roles, tenant/repo policy, deployment profile, toolsets, budgets, memory mode, and worker health.
- **Canonical Event Envelope**: Cross-backend bus message wrapper carrying event identity, idempotency, partitioning, redaction, replay, and dead-letter metadata.
- **Sidecar Budget Decision**: Deterministic allow/deny/degrade decision made before an LLM-backed sidecar call.
- **Retrieval Run**: Audit record for a retrieval request, including filters, lexical/vector/graph candidates, rerank scores, and packet output.
- **Feature Toggle**: Runtime configuration switch that controls whether a platform capability can affect foreground behavior, sidecar behavior, observability, or enforcement.
- **E2E Feature Test Case**: One executable feature-level scenario with required toggle state, workload fixture, expected artifacts, telemetry assertions, validation commands, and pass/fail classification.
- **E2E Feature Test Report**: Operator-facing summary of feature state, test evidence, platform impact, cost/latency, and rollout recommendation.
- **Tenant**: Organization or power-user boundary with users, roles, repos, communication channels, budgets, feature policy, runtime isolation, and memory visibility rules.
- **Runtime Cell**: Isolated execution environment for a tenant workspace, including Hermes home, state, worktrees, secrets, memory, sidecars, worker allocation, and event spool.
- **Repository Registration**: Tenant-scoped record describing a connected repo, branch/protection policy, validation commands, Spec Kit policy, deployment mapping, and secret references.
- **Communication Connector**: Tenant-scoped Slack, Telegram, WhatsApp, dashboard, API, email, or webhook binding that maps authenticated messages to task packets and replies.
- **Toolset Profile**: Tenant/repo/job-scoped configuration for enabled planning, coding, QA, browser, TinyFish, deployment, cloud, media, and repo tools with scopes and budgets.
- **CI/CD Toolset**: Tenant-scoped capability that lets Hermes create, inspect, repair, run, validate, and report on build/test/deploy pipelines while respecting secrets, approvals, and protected environments.
- **Skill**: Versioned procedural artifact, usually `SKILL.md` plus optional files, that teaches an agent how to perform a recurring task pattern.
- **Skill Packet**: Bounded prompt-ready representation of selected skills with ids, versions, summaries, match reasons, scope, confidence, and validation hooks.
- **Skill Candidate**: Proposed skill creation/update derived from approved memory or wiki evidence and awaiting validation/approval.
- **Skill Outcome Feedback**: Post-task record linking a skill version to helpful, irrelevant, harmful, or unknown impact.
- **SkillClaw Adapter**: Optional integration boundary for reading/writing skill bundles, validating candidates, and syncing tenant/global skill libraries.
- **Dreaming Conversion Target**: Approved destination for a proposal, such as memory candidate, wiki update, skill candidate, test task, Spec Kit task, CI/CD hardening task, policy audit candidate, routing advisory, or training corpus candidate.
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
- **Task Graph**: Supervisor-owned durable graph for a long-running request, containing task nodes, dependencies, concurrency limits, ownership rules, allocation refs, validation refs, and completion status.
- **Task Node**: Bounded unit of work inside a task graph with dependencies, owned paths, worker assignment, memory packet, validation requirement, artifact refs, and state.
- **Health Check Run**: Background sidecar execution record that scans task graphs, leases, allocations, workers, heartbeats, and degradation events and emits bounded recovery actions.
- **Recovery Decision**: Startup or sidecar decision that marks a task/allocation safe to resume, paused, blocked, reassignable, or requiring operator action.
- **Benchmark Workload**: Versioned task definition used by upstream and branch environments with prompt, repo refs, tool/model profile, expected artifacts, validation commands, and pass/fail rubric.
- **Telemetry Span**: Runtime measurement record for one model call, worker attempt, sidecar run, judge run, memory retrieval, notification, or validation step.
- **Production Gate Report**: Aggregated upstream-vs-branch result deciding whether the branch is eligible for broader rollout.

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
- **SC-021**: Task graph tests prove dependency ordering, concurrency caps, owned-path conflict rejection, validation-gated completion, and supervisor-only subtask acceptance.
- **SC-022**: Health sidecar tests prove stale leases, missing heartbeats, no-progress loops, repeated timeout/empty-output failures, and quota/network degradation produce bounded recovery actions without blocking foreground runtime.
- **SC-023**: Restart recovery tests prove active goals, task graphs, allocations, worker health, and approved memory are reloaded; unsafe workers are skipped; unknown in-flight attempts are not assumed successful; and expensive LLM sidecars are not called by default.
- **SC-024**: Benchmark harness tests prove upstream and branch runs use isolated Hermes homes, shared workload definitions, separate artifacts, and comparable model/tool profiles.
- **SC-025**: Telemetry tests prove token/cost/latency/context/path attribution is recorded for supervisor, workers, sidecars, judges, memory retrieval, QA, deployment, and Slack/dashboard analysis.
- **SC-026**: Production gate tests prove rollout is blocked when branch quality is worse than upstream, sidecars block foreground work, urgent alerts are missing, or memory approval boundaries are violated.

## Assumptions

- SQLite `state.db` remains the first durable event bus implementation.
- Redis Streams or Kafka are future options only after local SQLite bus limits are proven.
- Codex can be the initial learning judge provider; Qwen or Cerebras-backed models can be configured later.
- Existing Hermes CLI and dashboard/backend patterns should be reused instead of introducing a separate service.
- Existing learning sidecar, curator policy runner, housekeeping, retrieval, and policy audit code remain the base implementation.
- Operator approval means explicit user or admin action through CLI/API/config, not implicit model confidence.
- Non-trivial implementation work defaults to Spec Kit preservation; trivial fixes and explicit user opt-out are recorded as exceptions.
- SQLite metadata and FTS5 are the first retrieval index layer; vector and graph backends must be optional/configurable and can start with SQLite-backed implementations.
