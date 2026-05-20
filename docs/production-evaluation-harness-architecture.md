# Production Evaluation Harness Architecture

## Goal

The platform should not be productionized because it looks better in one chat.
It must show measurable improvement against upstream Hermes over longer task
horizons with controlled workloads, identical repositories, comparable models,
and full cost/latency/quality telemetry.

Tenant onboarding smoke and deployment packet shapes are defined in
[`specs/001-learning-memory-runtime/contracts/tenant-onboarding.md`](../specs/001-learning-memory-runtime/contracts/tenant-onboarding.md).
Harness workloads that exercise tenant onboarding should report statuses and
evidence refs for repo access, connector routing, toolsets, budgets, runtime
cell isolation, and CI/CD packets without storing raw transcripts or secrets.

## Architecture

```text
benchmark workload suite
  -> upstream Hermes environment
  -> branch Hermes environment
  -> shared repo snapshots / worktrees
  -> telemetry collector
  -> artifact store
  -> sidecar/judge/memory verifier
  -> comparison report
  -> production readiness gate
```

## Environment Isolation

Use separate homes and workspaces:

```text
~/.hermes-eval/upstream
~/.hermes-eval/branch
/srv/hermes-eval/workloads
/srv/hermes-eval/artifacts
```

Both environments receive the same task prompt and repo snapshot. The branch
environment may use memory, allocator, sidecars, judge, and context gate. The
upstream environment is the control.

## Message Bus And Storage

The first implementation should use a local durable bus because it is cheap and
easy to debug:

```text
runtime event
  -> SQLite event bus
  -> artifact file/object ref for raw streams
  -> sidecar consumers
  -> compact telemetry rows
```

Production scale can replace the transport without changing the supervisor
contract:

```text
SQLite bus -> Redpanda/Kafka
artifact files -> Azure Blob/S3
analytics rows -> Delta Lake/Parquet
approved memory -> lexical/vector/graph indexes
```

Raw transcripts and worker streams are stored for analysis, not supervisor
context. Supervisor receives compact decision packets only.

## Cost And Context Telemetry

Every path emits token/cost/latency attribution:

- supervisor
- planner
- worker
- judge
- curator
- dreaming
- memory retrieval
- progress summarizer
- Slack/dashboard analysis
- QA/test workers

Metrics are recorded per model, provider, task, session, workload, tenant, and
repo. If provider token counts are unavailable, deterministic estimates are
stored with `estimated=true`.

The runtime observability DTOs surface those fields without requiring a full
dashboard. `hermes memory observe list --json` provides active/historical job
rows with worker/model metadata, completion and blocker state, Spec Kit and
architecture refs, memory refs, and cost/latency summaries. Operators can filter
by tenant, repo, date window, worker id/status, status, completion status, and
blocker text, then drill into a line item by id, job id, or task id. Scoped Ask
is deterministic by default and summarizes only persisted metadata with
citations and `llm_calls=[]`; raw transcripts, secrets, tokens, and provider
logs stay out of observability payloads.

## Sidecar Verification

The harness must prove that sidecars add value without dragging the runtime:

- learning rollup produced candidates from evidence
- judge reviewed candidates fail-closed
- memory wiki only used approved evidence
- dreaming remained proposal-only
- progress summarizer stayed low-cost and non-blocking
- health sidecar emitted recovery packets for stale/no-progress work
- urgent Slack alert fired for blocked/degraded/fallback-exhausted states

Dreaming checks should reference
[`dreaming-integration-architecture.md`](./dreaming-integration-architecture.md)
and the
[`dreaming-integration.md`](../specs/001-learning-memory-runtime/contracts/dreaming-integration.md)
contract for proposal schema, local/global evidence filtering, and validator
outputs.

MLOps corpus checks should reference
[`lesser-model-mlops-architecture.md`](lesser-model-mlops-architecture.md)
and
[`mlops-corpus-remittance.md`](../specs/001-learning-memory-runtime/contracts/mlops-corpus-remittance.md).
The harness may validate corpus bundle quality, redaction, approval provenance,
remittance receipts, and external training hints. It must not treat a remitted
bundle as a Hermes-owned fine-tune job, model registry entry, deployment gate,
serving change, or rollout decision.

## Multi-Agent And QA Toolsets

Long-horizon workloads should include agent clusters, not only single worker
tasks:

- planner agent
- implementation workers
- QA/test worker
- reviewer/judge
- deployment/smoke worker
- memory/curation sidecars

Each worker gets a bounded toolset and owned paths. The supervisor owns task
graph state, validation, final reporting, and human-in-the-loop gates.

## Benchmark Output

Each benchmark run produces:

- `run.json`
- per-task telemetry JSONL
- artifact refs
- cost summary
- latency summary
- memory-hit summary
- sidecar activity summary
- validation evidence
- upstream-vs-branch comparison
- production gate result

The report must answer:

- Did the branch complete more tasks?
- Did it reduce repeated mistakes?
- Did memory reduce token use or prevent known failures?
- Did sidecars stay out of the foreground path?
- Did cost remain within budget?
- Did humans receive timely alerts when needed?

## Production Gate

Production rollout requires a benchmark pack with stable results over multiple
task classes, not a single smoke test.

Minimum gate:

- success rate not worse than upstream
- false completion lower than upstream
- repeated error signatures lower than upstream
- context admitted to supervisor bounded by policy
- sidecar overhead below budget
- urgent alerts reliable
- no memory promotion without judge/operator approval
