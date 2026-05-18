# Supervisor Orchestration Contract

## Initialization Protocol

Every non-trivial task follows this sequence:

```text
load constitution
  -> classify source/user/repo/task
  -> ask clarification if scope is missing
  -> build TaskRetrievalQuery
  -> retrieve advisory MemoryPacket
  -> create SupervisorTaskPacket
  -> decide Spec Kit requirement
  -> create PlannerPacket
  -> create/update SpecKitArtifactSet
  -> create WorkerDelegationPacket
  -> validate WorkerResult
  -> create ValidationReport
  -> create SessionSummary
  -> publish learning/runtime events
```

## Prompt Templates

Runtime templates must exist for:

- `supervisor_intake.md`
- `supervisor_initialization_protocol.md`
- `memory_packet.md`
- `speckit_planner_packet.md`
- `worker_delegation_packet.md`
- `worker_result.md`
- `validation_report.md`
- `session_summary.md`

Templates guide model behavior, but runtime gates validate required packet fields.

## Spec Kit Requirement

Spec Kit is required when a task:

- modifies application/runtime code
- creates architecture or feature work
- delegates to implementation workers
- needs future continuation or review
- comes from dashboard with ambiguous scope and non-trivial implementation intent

Spec Kit may be skipped only when:

- the task is read-only investigation
- the task is a trivial local fix
- the user explicitly opts out
- emergency debugging requires immediate action

Skip reasons must be recorded in the supervisor task packet.

## Worker Routing Policy

The architecture defines roles, not fixed vendors:

- Supervisor owns user conversation, memory, approval, validation, and final response.
- Planner/Spec Kit creator uses the strongest configured reasoning model.
- Implementation workers use configured coding agents such as Claude Code Sonnet, Minimax via Claude Code, DeepSeek TUI, Cursor, or Codex.
- Reviewer/judge should be separate from the implementation worker when practical.

## Goal Loop Integration

Hermes already has a persistent `/goal` loop. It stores `GoalState` in
`SessionDB.state_meta` under `goal:<session_id>`, appends continuation prompts as
ordinary user-role messages, and supports pause/resume/clear without mutating
the system prompt.

Supervisor orchestration must reuse this lifecycle for long-running autonomous
work. It must not create a second unbounded continuation loop.

Multi-agent allocation runs inside a goal/task turn:

```text
GoalState continuation
  -> SupervisorTaskPacket
  -> WorkerAllocationPlan
  -> WorkerAttemptResult records
  -> runtime/completion gates
  -> goal judge
  -> continue | pause | done | operator escalation
```

## Multi-Agent Allocation Contract

Every non-trivial delegated task must create a `WorkerAllocationPlan` with:

- candidate workers
- primary worker
- ranked fallback order
- total latency budget
- per-worker timeout
- max attempts
- retry-same-worker policy
- cooldown/sleep policy for network, quota, and rate-limit failures
- memory packet id
- validation requirement

Allocator state should persist beside goal state:

```text
allocation:<session_id>:<task_id>
```

Worker health should persist separately:

```text
worker_health:<worker_id>
```

The allocator may sleep/recover only by updating control-plane state
(`cooldown_until`, `retry_after`, or goal pause). It must not keep foreground
chat blocked waiting for network recovery.

Every worker attempt must produce a `WorkerAttemptResult` with:

- worker id
- route
- status: `success`, `failed`, `timed_out`, `empty_output`,
  `quota_exhausted`, `network_degraded`, or `blocked`
- duration
- redacted stdout/stderr excerpts
- artifact refs
- error signature
- validation status
- fallback eligibility

## Runtime Gates

- No worker dispatch without a valid WorkerDelegationPacket.
- No non-trivial completion without a ValidationReport.
- No memory writeback without an evidence pointer.
- No enforcement without judge and operator approval.
- No Spec Kit bypass without a recorded skip reason.
- No repeated same-route retry after a matching degraded worker attempt unless
  retry budget explicitly allows it.
- No foreground sleep loop for network degradation; pause or schedule recovery
  through goal/allocation state instead.
