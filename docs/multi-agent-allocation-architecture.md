# Multi-Agent Allocation Architecture

## Purpose

Hermes should continue long-running work without getting trapped in a failed
worker route, network outage, quota exhaustion, or retry loop. The platform
should reuse the upstream `/goal` lifecycle for persistence and continuation,
then add deterministic multi-agent allocation inside each goal/task turn.

Spec Kit implementation artifacts live in:

- `specs/001-learning-memory-runtime/contracts/goal-allocation.md`
- `specs/001-learning-memory-runtime/tasks.md` Phase 12

## Existing Goal Mechanism

The current goal loop is implemented in `hermes_cli/goals.py`.

State is stored in `SessionDB.state_meta` under:

```text
goal:<session_id>
```

The stored `GoalState` includes:

- `goal`
- `status`: `active`, `paused`, `done`, or `cleared`
- `turns_used`
- `max_turns`
- `created_at`
- `last_turn_at`
- `last_verdict`
- `last_reason`
- `paused_reason`
- `consecutive_parse_failures`
- `subgoals`

After each turn, the goal judge evaluates the last assistant response. If the
goal is not complete, Hermes appends a normal user-role continuation prompt and
continues in the same session. It does not mutate the system prompt or toolset.

Important existing controls:

- user messages preempt continuation
- `/goal pause`, `/goal resume`, and `/goal clear` are control-plane actions
- turn budget auto-pauses the loop
- repeated judge parse failures auto-pause the loop
- judge transport/API errors fail open to `continue`

This is the correct continuation substrate. The multi-agent allocator should not
create a separate endless loop.

## Allocation Layer

The allocator sits inside a goal/task turn:

```text
/goal or dashboard task
  -> GoalState continuation loop
  -> SupervisorTaskPacket
  -> WorkerAllocationPlan
  -> ranked worker attempts
  -> WorkerAttemptResult
  -> completion/runtime gates
  -> goal judge
  -> continue, pause, done, or operator escalation
```

The goal loop decides whether another turn is needed. The allocator decides
which worker should receive the current turn's bounded work packet.

## Worker Allocation Plan

Each non-trivial delegated task should create a compact plan:

```json
{
  "task_id": "task_...",
  "session_id": "...",
  "goal_key": "goal:<session_id>",
  "tenant_id": "atlas",
  "repo_id": "atlasweb-mini",
  "objective": "...",
  "candidate_workers": ["claude-code", "codex", "deepseek"],
  "primary_worker": "claude-code",
  "fallback_order": ["codex", "deepseek"],
  "latency_budget_seconds": 120,
  "per_worker_timeout_seconds": 30,
  "max_attempts": 3,
  "retry_same_worker": 0,
  "cooldown_seconds": 300,
  "sleep_on_network_degradation_seconds": 60,
  "memory_packet_id": "gmem_...",
  "validation_required": true
}
```

The plan is evidence, not prompt text only. It must be persisted so a resumed
goal can recover the active allocation state.

## Storage Model

Reuse the same control-plane storage family as goals:

```text
state_meta key: allocation:<session_id>:<task_id>
```

This avoids creating a second persistence mechanism for pause/resume/stop. The
value should contain the latest `WorkerAllocationPlan`, worker attempt history,
latency budget consumption, cooldowns, and final state.

Durable learning evidence remains separate:

- raw attempts: learning/runtime events
- reusable lessons: memory records/global lessons
- policy candidates: curator/judge/operator pipeline

## Worker Health Registry

The allocator needs a lightweight health registry:

```text
state_meta key: worker_health:<worker_id>
```

Fields:

- `worker_id`
- `provider`
- `last_success_at`
- `last_failure_at`
- `failure_count`
- `empty_output_count`
- `timeout_count`
- `quota_exhausted_until`
- `network_degraded_until`
- `cooldown_until`
- `last_error_signature`
- `confidence`

Worker health should be updated from structured `WorkerAttemptResult` records,
not model prose.

