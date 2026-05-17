# CLI Contracts

## `hermes runtime task init --json`

Creates a supervisor task packet from a chat/dashboard/CLI request.

Expected response:

```json
{
  "status": "created",
  "task_packet_id": "taskpkt_example",
  "requires_speckit": true,
  "needs_clarification": false,
  "memory_packet_id": "mempkt_example"
}
```

## `hermes runtime speckit plan --task TASK_ID --json`

Creates or updates Spec Kit artifacts through the configured planner/Spec Kit creator role.

Expected response:

```json
{
  "status": "completed",
  "task_packet_id": "taskpkt_example",
  "artifact_set_id": "specart_example",
  "branch_name": "132-learning-memory-runtime",
  "artifacts": {
    "spec": "specs/001-learning-memory-runtime/spec.md",
    "plan": "specs/001-learning-memory-runtime/plan.md",
    "tasks": "specs/001-learning-memory-runtime/tasks.md"
  }
}
```

## `hermes runtime delegate --task TASK_ID --worker WORKER --json`

Validates and dispatches a worker delegation packet.

Expected response:

```json
{
  "status": "queued",
  "delegation_packet_id": "delegate_example",
  "worker": "claude-code-sonnet",
  "worktree_path": "/tmp/hermes-worktrees/example"
}
```

## `hermes runtime validate --task TASK_ID --json`

Creates a supervisor validation report before completion.

Expected response:

```json
{
  "status": "passed",
  "validation_report_id": "val_example",
  "git_preserved": true,
  "speckit_validated": true,
  "memory_outcome_recorded": true
}
```

## `hermes memory judge-run --json`

Runs the learning judge over eligible proposed candidates.

Expected response:

```json
{
  "status": "completed",
  "scanned": 3,
  "approved": 1,
  "rejected": 1,
  "needs_human": 1,
  "decisions": [
    {
      "candidate_id": "metacand_example",
      "decision": "approve",
      "risk": "low",
      "enforcement_allowed": false,
      "reason": "Evidence is sufficient for advisory retrieval."
    }
  ],
  "errors": []
}
```

## `hermes memory bus publish --topic TOPIC --json-payload JSON`

Publishes a durable runtime event.

Expected response:

```json
{
  "status": "queued",
  "event_id": "evt_example",
  "topic": "runtime.policy_audit"
}
```

## `hermes memory bus consume --consumer NAME --once --json`

Consumes eligible events with leases and retry limits.

Expected response:

```json
{
  "status": "completed",
  "consumer": "learning-rollup",
  "processed": 5,
  "failed": 0,
  "requeued": 0,
  "errors": []
}
```

## `hermes memory jobs list --json`

Lists active and historical learning jobs.

Expected response:

```json
{
  "active": [],
  "history": [
    {
      "id": "job_example",
      "job_type": "judge",
      "status": "completed",
      "metrics": {
        "approved": 1,
        "rejected": 1
      }
    }
  ]
}
```
