# Runtime Learning Enforcement

This branch records how the VM Hermes runtime enforces the learning architecture from the atlas `128-hermes-agent-platform` spec.

## Runtime Branch

- VM repo: `/home/rakib/.hermes/hermes-agent`
- Runtime branch: `runtime-learning-enforcement`
- Base learning port: `memory-framework-on-current-main`

## Local Phase 10 Validation

Local validation on branch `132-learning-memory-runtime` completed on
2026-05-17 before VM deployment/smoke testing:

```bash
pytest tests/hermes_cli/test_supervisor_memory.py tests/hermes_cli/test_policy_engine.py tests/hermes_cli/test_config.py -q
# 92 passed

pytest tests/hermes_cli/test_learning_*.py -q
# 21 passed

pytest tests/hermes_cli/test_runtime_*.py -q
# 124 passed

pytest tests/hermes_cli/test_memory_index.py tests/hermes_cli/test_memory_graph.py tests/hermes_cli/test_memory_retrieval.py -q
# 7 passed
```

Total focused Phase 10 local coverage: 244 tests passed.

## VM Phase 10 Smoke Validation

VM deployment/smoke validation completed on 2026-05-17.

Deployment:

- VM host: `52.4.43.41`
- VM repo: `/home/rakib/.hermes/hermes-agent`
- Branch: `132-learning-memory-runtime`
- Commit deployed: `592298ceb3c386d618e8a603346867c6c522619e`
- Install path: `/home/rakib/.npm-global/bin/hermes`
- Runtime version after deploy: `Hermes Agent v0.14.0 (2026.5.16)`

Smoke results:

- Fast-forward deploy and editable reinstall succeeded.
- `hermes config tiers --json` returned `programmatic`,
  `low_cost_reasoning`, `balanced_reasoning`, and `strong_reasoning`.
- `hermes config roles --json` returned curator, learning judge, goal judge,
  discussion sidecars, dreaming, and citation validator role config.
- `hermes memory monitor --json` reported `healthy`, with `ready_packets=14`,
  `blocked_packets=0`, and `degraded_packets=0`.
- `hermes curator policy-run --json` completed and produced a valid
  `command_repair_policy` proposal for the Claude worker-router failure lesson.
- `hermes memory sidecar --once --json` completed:
  - rollup scanned 31 records
  - 31 records skipped as expected after housekeeping/filtering
  - skipped reasons included `curator_only:tool_routing_lesson`,
    `existing_candidate_status:approved`, and `synthetic_marker`
  - policy reconciliation completed
  - housekeeping completed
  - dreaming reported `skipped` because config keeps dreaming disabled
  - learning bus reported queued events
- Candidate list was clean after housekeeping: 3 approved candidates remained
  (`command_repair_policy`, `playbook`, and `routing_hint`).
- `hermes memory judge-run --json` completed with no pending candidates.
- Policy engine audit matched the approved Claude command-repair policy for
  `worker-router claude ...`; mode remained `audit`, command unchanged.
- Supervisor control plane smoke passed:
  - created a low-cost worker task
  - recorded heartbeat
  - assessed healthy task as non-reclaimable
  - created a stale low-cost worker task
  - stale assessment returned `reclaimable` with `lease_expired` and
    `missing_heartbeat`
  - recovery packet was created with next-worker recommendation `codex`
  - override `reclaim` moved the stale task to `reclaimed`
- Observability surfaces returned learning job line items.
- Learning sidecar service was restarted and verified `active`.

Known VM smoke gap:

- `hermes memory packet create --query "Use direct Claude Code when
  worker-router claude fails" ...` returned an empty compact packet even though
  the approved command-repair policy exists and policy-engine audit can match
  it. This means command-repair policy audit and compact memory retrieval are
  still separate paths on the VM. Phase 11 should include a task to either
  intentionally document that separation or add command-repair-policy retrieval
  into compact packets when relevant.

## VM Phase 11 Pre-Curation Smoke

VM pre-curation smoke validation completed on 2026-05-17.

Deployment:

- VM host: `52.4.43.41`
- VM repo: `/home/rakib/.hermes/hermes-agent`
- Branch: `132-learning-memory-runtime`
- Commit deployed: `f4889f4e1`
- Runtime version after editable reinstall: `Hermes Agent v0.14.0 (2026.5.16)`

Smoke scenario:

- Seeded an approved global command-repair lesson for the Claude
  `worker-router` failure signature.
- Replayed the duplicate failure event through `should_curate_locally(...)`.
- Replayed a near-match event with matching simhash and sufficient confidence.
- Replayed a miss where the only matching lesson was confidential and belonged
  to another tenant.
- Recorded aggregate reuse feedback for the global lesson without copying local
  private evidence into global memory.

Results:

- Exact global lesson hit returned `skip_global_exact_hit`.
- Exact hit returned `should_run_expensive_curator=false`.
- Exact hit emitted metric `global_lesson_hit`.
- Near global lesson hit returned `confirm_global_near_hit`.
- Near hit required lightweight local confirmation and skipped expensive
  curator work.
- Cross-tenant confidential match was rejected and returned `curate_locally`.
- Feedback update increased global lesson confidence only through aggregate
  reuse stats.
- `hermes memory sidecar --once --json` completed after deployment.
- Rollup skipped 31 noisy records rather than resurfacing them.
- `hermes memory monitor --json` remained `healthy`.
- Dreaming remained disabled by config and did not mutate runtime state.

