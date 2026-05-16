# Hermes Observability Control Plane Architecture

## Design Principle

Dashboard truth comes from structured events and deterministic validators, not
from LLM summaries.

LLMs may produce advisory digests. They must not set task status, gate status,
worker identity, model identity, or completion state.

## High-Level Components

```text
Hermes runtime producers
  - Kanban lifecycle
  - delegate_task
  - worker progress
  - completion gate
  - memory/learning sidecar
  - gateway/supervisor services
        |
        v
Observability event writer
        |
        v
Append-only event store
        |
        +--> deterministic rollup service
        |       - active jobs
        |       - historical jobs
        |       - worker status
        |       - system health
        |
        +--> read-only API
        |       - REST
        |       - SSE stream
        |
        +--> optional digest service
                - LLM summaries
                - citations to event ids
```

## Event Producers

### Kanban

Emits:
- `task.created`
- `task.ready`
- `task.claimed`
- `task.started`
- `task.blocked`
- `task.unblocked`
- `task.completed`
- `task.archived`
- `task.comment_added`
- `task.parent_linked`

### Delegation

Emits:
- `delegation.requested`
- `delegation.worker_selected`
- `delegation.worker_started`
- `delegation.worker_progress`
- `delegation.worker_completed`
- `delegation.worker_failed`
- `delegation.fallback_selected`
- `delegation.round_robin_selected`

### Completion Gate

Emits:
- `gate.started`
- `gate.check_completed`
- `gate.passed`
- `gate.blocked`

### Worker Runtime

Emits:
- `worker.heartbeat`
- `worker.tool_started`
- `worker.tool_completed`
- `worker.model_call`
- `worker.session_started`
- `worker.session_completed`

### System Runtime

Emits:
- `system.service_started`
- `system.service_stopped`
- `system.service_degraded`
- `system.override_applied`
- `system.config_changed`

## Event Store

Initial implementation should use SQLite because Hermes already uses SQLite for
Kanban/state and the VM deployment is single-node.

Later migration targets:
- SQLite + WAL for local/single VM.
- Redis Streams for multi-process fan-out.
- NATS for distributed multi-node deployments.

The event store must be append-only. Rollup tables are derived/cache tables and
can be rebuilt.

## Rollups

Rollups are deterministic program outputs:

- `active_jobs`: current status for running/todo/blocked tasks.
- `historical_jobs`: completed/blocked/archived jobs with filterable metadata.
- `worker_status`: latest heartbeat and current tool for each worker/session.
- `gate_status`: latest required gate result per task/run.
- `system_health`: Hermes services, sidecars, provider health, config readiness.

## API Shape

Read-only first:

- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/events`
- `GET /api/tasks/{task_id}/runs`
- `GET /api/workers`
- `GET /api/system`
- `GET /api/events/stream`
- `GET /api/digests/{task_id}`

Control APIs are explicitly out of scope for the first milestone. Later:

- retry
- reclaim
- block/unblock
- dispatch
- interrupt worker
- apply/revoke system override

## Dashboard Views

### Jobs Table

Columns:
- task id
- title
- repo
- branch
- board
- tenant
- assignee
- worker
- model/provider
- status
- gate status
- age/runtime
- last event

### Job Detail

Sections:
- task body
- parent/child tree
- event timeline
- worker runs
- commands/tools used
- completion-gate evidence
- blockers/recovery attempts
- memory packet and learning context
- final response/digest

### Active Workers

Sections:
- worker/session id
- task id
- current tool
- heartbeat age
- model/provider
- token/cost counters when available
- interrupt/reclaim state, read-only in first milestone

### System Health

Sections:
- gateway service
- supervisor service
- worker progress service
- learning sidecar
- provider configuration
- key/env readiness without exposing values
- system overrides

## LLM Digest Role

The digest service consumes event ids and bounded evidence. It may write:

- daily summaries
- task summaries
- blocker summaries
- routing effectiveness summaries

It may not write:

- task status
- gate status
- worker identity
- provider/model identity
- validation result

## Security

- Secrets must be redacted at write time.
- Event payload size must be bounded.
- Raw transcripts should be linked, not copied into dashboards by default.
- System override events must record actor, timestamp, reason, and scope.

