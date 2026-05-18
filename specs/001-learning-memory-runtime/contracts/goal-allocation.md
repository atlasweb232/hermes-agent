# Goal-Based Multi-Agent Allocation Contract

## Scope

This contract defines the implementation phase for combining upstream `/goal`
continuation with deterministic multi-agent worker allocation.

`/goal` remains the continuation loop and pause/resume control plane. The
allocator runs inside a bounded goal/task turn and decides which worker route to
try, when to fallback, when to pause, and what evidence to persist.

## Non-Goals

- Do not create a second autonomous loop beside `/goal`.
- Do not let an LLM decide completion without deterministic validation.
- Do not foreground sleep while waiting for network, quota, or auth recovery.
- Do not hardcode Claude-specific repair paths; all worker outcomes use generic
  status and health records.
- Do not promote allocation lessons into enforcement without judge and operator
  approval.

## State Keys

Use existing `SessionDB.state_meta` control-plane storage:

```text
goal:<session_id>
allocation:<session_id>:<task_id>
worker_health:<worker_id>
```

The allocation key must survive process restart so `/goal resume` can recover
attempt history, budget consumption, cooldowns, and next recovery action.

## WorkerAllocationPlan

Required fields:

```json
{
  "version": "2026.05.goal-allocation.v1",
  "allocation_id": "alloc_...",
  "task_id": "task_...",
  "session_id": "20260518_...",
  "goal_key": "goal:<session_id>",
  "tenant_id": "atlas",
  "repo_id": "atlasweb-mini",
  "objective": "bounded task objective",
  "memory_packet_id": "mempkt_...",
  "candidate_workers": ["claude-code", "codex", "deepseek"],
  "primary_worker": "claude-code",
  "fallback_order": ["codex", "deepseek"],
  "latency_budget_seconds": 120,
  "per_worker_timeout_seconds": 30,
  "max_attempts": 3,
  "retry_same_worker": 0,
  "cooldown_seconds": 300,
  "retry_after_seconds": 300,
  "validation_required": true,
  "status": "active",
  "created_at": 0,
  "updated_at": 0
}
```

Valid `status` values:

- `active`
- `completed`
- `paused`
- `blocked`
- `exhausted`
- `cancelled`

## WorkerAttemptResult

Required fields:

```json
{
  "attempt_id": "attempt_...",
  "allocation_id": "alloc_...",
  "worker_id": "claude-code",
  "route": "worker-router claude",
  "status": "success",
  "started_at": 0,
  "finished_at": 0,
  "duration_seconds": 0,
  "stdout_excerpt": "",
  "stderr_excerpt": "",
  "artifact_refs": [],
  "error_signature": "",
  "validation_status": "skipped",
  "fallback_allowed": true,
  "recovery_hint": ""
}
```

Valid `status` values:

- `success`
- `failed`
- `timed_out`
- `empty_output`
- `quota_exhausted`
- `auth_failed`
- `network_degraded`
- `blocked`
- `cancelled`

Valid `validation_status` values:

- `passed`
- `failed`
- `skipped`
- `not_applicable`

## WorkerHealth

Required fields:

```json
{
  "worker_id": "claude-code",
  "provider": "anthropic",
  "last_success_at": 0,
  "last_failure_at": 0,
  "failure_count": 0,
  "empty_output_count": 0,
  "timeout_count": 0,
  "quota_exhausted_until": 0,
  "network_degraded_until": 0,
  "auth_failed_until": 0,
  "cooldown_until": 0,
  "last_error_signature": "",
  "confidence": 1.0,
  "updated_at": 0
}
```

Worker health is advisory to allocation and evidence for observability. It is
not approved memory and must not be injected into prompts as durable truth.

## Lifecycle

1. A user, dashboard, or `/goal` continuation creates a supervisor task packet.
2. Runtime memory retrieval builds a compact advisory packet for the task.
3. The allocator creates or resumes `WorkerAllocationPlan`.
4. The allocator filters candidate workers using `WorkerHealth`, cooldowns,
   total latency budget, per-worker timeout, retry budget, and repeated-route
   suppression.
5. The selected worker receives a bounded delegation packet.
6. The worker wrapper records `WorkerAttemptResult`.
7. The allocator updates allocation state, worker health, runtime failure
   capture, and observability.
8. If validation succeeds, the supervisor may continue toward completion.
9. If fallback is available and budget remains, the allocator tries the next
   ranked worker.
10. If no safe attempt remains, the allocator pauses or blocks the allocation
    with `retry_after_seconds` and lets `/goal` or operator action resume later.

## Invariants

- `/goal` may continue the session but cannot complete, override, or validate a
  task by itself.
- The allocator cannot exceed `latency_budget_seconds` for one foreground turn.
- The same failed route cannot be retried indefinitely.
- Quota, auth, and network failures create cooldown state instead of foreground
  sleep loops.
- Empty output from worker wrappers is a degraded attempt unless accompanied by
  explicit success evidence.
- Final supervisor responses must disclose degraded worker evidence.
- Durable memory/policy promotion remains outside this contract and requires
  existing judge/operator gates.

## Observability Contract

Allocator CLI/API JSON must support:

- list active allocations
- show one allocation by id
- show worker health
- show attempt history
- show consumed and remaining latency budget
- show fallback reason
- show cooldowns and retry-after
- show linked goal/session/task ids
- show next recovery action

Initial CLI target:

```text
hermes runtime allocations list --json
hermes runtime allocations get <allocation_id> --json
hermes runtime workers health --json
```

## Tests

Required test scenarios:

- quota exhaustion selects fallback or pauses with retry-after
- auth failure does not loop and records health cooldown
- network degradation does not foreground sleep
- worker timeout respects per-worker and total latency budgets
- empty worker output is degraded and cannot be reported as worker success
- repeated failed route is suppressed
- ranked fallback succeeds and records original failed attempt
- all workers unhealthy pauses allocation
- `/goal resume` recovers allocation state without retrying cooled-down workers
- final response discloses degraded evidence when supervisor fallback is used
