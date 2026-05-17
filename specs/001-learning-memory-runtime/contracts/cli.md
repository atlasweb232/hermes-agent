# CLI Contracts

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
