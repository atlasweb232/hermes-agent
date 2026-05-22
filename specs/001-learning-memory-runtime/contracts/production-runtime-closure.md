# Production Runtime Closure Contract

## Purpose

Close the remaining production-readiness gaps discovered during live VM smoke:
secret-bearing command capture, model-role invocation drift, manual-only sidecar
operation, sparse runtime-failure evidence, unproven skill evolution, and
unproven goal-judge model execution.

This contract is intentionally narrower than the broader platform-hardening
phase. It converts the current live blockers into executable tests and
implementation tasks that must pass before the runtime-learning branch can be
treated as production-grade.

## Non-Goals

- Do not enable enforcement by default.
- Do not auto-promote memory, skills, policies, or dreaming proposals.
- Do not add a second autonomous loop beyond the existing sidecar and goal
  mechanisms.
- Do not store raw credentials, raw provider responses, raw transcripts, or
  unbounded command logs.
- Do not make Codex the default worker for all sidecar work; Codex remains
  reserved for code-critical review, goal judge, or explicitly configured
  strong-role paths.

## Required Production Gates

### Secret-Safe Runtime Capture

Every runtime-learning write path must sanitize before persistence. This
includes:

- supervisor command capture
- delegated worker failure capture
- allocator failure capture
- tool-result evidence excerpts
- sidecar/job summaries
- memory candidates
- bus events and DLQ records

Any secret-like value must be redacted before writing to SQLite, object storage,
bus payloads, Slack, dashboard DTOs, training corpus bundles, or archived
artifacts.

### Service-Resolved Model Roles

Model roles must resolve the same way under:

- interactive shell
- SSH non-login command
- Hermes gateway service
- sidecar service
- one-shot CLI
- scheduled task

The resolver must expose:

- effective binary path or provider transport
- configured provider/model/tier
- timeout and budget
- authentication readiness without printing secrets
- degraded reason if unavailable

### Goal Judge Model Invocation

`/goal` and `hermes runtime control goal` must invoke the configured
`goal_judge` model role when enabled. If the auxiliary client is unavailable,
the result must be reported as degraded with a structured reason and must not
be mistaken for a successful model-backed judgment.

Goal judge decisions cannot complete supervisor tasks directly. Completion
still requires deterministic validation evidence and supervisor ledger state.

### Sidecar Service Operation

Production sidecars must be runnable as bounded services or scheduled one-shot
jobs. Each sidecar must have:

- feature flag
- interval
- lease/lock
- max runtime
- budget check
- backlog limit
- redacted status
- last success/failure state
- non-blocking foreground behavior

### Rich Runtime Failure Evidence

`supervisor_runtime_failure` records must include enough bounded metadata for
curator and judge decisions:

- task id
- tenant id and repo id when known
- worker id and worker family when known
- requested route and actual route
- command family
- status classification
- timeout/latency budget
- allocation/attempt ids when applicable
- validation mismatch summary
- redacted evidence refs
- bounded output/error excerpts after secret scrub

Sparse records may still be stored, but curator output must classify them as
insufficient evidence and avoid creating reusable lessons except as
needs-human diagnostics.

### Skill Evolution Loop

The skill pipeline must prove one production-grade loop:

1. Runtime failure or approved memory identifies repeatable procedure.
2. Curator proposes skill candidate or skill repair candidate.
3. Learning judge reviews fail-closed.
4. Operator approval gates publication.
5. Runtime skill search retrieves only scoped approved skill metadata.
6. Worker receives bounded skill packet.
7. Outcome feedback marks skill helpful, irrelevant, harmful, or unknown.
8. Harmful feedback demotes or repairs the skill version.

### End-To-End Learning Loop

The production smoke must exercise:

1. Claude primary worker healthy path.
2. Claude degraded/timeout/empty path.
3. Codex fallback or code-critical path.
4. Runtime failure capture.
5. Curator candidate creation.
6. Learning judge decision.
7. Operator approval boundary.
8. Advisory memory/skill packet retrieval on a follow-up task.
9. Slack/dashboard notification for blocked or degraded work.
10. Cost/context telemetry showing sidecars did not block foreground runtime.

## Required CLI/API Surfaces

- `hermes runtime production-smoke --json`
- `hermes runtime model-roles doctor --json`
- `hermes runtime sidecars status --json`
- `hermes runtime sidecars run --role <role> --once --json`
- `hermes runtime redaction audit --json`
- `hermes runtime learning-loop smoke --json`
- `hermes skills runtime e2e --json`

The exact command names may be adjusted during implementation, but the final
surfaces must expose equivalent JSON for tests, dashboard, and operator use.

## Pass/Fail Criteria

Production closure passes only when:

- no secret-like values are persisted in runtime-learning stores during tests
- `goal_judge` successfully invokes the configured model role or reports a
  structured degraded result
- curator and learning judge can run from service-equivalent environment
- sidecars can run one-shot and expose service-ready status
- runtime failure records have bounded useful metadata
- skill evolution E2E passes with approval gates intact
- learning-loop E2E proves follow-up task injection
- all high-risk actions remain advisory or approval-gated
- foreground runtime never waits on long-running sidecar work

