# End-to-End Feature Testing Contract

## Purpose

Hermes needs a feature-level E2E test suite before more platform work is
productionized. The suite must verify each subsystem independently, then verify
the integrated path, while allowing operators to turn capabilities on or off
without breaking baseline chat and delegation.

This contract defines the minimum test matrix, feature toggle model, and report
shape.

## Feature Toggle Model

Every runtime capability must expose a CLI/API-compatible feature state:

- `feature_id`
- `configured`
- `effective`
- `default`
- `source`
- `risk_level`
- `dependencies`
- `last_changed_at`
- `last_changed_by`
- `reason`

The first implementation should support these feature ids:

- `supervisor.features.memory_retrieval`
- `supervisor.features.global_memory`
- `supervisor.features.runtime_failure_capture`
- `supervisor.features.runtime_failure_advisories`
- `supervisor.features.allocator`
- `supervisor.features.goal_continuation`
- `supervisor.features.health_sidecar`
- `supervisor.features.context_gate`
- `supervisor.features.progress_summarizer`
- `supervisor.features.learning_sidecar`
- `supervisor.features.curator`
- `supervisor.features.learning_judge`
- `supervisor.features.memory_wiki`
- `supervisor.features.dreaming`
- `supervisor.features.urgent_notifications`
- `supervisor.features.telemetry`
- `supervisor.features.benchmark_harness`
- `supervisor.features.enforcement`

### Defaults

- Baseline chat and delegation must remain available.
- Runtime failure capture, context gate, telemetry, and urgent notification
  features may default on only after smoke tests prove they do not block
  foreground work.
- Curator, judge, memory wiki, dreaming, global memory, and benchmark harness
  should default off or manual until their providers and cost budgets are
  configured.
- Enforcement must default false.

## CLI/API Surface

Planned surfaces:

- `hermes runtime features list --json`
- `hermes runtime features status --json`
- `hermes runtime features set <feature_id> <on|off> --reason ... --json`
- `hermes runtime e2e list --json`
- `hermes runtime e2e run --suite <suite> --features <ids|all> --json`
- `hermes runtime e2e report --run-id <id> --json`

The backend API should use the same schemas as the CLI.

## Feature Test Matrix

The E2E suite must include at least these line items:

| Feature Area | Enabled Test | Disabled Test | Main Evidence |
| --- | --- | --- | --- |
| Supervisor initialization and Spec Kit preservation | Non-trivial task creates/updates Spec Kit before delegation | Trivial task can skip with recorded reason | task packet, spec refs, validation report |
| Runtime failure capture | Worker timeout/empty output creates structured failure record | Failure happens with no learning write | runtime failure record, redacted excerpts |
| Curator and judge | Failure record becomes advisory candidate after review | Candidate remains raw/proposed when disabled | candidate, judge decision, approval status |
| Advisory retrieval/injection | Approved advisory appears in next bounded memory packet | No advisory packet is injected | retrieval run, memory packet |
| Allocator fallback and latency budget | Primary worker fails, fallback is attempted or paused | Supervisor discloses degradation without reallocation | allocation plan, attempt results |
| `/goal` continuation | Restart and `/goal resume` load safe allocation state | No goal continuation state is resumed | goal state, allocation refs |
| Context gate and progress summarizer | Worker streams are stored; supervisor gets bounded packets | Raw stream is not admitted and summarizer is skipped | stream refs, checkpoint packet |
| Health sidecar | Stale worker lease emits recovery packet | No health sidecar mutation occurs | lease, worker health, recovery packet |
| Restart recovery | Active state reloads without retrying unhealthy workers | No automatic resume occurs | recovery status |
| Task graph parallel dispatch | Ready nodes dispatch through allocator with owned paths | Parallel dispatch unavailable, sequential fallback used | task graph, owned paths |
| Memory wiki | Approved memory compiles to scoped wiki claim | Wiki remains unchanged | wiki claim, evidence refs |
| Dreaming | Offline proposal is created and held for approval | No proposal is created or injected | dreaming proposal, judge gate |
| Global memory and hot/warm/cold hydration | Scoped global lesson hydrates hot memory for task | Local-only retrieval runs | memory tier transitions |
| Urgent notifications | Blocked/degraded task posts to urgent Slack route | No notification sent and status records skipped-by-toggle | notification event |
| Telemetry and cost/context metrics | Token/cost/latency/context path metrics recorded | Task still runs with telemetry skipped | telemetry records |
| Dashboard/API observability | Job line item and detail bundle expose evidence | API shows feature disabled/skipped | observability line item |
| Upstream-vs-branch comparison | Feature states included in benchmark report | Branch runs baseline-only profile | comparison report |
| Azure chat/voice port workload | Real workload fixture exercises planning, delegation, validation | Workload is listed but skipped by toggle/profile | workload artifacts |

## Report Schema

Each test case result must include:

- `run_id`
- `suite_id`
- `case_id`
- `feature_ids`
- `feature_state`
- `tenant_id`
- `repo_id`
- `workload_id`
- `session_id`
- `task_id`
- `worker_ids`
- `model_provider_roles`
- `latency_budget`
- `token_cost_estimate`
- `artifacts`
- `telemetry_refs`
- `memory_refs`
- `sidecar_refs`
- `notification_refs`
- `validation_refs`
- `status`
- `failure_class`
- `rollout_recommendation`

## Safety Rules

- A disabled feature must not mutate runtime state beyond a skipped-feature
  audit event.
- A failed sidecar must not block foreground chat, terminal, or delegation
  unless the tested feature explicitly owns that gate.
- E2E tests must not store raw secrets, full transcripts, or unbounded logs in
  memory packets, wiki claims, dreaming proposals, or reports.
- Test fixtures may use synthetic secrets and synthetic provider responses.
- Live provider tests must be opt-in and tagged separately from deterministic
  CI tests.

## Definition Of Done

- Every major platform feature has an enabled and disabled test.
- Feature toggles are visible and auditable through CLI/API JSON.
- The E2E suite can run a deterministic local profile without cloud/provider
  credentials.
- A live profile can run the Azure desktop chat/voice workload when credentials
  and endpoints are provided.
- Reports make it clear whether a failure is a code defect, environment issue,
  provider issue, missing implementation, or expected disabled behavior.