## Latency Budget

Each allocation plan has a total latency budget and per-worker timeout.

Rules:

- never exceed the total task latency budget inside one turn
- never retry the same worker route indefinitely
- if the failure signature is network/quota/rate-limit, enter cooldown instead
  of immediate retry
- if all configured workers are unhealthy or over budget, pause the goal and
  surface operator action
- long-running implementation work should run in background workers and report
  progress instead of pinning foreground chat

## Sleep And Recovery

The platform should sleep/recover only as a bounded state transition:

```text
network/quota failure
  -> mark worker degraded
  -> set cooldown_until
  -> if fallback exists and budget remains, try fallback
  -> if no fallback, pause goal with retry_after
  -> /goal resume or scheduled continuation retries after cooldown
```

Do not keep a live foreground process waiting just because the network may
recover. Sleep belongs to the control plane, not the active model/tool loop.

## Worker Attempt Result

Every attempt should produce:

```json
{
  "attempt_id": "attempt_...",
  "worker_id": "claude-code",
  "route": "worker-router claude",
  "status": "success|failed|timed_out|empty_output|quota_exhausted|network_degraded|blocked",
  "started_at": 0,
  "finished_at": 0,
  "duration_seconds": 0,
  "stdout_excerpt": "",
  "stderr_excerpt": "",
  "artifact_refs": [],
  "error_signature": "",
  "validation_status": "passed|failed|skipped",
  "fallback_allowed": true
}
```

The supervisor final response may summarize this, but it must not overwrite the
structured status.

## Worker Progress Context Gate

Long-running workers should be observable without consuming the supervisor's
model context. Worker-router, delegation, and future allocator paths must emit
typed progress events programmatically:

- `worker_started`
- `worker_heartbeat`
- `worker_stream_ref`
- `worker_progress_checkpoint`
- `worker_blocked`
- `worker_degraded`
- `worker_validation`
- `worker_final`

Raw stdout, stderr, terminal streams, watch output, and log tails are artifact
references. They are not prompt material. The supervisor receives only bounded
typed packets at decision boundaries, and the packet must include refs back to
the raw evidence for audit.

A cheap progress summarizer sidecar may read the event/log refs and publish a
compact checkpoint for Slack, dashboard, or supervisor review. It uses the
configured low-cost reasoning tier and is not allowed to complete work, approve
memory, or enforce policy.

## Integration With Existing Runtime Gates

The current branch already has:

- runtime memory injection
- worker foreground timeout cap
- empty worker-wrapper output classification
- final-response degraded-worker disclosure
- `supervisor_runtime_failure` memory capture

The allocator should build on those pieces:

- use runtime memory before allocation
- consult worker health before dispatch
- classify each attempt with the same outcome vocabulary
- feed failed attempts into `supervisor_runtime_failure`
- feed successful attempts into validation/completion gates
- let `/goal` continue only after the allocator either completes, pauses, or
  escalates the current turn

## Upstream Comparison

Upstream goal handles continuation, pause/resume/clear, judge verdicts, and
state persistence. It does not provide multi-agent worker health, ranked
fallback allocation, latency budget accounting, or degraded-worker final
response enforcement.

Therefore the correct path is integration:

- keep upstream goal as the continuation loop
- add allocator state beside goal state
- reuse goal pause/resume semantics for blocked or cooling-down work
- do not create a second autonomous loop

## Open Implementation Items

Track implementation in Spec Kit Phase 12:

- add `WorkerAllocationPlan`, `WorkerAttemptResult`, and `WorkerHealth`
  schemas
- persist allocation state in `SessionDB.state_meta`
- add worker health registry helpers
- add allocator decision function with latency/retry/cooldown policy
- wire allocator into supervisor delegation path before direct fallback
- add CLI/API read surfaces for allocation status and health
- add tests for quota exhaustion, auth failure, network degradation, empty
  output, timeout, fallback to next worker, and goal pause on exhausted budget
