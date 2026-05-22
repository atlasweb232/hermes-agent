# Production Runtime Closure Architecture

## Current Live Findings

The VM smoke proved that the runtime-learning framework is functional but not
yet production-grade:

- Claude Code is available and can answer a direct smoke prompt.
- Codex is installed and authenticated, but only works from a trusted repo path
  and is not on the default non-login/service `PATH`.
- Curator worked after switching from dead Ollama to Codex.
- Learning judge reviewed curator candidates and failed closed for weak
  evidence.
- Goal control ledger worked, but the model-backed goal judge returned
  `auxiliary client unavailable`.
- Runtime failures were captured, but some records lacked enough bounded
  metadata for confident automatic approval.
- A command capture path persisted secret-bearing command text before manual
  redaction; this must be blocked before persistence.
- Skill retrieval exists, but a failure-to-skill-candidate-to-approved-skill
  loop has not been proven live.

## Production Principle

Production-grade means every runtime path is deterministic, observable,
redacted, bounded, and fail-closed. It does not mean every sidecar runs a large
model. The platform should use:

- programmatic paths for exact memory hits, metadata classification, and
  redaction checks
- cheap reasoning for bounded summarization and extraction
- strong reasoning for curator, judge, and dreaming only when needed
- Codex for code-critical review, goal judge, or explicitly configured
  high-confidence tasks

## Control Flow

```text
worker/tool/goal event
  -> context admission gate
  -> worker event store / artifact ref
  -> bounded progress checkpoint
  -> secret-safe runtime capture
  -> typed memory/bus event
  -> sidecar budget and lease gate
  -> curator candidate
  -> learning judge decision
  -> operator approval boundary
  -> approved advisory memory / skill candidate / wiki claim
  -> scoped retrieval packet on next task
  -> outcome feedback and quality lifecycle
```

At no point may a raw transcript, raw command containing secrets, or unbounded
worker stream enter the supervisor context or persistent learning stores.

## Context Admission First

The immediate production problem is supervisor context bloat. Compression is a
safety valve, not the target operating mode. The supervisor should not need to
compress just because workers, sidecars, Slack mirrors, or Spec Kit reports
emitted verbose updates.

The first implementation slice should add:

- `hermes_cli/context_admission.py`
- `hermes_cli/worker_event_store.py`
- `hermes_cli/progress_checkpoint.py`

The admission gate decides whether an item is:

- admitted directly because it is small and decision-critical
- summarized into a checkpoint
- stored only with an event/artifact ref
- rejected from supervisor context

The worker event store preserves full detail for audit and UI. The progress
checkpoint gives the supervisor a compact view: current task, latest progress,
blocker, next action, validation refs, memory refs, and artifact refs. The
supervisor prompt should use the checkpoint and refs, not raw update streams.

This is the shortest path to reducing preflight compression frequency while
preserving traceability.

## Goal Judge Boundary

The goal judge is a continuation evaluator, not a completion authority. It can
return `continue`, `done`, `pause`, or degraded status, but the supervisor
ledger and deterministic validation gates decide whether the task is actually
complete.

If the configured `goal_judge` cannot be invoked from the active environment,
the response must be explicit:

```json
{
  "status": "degraded",
  "reason": "goal_judge_unavailable",
  "model_role": "goal_judge",
  "provider": "codex",
  "foreground_blocked": false
}
```

## Sidecar Deployment

Production sidecars should run as one of:

- systemd services with timers on a single VM
- containerized workers with leases in Azure Container Apps or Kubernetes
- scheduled one-shot jobs for low-frequency roles

Each sidecar must acquire a lock, check budget, process bounded work, publish
redacted job state, and exit or sleep without blocking foreground chat.

## Secret Safety

Secret scrub must run before persistence. Post-hoc redaction is not sufficient.
The redaction layer must protect:

- SQLite memory records
- SQLite evidence excerpts
- bus payloads
- DLQ records
- candidate payloads
- Slack/dashboard messages
- training corpus bundles
- object storage artifacts

The redaction test suite should seed provider-shaped values and assert they do
not appear in any persisted store.

## Skill Evolution

Skills are procedural memory, not policy. A skill may be created only from
approved memory/wiki evidence or from a curated skill candidate that passes
judge and operator approval. Runtime skill injection must be scoped by tenant,
repo, toolset, worker role, safety status, and context budget.

## Production Readiness Smoke

The final production smoke should run against the VM with:

- Claude as primary worker
- Codex as code-critical fallback and judge path
- curator and learning judge enabled
- sidecars in one-shot service-equivalent mode
- Slack urgent route configured
- feature flags explicit
- enforcement disabled

The smoke passes only when a live failure produces an advisory candidate,
judge decision, approval boundary, and useful follow-up memory or skill packet
without leaking secrets or blocking foreground runtime.

## Runtime Impact UI

The current operator dashboard work provides DTOs and seeded fixture tests, but
production closure requires live UI/API wiring. Operators need to answer one
question quickly: is runtime learning adding value or dragging the platform?

The runtime impact view should show:

- sidecars grouped by category and job
- live memory activity for each job
- foreground latency added by memory retrieval, allocator, validation, and
  notification paths
- background latency spent by curator, judge, dreaming, wiki, sync,
  housekeeping, corpus, and benchmark paths
- token and cost attribution by supervisor, worker, model, sidecar, memory
  retrieval, Slack/dashboard Ask, and deployment worker
- degraded or disabled reason for every sidecar
- whether each latency/cost item was foreground-blocking or asynchronous

The UI must remain bounded and lazy-loaded. The job list should show compact
rollups; job detail tabs should fetch sidecars, memory activity, and latency
attribution on demand. Raw logs, raw transcripts, provider logs, and secrets
must never be loaded by default.

This UI is part of production readiness because without it the operator cannot
prove that sidecars and memory retrieval are improving task convergence rather
than silently increasing latency, cost, or context bloat.
