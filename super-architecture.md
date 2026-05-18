# Hermes Super Architecture

## Purpose

Hermes needs a long-running workflow architecture that can continue work,
allocate tasks across multiple agents, preserve supervisor memory and control,
recover after outages, and improve from failures without letting background
learning or goal continuation degrade foreground work.

The core rule is:

```text
goal is the continuation primitive;
supervisor is the orchestration authority;
allocator is the worker routing authority;
sidecars are background observers and learners.
```

## Authority Model

### Goal

`/goal` is a durable continuation loop.

It may:

- persist goal state
- continue a session
- pause, resume, clear, or stop
- enforce max turn budget
- ask a goal judge whether another turn is needed

It must not:

- bypass supervisor task state
- choose workers directly
- validate implementation completion
- override Spec Kit, leases, or recovery policy
- retry unhealthy workers forever
- promote memory, policies, or configuration

### Supervisor

The supervisor owns task meaning and completion authority.

It must:

- convert user/dashboard/API requests into task packets
- create or update Spec Kit artifacts for non-trivial work
- preserve master instructions and session summaries
- load relevant memory packets
- create task graph and subtask packets
- request planner, reviewer, and worker agents
- validate work before completion
- decide completion, block, escalation, or abandonment

The supervisor may create or attach a goal when the task needs continuation, but
the goal remains subordinate to supervisor state.

### Allocator

The allocator owns worker routing for a bounded task turn.

It must:

- read task packet, memory packet, worker health, and allocation state
- create a `WorkerAllocationPlan`
- rank candidate workers
- enforce latency budget, per-worker timeout, retry budget, and cooldown
- suppress repeated failed routes
- record `WorkerAttemptResult`
- choose fallback workers when safe
- pause with retry-after when no safe worker remains

The allocator is generic. It is called by chat, goal, dashboard, API, or
supervisor task workflows. It is not a goal-only feature.

### Health Sidecar

The health sidecar monitors platform degradation out of band.

It should:

- detect stale leases and missing heartbeats
- detect no-progress loops
- detect repeated command/error signatures
- update worker health
- emit recovery candidates or recovery tasks
- avoid blocking chat, tool execution, or worker dispatch

It should not:

- directly complete tasks
- directly promote memory
- directly change policy enforcement
- sleep in the foreground on network recovery

### Learning Sidecars

Learning sidecars convert evidence into reusable knowledge.

They include curator, judge, memory wiki, dreaming, indexer, sync, and
housekeeping jobs.

They should:

- consume runtime events asynchronously
- produce candidates, decisions, wiki claims, proposals, or indexes
- run with bounded leases, timeouts, rate limits, and configured model roles
- keep raw events, candidates, wiki, dreaming, policies, and training data
  separate

They must not:

- block foreground runtime
- inject unapproved proposals
- enforce policy without judge and operator approval
- copy private tenant evidence globally without approval

## Long-Running Self-Healing Workflow

```text
user/dashboard/API request
  -> supervisor task packet
  -> Spec Kit preservation if non-trivial
  -> optional goal creation for continuation
  -> task graph / subtask planning
  -> memory retrieval and compact advisory packet
  -> allocator creates or resumes WorkerAllocationPlan
  -> allocator dispatches ready subtasks to ranked workers
  -> workers heartbeat and emit progress/results
  -> runtime degradation gate classifies attempts
  -> allocator updates WorkerAttemptResult and WorkerHealth
  -> validator checks outputs and evidence
  -> health sidecar detects stale/no-progress/degraded state
  -> learning sidecars curate failures and successes
  -> goal continues, pauses, resumes, or stops
  -> supervisor decides completion/block/escalation
```

## Parallel Task Allocation

Parallelism belongs to the supervisor task graph and allocator, not to `/goal`.

The supervisor should:

- split work into independent subtasks
- assign ownership and worktrees
- cap concurrency
- keep merge/review authority
- prevent workers from overwriting each other
- preserve per-subtask memory packets and validation evidence

The allocator should:

- choose a worker per subtask
- track per-worker and global latency budgets
- avoid dispatching new work to unhealthy workers
- fallback only when budget and ownership rules allow

## Recovery After Outage

Persisted state must allow restart from where work stopped:

- `goal:<session_id>` for continuation state
- `allocation:<session_id>:<task_id>` for active allocation state
- `worker_health:<worker_id>` for degraded worker state
- supervisor task ledger for task graph, ownership, validation, and recovery
- runtime event bus for attempt, heartbeat, failure, and learning signals
- Spec Kit and git branches/worktrees for durable implementation state

On restart:

```text
service starts
  -> load active goals
  -> load supervisor task ledger
  -> load active allocations
  -> load worker health and cooldowns
  -> hydrate hot memory from local/global approved lessons
  -> resume only safe ready work
  -> skip unhealthy workers until cooldown expires
```

## Runtime Degradation Integration

The degradation gate is generic and sits below every workflow:

```text
chat / goal / dashboard / API
  -> supervisor task packet
  -> allocator / worker dispatch
  -> terminal/tool/worker result
  -> degradation classifier
  -> structured failure memory/event capture
  -> final response disclosure or allocator recovery
```

This means the same timeout, empty-output, evidence-mismatch, and failed-route
logic applies whether the task came from `/goal`, manual chat, dashboard, API,
or a worker delegation.

## Worker Progress And Context Preservation

