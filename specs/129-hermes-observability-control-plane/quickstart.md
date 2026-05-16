# Quickstart For Future Implementation

1. Start with event capture, not UI.
2. Emit events from Kanban, delegate_task, completion_gate, worker progress, and
   system service health.
3. Store events in SQLite append-only form.
4. Build deterministic rollups.
5. Expose read-only API.
6. Build dashboard against the read-only API.
7. Add advisory LLM digest after status truth is deterministic.
8. Add control actions only after read-only views are reliable.

## Example Smoke Scenario

Use the existing VM smoke task:

- Parent: `t_03de0037`
- Child: `t_389db41d`

Expected observability:

- `task.created` for both tasks.
- `task.comment_added` for TinyFish env prerequisite.
- `delegation.requested` when supervisor routes the child.
- `delegation.worker_selected` showing Codex-first routing.
- `worker.model_call` showing actual model/provider.
- `gate.started` and `gate.blocked` or `gate.passed`.
- `task.blocked` if env/toolchain/gate checks fail.

