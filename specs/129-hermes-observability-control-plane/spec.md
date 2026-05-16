# Hermes Observability Control Plane Specification

## Summary

Hermes needs a first-class observability/control plane for supervisor, worker,
Kanban, memory, learning, and validation activity. The goal is to make task
truth inspectable without trusting LLM summaries.

The control plane must show historical jobs, active jobs, repository context,
worker/model routing, progress, completion-gate evidence, blockers, retries,
fallbacks, and system overrides.

## User Stories

### Story 1: Inspect Active Work

As an operator, I can open a dashboard/API view and see every active task with
repo, branch, assignee, worker, model/provider, current tool/action, heartbeat
age, runtime, and blocker status.

Acceptance criteria:
- Active tasks are listed without reading raw log files.
- Each task links to parent/child tasks and session/run records.
- Stale heartbeats are visibly marked.
- Blocked tasks show the blocker reason and last attempted recovery.

### Story 2: Audit Historical Jobs

As an operator, I can filter historical jobs by date range, repo, board, tenant,
assignee, status, worker, model/provider, and gate status.

Acceptance criteria:
- Results include task id, title, repo, branch, status, start/end time, duration,
  worker route, final gate status, and final outcome.
- Historical entries are backed by structured event/task/run records, not LLM
  prose alone.
- The dashboard can show both final summary and raw evidence links.

### Story 3: Trace Delegation And Routing

As an operator, I can see how a supervisor delegated work, which worker was used
first, what fallback/round-robin decisions happened, and why.

Acceptance criteria:
- Delegation events include requested worker, actual worker, model/provider,
  fallback reason, and final worker status.
- The UI distinguishes "worker claimed complete" from "gate verified complete".
- Model/provider identity is explicit and cannot be inferred from prose.

### Story 4: Monitor Deterministic Validation

As an operator, I can inspect completion-gate runs for each task.

Acceptance criteria:
- Gate checks show command, return code, status, and bounded output.
- A task cannot appear as verified complete unless required gate checks passed.
- Missing toolchains are shown as blockers, not successes.

### Story 5: Use Summaries Without Trusting Them

As an operator, I can read an LLM-generated digest of task history, but the
dashboard status remains derived from structured events and validators.

Acceptance criteria:
- Digest panels are labelled advisory.
- Digest generation includes citations to task events/run ids.
- Digest output cannot overwrite task status or gate status.

## Non-Goals

- Do not replace Kanban as the task source of truth.
- Do not make an LLM the authority for task status.
- Do not expose secrets, full raw transcripts, or unbounded tool output.
- Do not add destructive controls before read-only observability is reliable.

## Functional Requirements

1. Provide a canonical event envelope for task, worker, delegation, gate,
   memory, learning, and system events.
2. Persist observability events in an append-only store.
3. Provide rollups for active tasks, historical jobs, workers, and system health.
4. Provide filtering by date, repo, branch, board, tenant, assignee, status,
   worker, provider/model, and gate status.
5. Provide a read-only API suitable for a frontend dashboard.
6. Provide an optional SSE stream for live task/worker updates.
7. Provide a dashboard architecture that can be implemented after the API.
8. Capture completion-gate evidence as structured events.
9. Capture worker route/fallback/round-robin decisions as structured events.
10. Support advisory LLM digest generation without making it authoritative.

## Quality Requirements

- Event writes must be append-only and resilient to process restarts.
- Dashboard queries must avoid scanning raw log files on every request.
- Event payloads must be bounded and secret-redacted.
- The API must be usable in headless VM deployments.
- The architecture must work with the current Hermes Kanban/service model.

