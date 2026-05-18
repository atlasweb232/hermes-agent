# Forward Testing Strategy

## Principle

Test feature-by-feature, then run a small aggregate smoke after each slice. Do
not wait until every architecture phase is implemented before validating runtime
behavior.

The validation shape is:

```text
unit tests
  -> focused integration test
  -> VM smoke test
  -> aggregate regression smoke
```

## Aggregate Smoke

Keep the aggregate smoke small and repeatable:

- ask a worker-backed task where the primary worker is unavailable, slow, or
  returns empty output
- verify Hermes does not report false worker success
- verify fallback or pause behavior
- verify memory/event capture
- verify CLI/API exposes state
- restart Hermes and verify state is preserved

## Phase 12 Testing Order

1. Allocator schemas and serialization.
2. Allocation and worker-health state persistence.
3. Allocator decision policy for ranked fallback, repeated-route suppression,
   cooldowns, latency budget, and max attempts.
4. Supervisor delegation path wiring.
5. Allocator observability.
6. Upstream-vs-branch smoke proving reduced looping and clearer degradation
   disclosure.

## Phase 13 Testing Order

1. Task graph schema and ownership rules.
2. Dependency readiness and concurrency caps.
3. Health sidecar stale lease and no-progress detection.
4. Health sidecar bounded recovery actions.
5. Restart recovery loading goals, task graphs, allocations, worker health, hot
   memory, and safe-to-resume decisions.
6. Workflow-agnostic tests across chat, `/goal`, dashboard/API, and worker
   delegation.

## Stop Criteria

Stop and fix before moving forward if:

- a degraded worker attempt is reported as successful worker completion
- a failed route is retried indefinitely
- foreground chat waits on health, curator, judge, dreaming, wiki, or recovery
  sidecars
- restart assumes an unknown in-flight attempt succeeded
- unapproved memory, dreaming proposal, or policy candidate is injected
- parallel subtasks can write overlapping paths without supervisor approval
