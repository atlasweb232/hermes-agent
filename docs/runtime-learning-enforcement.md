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
- `hermes config tiers --json` returned the then-current `programmatic`,
  `low_cost_reasoning`, `balanced_reasoning`, and `strong_reasoning` names.
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

Training corpus export follows the MLOps remittance boundary in
[`lesser-model-mlops-architecture.md`](lesser-model-mlops-architecture.md)
and
[`specs/001-learning-memory-runtime/contracts/mlops-corpus-remittance.md`](../specs/001-learning-memory-runtime/contracts/mlops-corpus-remittance.md).
The runtime only collects, curates, exports, validates, and remits approved
corpus bundles. External MLOps owns fine-tuning, model registry entries,
evaluation gates, serving, and rollout, and corpus receipts do not change
runtime routes or enforcement policy.

Budget rule:

- Exact persisted lesson hit: programmatic only; no curator, judge, dreaming, or
  strong-model call by default.
- Near persisted lesson hit: cheap confirmation only if needed.
- Strong model: only for promotion, enforcement, contradiction, low confidence,
  or explicit operator request.
- Codex is reserved for code-critical review and is not the default cheap
  sidecar tier.

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

## Phase 11 Sidecar Tier Policy

Sidecar model selection is explicit in config and visible through JSON:

```bash
hermes config tiers --json
GET /api/model/tiers
GET /api/model/roles
```

Preferred top-level config shape:

```yaml
sidecar_tiers:
  programmatic:
    provider: none
    model: none
  cheap_reasoning:
    provider: cerebras
    model: gpt-oss-120b
    timeout_seconds: 60
    max_tokens: 2048
  strong_reasoning:
    provider: deepseek
    model: deepseek-reasoner
    timeout_seconds: 180
    max_tokens: 4096
  code_critical:
    provider: codex
    model: codex
    timeout_seconds: 300

sidecar_roles:
  progress_summarizer: cheap_reasoning
  classifier: programmatic
  extraction: cheap_reasoning
  curator: strong_reasoning
  learning_judge: strong_reasoning
  dreaming: strong_reasoning
  policy_review: strong_reasoning
  code_review_judge: code_critical
  training_corpus_review: strong_reasoning
```

Only provider and model names belong in sidecar config. Provider credentials
remain in the normal secret stores, never in `config.yaml`, docs, tests, or
logs. Existing `supervisor.sidecar_model_tiers` values are still read for
compatibility, but top-level `sidecar_tiers` wins.

The production routing policy is:

1. Programmatic retrieval runs first.
2. Exact persisted lesson matches suppress curator, judge, dreaming, and all
   other LLM-backed sidecars.
3. Near matches may use the cheap tier for bounded confirmation/extraction.
4. High-confidence non-promotion paths avoid the strong tier.
5. Low confidence, contradiction, promotion, or enforcement requests escalate
   to the strong judge/curator path.
6. Promotion and enforcement requests require both judge and operator approval;
   this slice records advisory approval only and does not enable enforcement.

## VM Phase 11A Persisted Lesson Smoke

VM persisted global lesson validation completed on 2026-05-17.

Deployment:

- VM host: `52.4.43.41`
- VM repo: `/home/rakib/.hermes/hermes-agent`
- Branch: `132-learning-memory-runtime`
- Commit deployed: `7e7e3434f`
- Runtime version after editable reinstall: `Hermes Agent v0.14.0 (2026.5.16)`

Smoke sequence:

1. Persisted the Claude router repair lesson through CLI:
   `hermes memory global lesson add --lesson-json ... --json`
2. Retrieved the lesson from durable SQLite global memory:
   `hermes memory global retrieve --event-json ... --json`
3. Hydrated task memory:
   `hermes memory global hydrate --event-json ... --json`
4. Ran curator policy pass:
   `hermes curator policy-run --json`
5. Ran learning sidecar once and monitor checks.

Results:

