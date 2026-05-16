# Contract: Observability Event Envelope

All observability producers emit the same envelope.

```json
{
  "event_id": "evt_01h...",
  "event_type": "task.started",
  "schema_version": 1,
  "timestamp": "2026-05-16T21:13:00Z",
  "source": "kanban|delegate_task|completion_gate|worker|system|learning",
  "tenant": "atlas",
  "board": "default",
  "task_id": "t_389db41d",
  "parent_task_id": "t_03de0037",
  "run_id": "run_...",
  "session_id": "20260516_...",
  "worker_id": "default",
  "worker_kind": "codex|claude-code|deepseek-tui|hermes-child|unknown",
  "provider": "custom",
  "model": "gpt-oss-120b",
  "repo_path": "/home/rakib/git/atlasweb-mini",
  "branch": "128-118-tinyfish-web-agent",
  "severity": "debug|info|warning|error",
  "status": "ready|running|blocked|failed|done|passed",
  "payload": {},
  "redactions": ["secret:TINYFISH_API_KEY"],
  "correlation_id": "corr_..."
}
```

## Rules

- `event_id` is globally unique.
- `timestamp` is UTC ISO-8601.
- `payload` must be bounded.
- `payload` must not contain raw secrets.
- Worker/model/provider identity must come from runtime metadata, not prose.
- `correlation_id` links a user request, task, worker session, and gate run.