Boundary:

- This smoke seeded the approved global lesson as an in-process Python object
  and passed it directly to `should_curate_locally(...)`.
- It did not write the lesson into the configured global memory backend.
- It did not retrieve the lesson from `~/.hermes/memory-wiki/global/state.sqlite`
  or another durable global index.
- It did not prove live `hermes chat` prompt injection or supervisor avoidance
  of the old command loop after restart.

Required next validation:

```text
persist approved global command-repair lesson
  -> restart Hermes
  -> retrieve persisted lesson for a fresh event
  -> run pre-curation
  -> record global_lesson_hit
  -> run live Hermes task
  -> verify old failure loop is not repeated
```

Acceptance criteria:

- The retrieved lesson source is durable storage, not a test dictionary.
- Retrieval audit shows exact signature/hash or bounded near-match reason.
- Wrong tenant, secret, rejected, and retired lessons are rejected before
  similarity scoring.
- Exact retrieved lesson skips expensive local curator work.
- Near retrieved lesson triggers only lightweight confirmation.
- Reuse feedback updates aggregate counters/confidence only.
- No private local evidence is imported into global memory without approval.

## Phase 11A Production Readiness Order

The next production work should stay narrow until value is measured. The
priority is not more infrastructure; it is proving that persisted memory makes
lower-cost workers repeat fewer mistakes.

Immediate order:

1. Persist approved global lessons in the configured local SQLite/global memory
   backend.
2. Retrieve persisted lessons for runtime events with hard metadata filters
   before any semantic matching.
3. Wire retrieved lessons into pre-curation before local curator or dreaming.
4. Materialize relevant approved global lessons into local hot cache for the
   task run using TTL, top-k, and tenant/repo/sensitivity gates.
5. Hydrate task-start memory by checking local hot cache first, persisted global
   lessons second, and merging the result with local memory wiki/policy hints
   into a compact advisory packet.
6. Add CLI/API JSON surfaces for operator testing and dashboard/backend use.
7. Add cost/value counters: memory hit, near hit, miss, skipped curator,
   skipped dreaming, estimated packet tokens, repeated error count, model used,
   and outcome feedback.
8. Run VM restart smoke with the Claude router lesson coming from durable
   storage.
9. Run a live Hermes task and verify the old command loop is avoided or
   explicitly escalated.
10. Run low-end model baseline vs memory-assisted eval.

Deferred until the above passes:

- Kafka/Redpanda production bus deployment.
- Production object/vector/graph backend adapters.
- Large training corpus export.
- Realtime voice.
- Full observability frontend beyond minimal JSON/status surfaces.
- Global indexer and local sync sidecars until local hot-cache hydration proves
  value.

Budget rule:

- Exact persisted lesson hit: programmatic only; no curator, judge, dreaming, or
  strong-model call by default.
- Near persisted lesson hit: cheap confirmation only if needed.
- Strong model: only for promotion, enforcement, contradiction, low confidence,
  or explicit operator request.

Shortest low-overhead runtime path:

```text
task metadata
  -> local hot cache
  -> persisted global exact/simhash lookup on miss
  -> materialize top-k to local hot cache
  -> merge with local wiki/policy hints
  -> compact advisory packet
  -> cheap worker
```

## Enforced Today

The active enforcement path is DB-backed and task-event driven:

1. Kanban task lifecycle events are captured for terminal outcomes: `completed`, `blocked`, `gave_up`, `crashed`, `timed_out`, `spawn_failed`, `reclaimed`, and `completion_blocked_hallucination`.
2. Captured events are mirrored into `state.db` as `hermes_memory_records` rows with `kind = task_outcome` plus linked `hermes_memory_evidence` rows.
3. The learning sidecar runs `rollup -> monitor -> reconcile` and records each pass in `hermes_learning_runs`.
4. Useful records become `hermes_meta_candidates` with status `proposed` unless promotion policy later approves them.
5. Promotion and auto-apply are policy gated. Auto-apply remains disabled by default.

## Persistent Supervisor Constitution

The VM stores persistent supervisor rules in `/home/rakib/.hermes/SOUL.md`. Hermes loads this file into the system prompt for new sessions. The constitution block tells the supervisor to preserve master instructions, prefer git/tests/logs over memory, delegate with bounded task packets, persist outcomes, and avoid automatic policy-changing actions without explicit approval.

## Learning Sidecar Service

The VM installs a user service:

- unit: `hermes-learning-sidecar.service`
- command: `python -m hermes_cli.main memory sidecar --interval 300`
- home: `/home/rakib/.hermes`
- repo: `/home/rakib/.hermes/hermes-agent`

The service keeps the learning loop active after SSH disconnects because user linger is enabled for `rakib`.

## Manual Checks

```bash
systemctl --user status hermes-learning-sidecar
hermes memory monitor --json
hermes memory sidecar --once --json
python3 - <<PY
import sqlite3
from pathlib import Path
conn = sqlite3.connect(Path.home() / ".hermes/state.db")
cur = conn.cursor()
for table in ["hermes_memory_records", "hermes_memory_evidence", "hermes_learning_runs", "hermes_meta_candidates"]:
    print(table, cur.execute("select count(*) from " + table).fetchone()[0])
PY
```

## Still Not Enforced

The full memory-wiki compiler and dreaming/DGM loop are not part of this enforcement pass. They remain separate follow-up work after the task outcome capture and learning sidecar are proven with the branch-118 validation test.