- Global lesson `global-claude-router-repair` was stored durably.
- Retrieval returned `exact_matches=1`, `returned=1`, and no rejected rows.
- Hydration materialized one local hot-cache entry:
  `ghot_b43927edc0c39ee8`.
- Hydrated packet included one compact advisory item:
  prefer direct `claude --model sonnet -p` after `worker-router claude`
  failures.
- Curator policy pass scanned one runtime routing lesson and skipped it:
  `records_skipped=1`, `global_lesson_hit=1`, `candidates_created=0`.
- This proves persisted memory suppressed an expensive curator path without a
  strong-model call.
- `hermes memory sidecar --once --json` completed.
- `hermes memory monitor --json` remained `healthy`.

Remaining validation:

- Run an actual fresh `hermes chat`/worker task and verify the supervisor
  receives the hydrated advisory packet before attempting the old command loop.

## SQLite Learning Bus Audit And Drain

T128 added local-only audit and drain surfaces for the SQLite learning event
bus before any Kafka/Redpanda work:

```bash
python3 -m hermes_cli.main memory bus audit --json
python3 -m hermes_cli.main memory bus drain --consumer audit --drain-key smoke-1 --limit 1 --json
```

The audit output reports bounded metadata only. Samples include event ids,
topics, tenant/repo/task scope, attempt and lease metadata, timestamps,
`event_key_present`, `lease_expired`, `payload_redacted`, payload byte size,
and payload key count. It does not emit `payload_json`, raw transcripts, raw
logs, API keys, tokens, passwords, or payload values.

Replay safety is explicit in the JSON:

- expired `leased` rows are counted as replayable;
- `consumed` and `dead` rows are counted as non-replayable;
- rows with event idempotency keys are counted without exposing the key value;
- `drain` records `(drain_key, event_id)` in SQLite so repeating the same
  drain key returns `already_drained` metadata instead of leasing or acking the
  same event again.

Dedicated consumer sidecar conclusion: a dedicated local consumer sidecar is
recommended before Kafka/Redpanda when durable queued backlog or replayable
expired leases exist, or when multi-instance operation would otherwise depend
on repeated manual drains. For single-node/dev with no queued or replayable
backlog, manual CLI drain or a local sidecar remains sufficient. The same
conclusion is exposed as `dedicated_consumer_sidecar_required` and
`dedicated_consumer_sidecar_reason` in `memory bus audit --json`.

## VM Phase 11A Live Failure-Learn Smoke

Live validation completed after deploying branch `132-learning-memory-runtime`
at `2907255f1`.

Sequence:

1. Restarted the learning sidecar on the VM.
2. Persisted approved global lesson `global-claude-router-repair` into the
   configured SQLite global memory backend.
3. Retrieved the lesson through `hermes memory global retrieve --event-json`.
4. Hydrated task memory through `hermes memory global hydrate --event-json`.
5. Ran a fresh one-shot Hermes task asking Claude Code for `two plus two`.

Observed result:

- Durable retrieval returned one exact match.
- Hydration materialized one hot-cache entry and one compact advisory item.
- The fresh task returned `4`.
- Session evidence showed the supervisor used direct Claude Code invocation:
  `claude -p "What is two plus two? Reply with only the answer." --model sonnet --max-turns 1`.
- The fresh task did not call `worker-router claude`, avoiding the previously
  observed bad command loop.

Caveat:

- The live prompt explicitly said to use learning memory. The next stricter
  acceptance test should prove the same behavior from automatic task-start
  memory hydration without that hint.

## Automatic Task-Start Memory Injection

Implemented on branch `132-learning-memory-runtime`.

Plain `hermes chat` now builds an ephemeral runtime memory packet for the
current user turn before the first model call. The packet is generated
programmatically from the user message, tenant/repo metadata, and approved
global lessons:

```text
user turn
  -> infer_runtime_memory_event(...)
  -> local hot-cache lookup
  -> approved global exact/simhash/metadata-lexical retrieval
  -> bounded advisory packet
  -> append to current API user message only
```

The injected block is advisory-only and is not written into the persisted
conversation history or cached system prompt. Explicit user instructions, git,
tests, logs, and runtime evidence remain more authoritative than memory.

Current acceptance coverage:

- `tests/hermes_cli/test_runtime_memory_injection.py` proves Claude Code task
  prompts retrieve the approved Claude router lesson without the user saying
  "use memory".
- `tests/hermes_cli/test_global_memory.py` proves metadata + lexical fallback
  can retrieve a high-confidence command-repair lesson when no exact failure
  signature is present in the user prompt.

VM live smoke for the no-hint path remains pending.

## Runtime Worker Degradation Gate

Implemented after the Claude Code smoke test showed a broader issue: the final
answer was correct, but the worker route timed out/failed and the supervisor
still described the worker run as successful.

The fix is generic, not Claude-specific:

- terminal outcomes are classified as `success`, `failed`, `timed_out`, or
  `empty_output`
- worker-like command families are tracked across the turn
- if the latest worker command is degraded and no later worker command succeeds,
  the final response must disclose that the answer is supervisor fallback
- foreground worker commands get a configurable default timeout cap so degraded
  workers do not pin the whole environment

This is disclosure enforcement only. Policy-driven command blocking/rewrite and
automatic worker reallocation remain future work behind judge/operator approval.

## Phase 11A Cost/Value JSON Observability

Implemented deterministic JSON reporting through:

```bash
hermes memory global value --event-json ... --tool-events-json ... --json
```

The report includes:

- `memory_hits`
- `global_lesson_hits`
- `global_lesson_near_hits`
- `global_lesson_misses`
- `hot_cache_hits`
- `skipped_curator_count`
- `skipped_dreaming_count`
- `estimated_packet_tokens`
- `repeated_error_count`
- `tool_error_count`
- `worker_model`
- `worker_provider`
- `outcome`
- `memory_effect`
- `validation_complete`

This path is programmatic. It calls persisted retrieval, pre-curation, and
hydration, but it does not call curator, judge, dreaming, or any other
LLM-backed sidecar on exact approved lesson hits.

## Phase 11 T115 Deterministic VM/Local Smoke

T115 validation completed on branch `132-learning-memory-runtime` at HEAD
`b7cb99dc` before this documentation update. The run used isolated
`HERMES_HOME` and artifact roots under `/tmp`, ran no destructive commands,
stored no provider secrets or raw transcripts, and kept enforcement disabled
and advisory-only throughout.

This was an Azure VM/local deterministic fixture smoke, not a live
provider/Azure benchmark. Live Azure smoke remained skipped because
`AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_VM_NAME`, and explicit
live-smoke opt-in were missing.

Selected model tiers:

- `programmatic`: provider `none`, model `none`, `allow_llm=false`, timeout
  60s.
- `cheap_reasoning`: provider `cerebras`, model `gpt-oss-120b`,
  `allow_llm=true`, timeout 60s, `max_tokens=2048`.
- `strong_reasoning`: provider `deepseek`, model `deepseek-reasoner`,
  `allow_llm=true`, timeout 180s, `max_tokens=4096`.
- `code_critical`: provider `codex`, model `codex`, `allow_llm=true`, timeout
  300s.

Role mapping:

- `classifier` -> `programmatic`
- `extraction` -> `cheap_reasoning`
- `progress_summarizer` -> `cheap_reasoning`
- `curator` -> `strong_reasoning`
- `learning_judge` -> `strong_reasoning`
- `dreaming` -> `strong_reasoning`
- `policy_review` -> `strong_reasoning`
- `code_review_judge` -> `code_critical`
- `training_corpus_review` -> `strong_reasoning`

Smoke sequence and outcomes:

