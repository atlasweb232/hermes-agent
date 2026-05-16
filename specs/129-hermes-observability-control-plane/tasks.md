# Implementation Tasks

This branch is documentation/specification only. Implementation should happen
after validating the currently running VM task behavior.

## Milestone 1: Structured Event Backbone

- [ ] Add `hermes_cli/observability/events.py` with event envelope dataclasses.
- [ ] Add SQLite migrations for `observability_events`.
- [ ] Add secret redaction helpers.
- [ ] Add bounded payload serialization.
- [ ] Emit Kanban lifecycle events.
- [ ] Emit completion-gate events.
- [ ] Emit delegate_task routing/fallback events.

## Milestone 2: Rollups

- [ ] Add deterministic rollup builder for active jobs.
- [ ] Add deterministic rollup builder for historical jobs.
- [ ] Add worker/session rollups from progress events.
- [ ] Add gate rollups from completion-gate events.
- [ ] Add rebuild command for derived rollup tables.

## Milestone 3: Read-Only API

- [ ] Add `GET /api/tasks`.
- [ ] Add `GET /api/tasks/{task_id}`.
- [ ] Add `GET /api/tasks/{task_id}/events`.
- [ ] Add `GET /api/tasks/{task_id}/runs`.
- [ ] Add `GET /api/workers`.
- [ ] Add `GET /api/system`.
- [ ] Add `GET /api/events/stream` SSE endpoint.

## Milestone 4: Dashboard

- [ ] Add jobs table.
- [ ] Add job detail page.
- [ ] Add active workers page.
- [ ] Add system health page.
- [ ] Add gate evidence panel.
- [ ] Add blocker/recovery panel.

## Milestone 5: Advisory Digest

- [ ] Add digest generator that consumes event ids.
- [ ] Store digest output separately from authoritative status.
- [ ] Require citations/event ids in digest output.
- [ ] Add daily and per-task digest views.

## Milestone 6: Controls

Controls are intentionally later than read-only observability.

- [ ] Retry task.
- [ ] Reclaim task.
- [ ] Block/unblock task.
- [ ] Dispatch task.
- [ ] Interrupt worker.
- [ ] Apply/revoke system override.