Worker progress is runtime data first, not supervisor prompt content. Every
worker invocation must be wrapped by runtime code that emits typed events:
start, heartbeat, stream reference, checkpoint, blocked/degraded, validation,
and final result. This is enforced by wrappers and the event bus, not by asking
the worker model to remember to report progress.

Raw worker streams, stdout/stderr bodies, terminal transcripts, and log tails
are stored as artifacts and exposed through observability. They do not enter
supervisor context directly. A supervisor context gate admits only compact
typed packets at decision boundaries: allocation decisions, bounded progress
checkpoints, blocked/degraded packets, validation packets, recovery packets,
and final worker results.

A cheap progress summarizer sidecar can convert durable worker events into
bounded checkpoints for Slack, dashboard, and supervisor review. That sidecar
uses the configured low-cost reasoning tier by default, such as a local small
model or hosted low-cost model. It cannot mark work complete, approve memory,
or enforce policy.

## Memory And Learning Integration

Memory retrieval is a task-start service:

```text
task metadata
  -> local hot memory
  -> local approved memory/wiki
  -> approved global lessons
  -> compact advisory packet
  -> supervisor/planner/worker context
```

Learning is an asynchronous feedback service:

```text
runtime event / task outcome
  -> bus
  -> curator / judge / wiki / dreaming / housekeeping
  -> approved memory or proposal
  -> future retrieval or policy candidate
```

Unapproved candidates and dreaming proposals must never be injected directly.

## Spec Kit Coverage Review

### Already Captured

- Goal is continuation, not orchestration authority.
  - `specs/001-learning-memory-runtime/spec.md` FR-058, FR-060
  - `specs/001-learning-memory-runtime/contracts/goal-allocation.md`
  - `docs/multi-agent-allocation-architecture.md`

- Allocator owns worker routing, latency budget, fallback, and cooldown.
  - `specs/001-learning-memory-runtime/spec.md` FR-061 through FR-064
  - `specs/001-learning-memory-runtime/tasks.md` Phase 12
  - `specs/001-learning-memory-runtime/contracts/goal-allocation.md`

- Runtime degradation gate is generic and already implemented for supervisor
  final-response disclosure.
  - `specs/001-learning-memory-runtime/tasks.md` T131A and T131A1
  - `docs/deterministic-completion-gate-architecture.md`

- Sidecars must run out of band and not block foreground execution.
  - `specs/001-learning-memory-runtime/spec.md` FR-014, FR-015, FR-038
  - `specs/001-learning-memory-runtime/tasks.md` US3, US5, US6
  - `docs/curator-policy-framework-architecture.md`

- Worker progress must be emitted by wrappers and gated before supervisor
  context injection.
  - `specs/001-learning-memory-runtime/spec.md` FR-071 through FR-074
  - `specs/001-learning-memory-runtime/contracts/worker-progress-context-gate.md`
  - `specs/001-learning-memory-runtime/tasks.md` T167 through T174

- Memory/wiki/dreaming/policy/training layers are separated.
  - `specs/001-learning-memory-runtime/spec.md` FR-016, FR-032 through FR-044
  - `docs/curator-policy-framework-architecture.md`
  - `docs/global-memory-wiki-architecture.md`

- Task-level goal state and goal judge are supervisor-owned, not native goal
  completion authority.
  - `specs/001-learning-memory-runtime/tasks.md` Phase 9A
  - `docs/curator-policy-framework-architecture.md`

### Partially Captured

- Parallel subtask allocation is implied by supervisor task ledger,
  worktree assignment, and allocator fallback, but there is no dedicated
  parallel task graph contract yet.

- Health sidecar behavior is partially captured through stale lease,
  heartbeat, no-progress, and worker health concepts, but there is no dedicated
  health sidecar contract yet.

- Restart recovery is captured through goal state, allocation state, worker
  health, and supervisor ledger requirements, but there is no single recovery
  runbook contract yet.

- Cross-workflow generic allocator use is captured in architecture wording, but
  Phase 12 examples still emphasize `/goal`. Implementation should keep the
  allocator callable from chat, dashboard, API, and supervisor tasks.

### Phase 13 Artifacts Added

- `specs/001-learning-memory-runtime/contracts/task-graph.md` for
  supervisor-owned parallel subtasks, dependencies, ownership, concurrency caps,
  worktree assignment, and merge authority.

- `specs/001-learning-memory-runtime/contracts/health-sidecar.md` for stale
  lease detection, worker heartbeat monitoring, no-progress detection, cooldown
  updates, and recovery task emission.

- `specs/001-learning-memory-runtime/contracts/restart-recovery.md` describing
  exactly how service startup reloads goals, supervisor tasks, allocations,
  worker health, memory hot cache, and safe resumable work.

- `specs/001-learning-memory-runtime/contracts/worker-progress-context-gate.md`
  describing how worker streams remain observable without consuming supervisor
  context and how low-cost progress summarization stays non-blocking.

### Still Missing In Implementation

- Tests proving allocator is workflow-agnostic:
  - called from `/goal`
  - called from dashboard/API task
  - called from manual chat/supervisor task
  - same degradation classifier and worker health updates apply in all cases

- Runtime implementation for task graph, worker progress/context gate, health
  sidecar, and restart recovery.

## Implementation Principle

Build the allocator and health sidecar as generic runtime services first.
Then wire `/goal` into them as one caller.

Do not build goal-specific routing logic that cannot be reused by dashboard,
API, chat, or future autonomous workflows.