- `python3 -m hermes_cli.main config tiers --json` exited 0 in 568.02 ms and
  confirmed the tier and role routing above.
- `runtime features status --tenant-id t115-tenant --repo-id hermes-agent --json`
  exited 0 in 932.49 ms.
- Baseline `runtime task init` without a memory packet exited 0 in 737.22 ms.
- A deterministic approved global lesson fixture was added with
  `memory global lesson add`, exiting 0 in 729.6 ms.
- Exact `memory global retrieve` exited 0 in 726.26 ms and returned
  `lesson_count=1`.
- Exact `memory global hydrate` exited 0 in 726.24 ms and returned
  `global_lessons=1`, `estimated_tokens=33`. The LLM sidecar was skipped
  because the exact persisted lesson match used the programmatic no-LLM path.
- Memory-assisted `runtime task init` exited 0 in 941.2 ms.
- `memory sidecar --once --json` exited 0 in 733.86 ms.
- `hermes curator status` exited 0 in 534.91 ms.
- `memory judge-run --json` exited 0 in 740.68 ms.
- `memory dream status --json` exited 0 in 724.41 ms.
- `runtime e2e run --suite runtime.local_smoke ... --json` first returned
  `skipped` with default feature gates. After scoped overrides for
  `t115-tenant`/`hermes-agent` enabled `runtime.health_sidecar`,
  `runtime.restart_recovery`, `runtime.task_graph`, and
  `runtime.benchmark_harness` with `enforcement_allowed=false`, the same suite
  exited 0 in 748.3 ms with status `passed` and all four cases passed.
- `runtime smoke compare --no-upstream --json` exited 0 in 1941.74 ms with
  status `passed`, `repeated_failed_loop_result=passed`,
  `foreground_elapsed_seconds=0.042714085`, and
  `expensive_sidecar_called=false`.
- Deterministic fixture `runtime benchmark run --execution-mode fixture
  --urgent-dry-run --json` exited 0 in 728.17 ms.
- `runtime benchmark report --run-id ... --json` exited 0 in 731.37 ms. The
  deterministic production gate allowed the fixture run.
- `runtime benchmark azure-smoke --json` exited 0 with status `skipped` for
  the live Azure blockers listed above; deterministic fixture status was
  `passed`.
- `runtime costs status --json` exited 0 with `run_count=1`,
  `total_estimated_cost_usd=0.038`, `total_prompt_tokens=189`,
  `total_completion_tokens=198`, and production gate `allowed=true`.

Deterministic benchmark metrics:

- Quality: upstream `success_rate=1.0`, `validation_pass_rate=1.0`,
  `false_completion_rate=1.0`, `repeated_error_rate=2.0`; branch
  `success_rate=1.0`, `validation_pass_rate=1.0`,
  `false_completion_rate=0.0`, `repeated_error_rate=0.0`.
- Cost: upstream `estimated_cost_usd=0.02`; branch
  `estimated_cost_usd=0.018`; `cost_per_success_ratio=0.90`.
- Latency: upstream `avg_latency_ms=1000.0`; branch `avg_latency_ms=900.0`;
  `foreground_latency_ratio=0.90`; branch `sidecar_wall_ms=40.0`.
- Self-learning: upstream `memory_hit_rate=0.0`; branch
  `memory_hit_rate=1.0`, `memory_helpful=1`, `memory_harmful=0`,
  `sidecar_cost_usd=0.002`, `sidecar_blocked_foreground=false`,
  `urgent_alerts_expected=0`, and `urgent_alerts_sent=0`.

Result:

- No regressions were observed in the deterministic fixture.
- The branch reduced repeated errors and false completions in the fixture while
  preserving success and validation pass rates.
- Sidecars did not block foreground work, and exact persisted memory hits used
  the programmatic path instead of an LLM sidecar.
- Live provider/Azure results are not claimed here; they remain blocked until
  the required Azure config and explicit live-smoke opt-in are present.

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
