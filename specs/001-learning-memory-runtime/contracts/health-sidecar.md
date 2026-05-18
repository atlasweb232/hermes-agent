# Health Sidecar Contract

## Scope

The health sidecar monitors platform and worker degradation out of band. It
keeps long-running workflows from drifting, looping, or blocking foreground
execution by updating worker health, task status, and recovery signals.

## Non-Goals

- Do not run in the foreground chat/tool path.
- Do not directly complete tasks.
- Do not promote memory or policies.
- Do not execute unbounded sleeps.
- Do not replace deterministic validation.

## Inputs

The health sidecar reads:

- supervisor task ledger entries
- task graph nodes
- allocation state
- worker attempt results
- worker heartbeat/progress events
- terminal/tool degradation events
- runtime learning events

## Outputs

The health sidecar writes:

- worker health updates
- stale lease markers
- no-progress markers
- repeated-failure markers
- recovery packet references
- learning job status
- optional recovery task candidates

## HealthCheckRun

Required fields:

```json
{
  "run_id": "health_...",
  "status": "completed",
  "started_at": 0,
  "finished_at": 0,
  "tasks_scanned": 0,
  "allocations_scanned": 0,
  "workers_scanned": 0,
  "stale_leases": 0,
  "no_progress": 0,
  "cooldowns_set": 0,
  "recovery_candidates": 0,
  "errors": []
}
```

## Detection Rules

The sidecar must detect:

- stale worker lease
- missing heartbeat
- repeated command/error signature
- no git/test/progress delta over a configured window
- timeout or empty-output streak
- quota/auth/network degradation
- task stuck in running state beyond lease
- allocation with no safe worker remaining

## Recovery Actions

Allowed actions:

- update `worker_health:<worker_id>`
- set worker cooldown
- mark task node blocked or needs status
- emit recovery packet
- request supervisor reassignment
- pause allocation with retry-after
- record learning event for later curator/judge processing

Forbidden actions:

- edit repo files
- merge or revert code
- mark task complete
- approve memory
- enforce policy
- change model config without operator approval

## Scheduling

The sidecar may run:

- manually through CLI/API
- on service start
- on interval
- after allocation/worker events

Each run must use a bounded lease, timeout, scan limit, and maximum recovery
actions per run.

## Tests

Required test scenarios:

- stale lease produces recovery packet
- missing heartbeat does not block foreground chat
- repeated timeout sets worker cooldown
- no-progress loop marks task blocked or needs status
- quota/auth/network degradation pauses allocation with retry-after
- sidecar crash leaves foreground runtime unaffected
- duplicate sidecar runs are idempotent
