# Supervisor Task Graph Contract

## Scope

The supervisor task graph is the durable representation of parallel and
dependent work under supervisor authority. It lets Hermes split a long-running
request into bounded subtasks without giving `/goal` or worker agents ownership
of orchestration, merge, validation, or completion.

## Non-Goals

- Do not use `/goal` as the task graph.
- Do not let workers create unbounded subtasks without supervisor approval.
- Do not allow parallel workers to share write ownership unless explicitly
  declared safe.
- Do not mark graph completion without validation evidence and session summary.

## TaskGraph

Required fields:

```json
{
  "version": "2026.05.task-graph.v1",
  "graph_id": "graph_...",
  "session_id": "20260518_...",
  "tenant_id": "atlas",
  "repo_id": "atlasweb-mini",
  "goal_key": "goal:<session_id>",
  "root_task_id": "task_...",
  "status": "active",
  "concurrency_limit": 2,
  "created_at": 0,
  "updated_at": 0
}
```

Valid `status` values:

- `active`
- `paused`
- `blocked`
- `completed`
- `cancelled`

## TaskNode

Required fields:

```json
{
  "task_id": "task_...",
  "graph_id": "graph_...",
  "parent_task_id": "task_parent",
  "title": "bounded subtask",
  "objective": "specific outcome",
  "status": "ready",
  "priority": 0,
  "dependencies": ["task_..."],
  "owned_paths": ["hermes_cli/..."],
  "worktree_ref": "worktree://...",
  "assigned_worker": null,
  "allocation_id": null,
  "memory_packet_id": "mempkt_...",
  "validation_required": true,
  "validation_refs": [],
  "artifact_refs": [],
  "created_at": 0,
  "updated_at": 0
}
```

Valid `status` values:

- `ready`
- `assigned`
- `running`
- `blocked`
- `review`
- `validated`
- `completed`
- `cancelled`
- `failed`

## Ownership Rules

- Every write-capable task must declare `owned_paths` or an explicit
  read-only/analysis mode.
- Two running tasks may not own overlapping paths unless the supervisor marks
  the overlap as safe.
- Workers may propose subtasks, but the supervisor must add them to the graph.
- Merge/review/validation belongs to the supervisor.

## Lifecycle

1. Supervisor creates a root graph for a non-trivial request.
2. Planner creates candidate task nodes and dependencies.
3. Supervisor validates node boundaries, ownership, and validation requirements.
4. Ready nodes are passed to the allocator within concurrency limits.
5. Worker attempts update task node status through structured results.
6. Validator moves nodes to `validated` or `blocked`.
7. Supervisor completes the graph only when required nodes are validated and
   final session summary is present.

## Tests

Required test scenarios:

- dependency ordering prevents early dispatch
- concurrency cap prevents too many parallel workers
- overlapping owned paths are rejected
- read-only tasks can run without owned paths
- failed validation blocks graph completion
- worker-proposed subtasks require supervisor acceptance
- completed graph includes Spec Kit refs, artifact refs, validation refs, and
  session summary
