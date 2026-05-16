# Contract: Read-Only Observability API

## GET /api/tasks

Query parameters:
- `status`
- `tenant`
- `board`
- `repo`
- `branch`
- `assignee`
- `worker_kind`
- `provider`
- `model`
- `gate_status`
- `created_after`
- `created_before`
- `updated_after`
- `updated_before`
- `limit`
- `cursor`

Response:

```json
{
  "items": [
    {
      "task_id": "t_389db41d",
      "title": "Smoke: delegate TinyFish desktop form-fill planning slice",
      "status": "todo",
      "tenant": "atlas",
      "board": "default",
      "repo_path": "/home/rakib/git/atlasweb-mini",
      "branch": null,
      "assignee": "default",
      "worker_kind": null,
      "provider": null,
      "model": null,
      "gate_status": null,
      "last_event_type": "task.comment_added",
      "created_at": "2026-05-16T21:12:00Z",
      "updated_at": "2026-05-16T21:13:00Z"
    }
  ],
  "next_cursor": null
}
```

## GET /api/tasks/{task_id}

Returns task detail, parent/child tree, latest rollups, and links to runs/events.

## GET /api/tasks/{task_id}/events

Returns ordered event envelope records.

## GET /api/tasks/{task_id}/runs

Returns worker attempts, session ids, duration, model/provider, final status,
and gate status.

## GET /api/workers

Returns active and recently active worker/session rollups.

## GET /api/system

Returns Hermes service health, provider readiness, sidecar status, and active
system overrides. Secrets must be reported as present/missing only.

## GET /api/events/stream

Server-Sent Events stream of event envelopes or rollup updates.

