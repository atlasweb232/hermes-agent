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

## `hermes runtime features list --json`

Lists deterministic local/dev runtime feature definitions without writing state.

Expected response:

```json
{
  "schema_version": 1,
  "scope": {
    "tenant_id": null,
    "repo_id": null
  },
  "features": [
    {
      "feature_id": "runtime.health_sidecar",
      "default_enabled": false,
      "runtime_affecting": true,
      "experimental": true,
      "safety": {
        "enforcement_allowed_default": false,
        "requires_explicit_enable": true
      }
    }
  ]
}
```

## `hermes runtime features status --json`

Resolves effective feature states for the optional tenant/repo scope.

Expected response:

```json
{
  "schema_version": 1,
  "scope": {
    "tenant_id": "tenant-a",
    "repo_id": "repo-a"
  },
  "features": [
    {
      "feature_id": "runtime.health_sidecar",
      "enabled": false,
      "effective": false,
      "source": "default",
      "override": null,
      "reason": null,
      "updated_at": null,
      "enforcement_allowed": false
    }
  ]
}
```

## `hermes runtime features set FEATURE_ID on|off --reason TEXT --json`

Writes a bounded scoped override to local state. A reason is required, secret-like
values are redacted, and enforcement remains disabled by default.

Expected response:

```json
{
  "feature_id": "runtime.health_sidecar",
  "enabled": true,
  "effective": true,
  "source": "override",
  "reason": "bounded health sidecar smoke",
  "updated_at": "2026-05-19T00:00:00Z",
  "scope": {
    "tenant_id": "tenant-a",
    "repo_id": "repo-a"
  },
  "enforcement_allowed": false
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

## `hermes runtime e2e list --json`

Lists deterministic local/dev E2E suites without writing state.

Expected response:

```json
{
  "schema_version": 1,
  "suites": [
    {
      "suite_id": "runtime.local_smoke",
      "workload_id": "runtime-local-dev-smoke",
      "profile": "deterministic-local-dev",
      "artifact_policy": {
        "isolated_hermes_home": true,
        "isolated_artifact_root": true,
        "bounded_evidence_only": true,
        "raw_transcripts_stored": false,
        "enforcement_allowed": false
      },
      "validation_commands": ["runtime-e2e:deterministic-local-smoke"]
    }
  ]
}
```

## `hermes runtime e2e run --suite runtime.local_smoke --json`

Runs the local deterministic smoke suite and persists a bounded run record in
local `state_meta`. Each run creates an isolated `HERMES_HOME` and artifact
root under `--artifact-root` or `$HERMES_HOME/runtime-e2e/<run_id>`.

Expected response:

```json
{
  "schema_version": 1,
  "run_id": "e2e_20260519T000000_example",
  "suite_id": "runtime.local_smoke",
  "workload_id": "runtime-local-dev-smoke",
  "status": "skipped",
  "scope": {
    "tenant_id": "tenant-a",
    "repo_id": "repo-a"
  },
  "isolated": {
    "hermes_home": "/tmp/hermes-e2e/e2e_example/hermes-home",
    "artifact_root": "/tmp/hermes-e2e/e2e_example",
    "state_db": "/tmp/hermes-e2e/e2e_example/hermes-home/state.db"
  },
  "safety": {
    "enforcement_allowed": false,
    "raw_transcripts_stored": false,
    "expensive_sidecars_started": false,
    "provider_calls": 0
  },
  "cases": [
    {
      "case_id": "runtime.health_sidecar.disabled_or_enabled",
      "feature_ids": ["runtime.health_sidecar"],
      "status": "skipped",
      "skip_reason": "feature disabled by scoped runtime toggle",
      "enforcement_allowed": false
    }
  ]
}
```

## `hermes runtime e2e status --run-id RUN_ID --json`

Returns the persisted bounded run record. `report` is accepted as a compatible
alias for callers that already adopted the earlier contract name.

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
