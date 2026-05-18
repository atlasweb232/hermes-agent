# Restart Recovery Contract

## Scope

Restart recovery defines how Hermes resumes long-running workflows after process
restart, VM reboot, SSH disconnect, provider outage, or sidecar interruption.
The system must continue from durable state without repeating unsafe worker
routes or losing supervisor control.

## Non-Goals

- Do not replay raw transcripts into prompts.
- Do not resume unhealthy workers before cooldown expires.
- Do not mark tasks complete during startup.
- Do not run expensive curator/judge/dreaming work on startup unless explicitly
  configured and bounded.

## Durable Inputs

Startup recovery reads:

- `goal:<session_id>`
- supervisor task ledger
- task graph state
- `allocation:<session_id>:<task_id>`
- `worker_health:<worker_id>`
- runtime event bus leases/dead letters
- local hot memory cache
- approved local/global lessons
- Spec Kit refs and git/worktree refs

## Startup Sequence

```text
service start
  -> load config and model roles
  -> load active goals
  -> load supervisor task ledger
  -> load task graphs
  -> load active allocations
  -> load worker health and cooldowns
  -> inspect expired leases and in-flight sidecar jobs
  -> hydrate hot memory for active tasks
  -> identify safe ready tasks
  -> leave blocked/cooling-down tasks paused
  -> expose recovery status through CLI/API
```

## RecoveryDecision

Required fields:

```json
{
  "decision_id": "recovery_...",
  "session_id": "20260518_...",
  "task_id": "task_...",
  "allocation_id": "alloc_...",
  "decision": "resume",
  "reason": "worker healthy and dependencies satisfied",
  "safe_to_dispatch": true,
  "blocked_by": [],
  "retry_after_seconds": 0,
  "memory_packet_id": "mempkt_...",
  "created_at": 0
}
```

Valid `decision` values:

- `resume`
- `pause`
- `block`
- `request_status`
- `reassign`
- `abandon_requires_operator`

## Recovery Rules

- Active goals may continue only after supervisor task state is loaded.
- Allocations may resume only if remaining budget exists and selected workers
  are healthy.
- Workers in cooldown must be skipped until cooldown expires.
- Unknown in-flight worker attempts must become `request_status` or `blocked`,
  not assumed successful.
- Expired sidecar leases may be reclaimed, but sidecar outputs must remain
  advisory until validated.
- Hot memory hydration must use approved memory only.

## Observability

Initial CLI/API target:

```text
hermes runtime recovery status --json
hermes runtime recovery run --once --json
```

Output must include:

- active goals
- active task graphs
- active allocations
- unhealthy workers
- paused tasks
- safe-to-resume tasks
- blocked tasks and reasons
- retry-after timestamps
- stale sidecar leases

## Tests

Required test scenarios:

- restart with active goal and healthy worker resumes safely
- restart with cooled-down worker skips that worker
- restart with unknown in-flight attempt does not assume success
- restart with expired sidecar lease reclaims lease idempotently
- restart hydration uses approved memory only
- restart does not call expensive LLM sidecars by default
- recovery status exposes blocked and safe-to-resume tasks
