# Production Evaluation Harness Contract

## Purpose

Hermes must prove that the memory framework, sidecars, judges, allocator, and
self-learning loop improve real task outcomes before production rollout. The
evaluation must compare a clean upstream Hermes environment against the
`132-learning-memory-runtime` branch under the same workloads, tools, budgets,
and model mix.

This contract defines the minimum side-by-side harness.

## Environments

### Upstream Control

- Fresh upstream Hermes checkout.
- Separate `HERMES_HOME`.
- Same OS, CPU, memory, network, and repo worktrees as the branch environment.
- Same model credentials and tool availability where possible.
- Learning/memory extensions disabled unless upstream provides equivalent
  behavior natively.

### Branch Treatment

- `132-learning-memory-runtime`.
- Separate `HERMES_HOME`.
- Memory framework, event bus, allocator, sidecars, judge, and context gate
  enabled according to test profile.
- Same workload prompts and repo snapshots as upstream.

## Workload Classes

The harness must support at least:

- branch inspection and review
- implementation with Spec Kit artifacts
- failing primary worker with fallback
- long-running goal continuation
- stale worker/no heartbeat
- repeated tool failure
- hallucinated success / empty worker output
- multi-repo task decomposition
- QA/test generation and validation
- deployment/smoke-test task

Each workload has:

- `workload_id`
- repo snapshot refs
- branch refs
- task prompt
- expected artifacts
- expected validation commands
- allowed workers/tools
- model budget profile
- pass/fail rubric

## Telemetry Requirements

Every task turn, worker attempt, sidecar run, and judge run must emit telemetry:

- environment: `upstream` or `branch`
- session id
- task id
- workload id
- tenant/repo ids
- model/provider/worker role
- prompt tokens
- completion tokens
- cached/input/output tokens if available
- estimated cost
- wall-clock latency
- queue/wait latency
- context bytes/tokens admitted to supervisor
- raw bytes stored out-of-context
- memory packet ids injected
- sidecars triggered/skipped
- judge decisions
- worker attempts and fallback reasons
- validation result
- operator intervention count
- Slack/dashboard notification count

If a provider does not expose token usage, the harness records a deterministic
estimate and labels it `estimated=true`.

## Memory And Sidecar Assertions

For branch runs, the harness must assert:

- raw worker streams were stored as artifacts, not injected into supervisor
  context
- compact progress packets were admitted only at decision boundaries
- approved memory retrieval ran before worker dispatch
- learning candidates were produced only from evidence-backed events
- judge decisions were recorded separately from candidates
- no candidate became approved memory without judge/operator gates
- dreaming proposals were proposal-only
- sidecars did not block foreground work
- urgent Slack notification fired on blocked/degraded/fallback-exhausted states

## Quality Metrics

The harness must compare:

- task success rate
- validation pass rate
- time to first useful artifact
- time to completion
- number of repeated errors
- number of hallucinated/false completions
- number of worker reallocations
- number of operator interventions
- token/cost per successful task
- supervisor context growth per task
- memory hit rate
- memory helpful/ignored/harmful feedback
- sidecar overhead as percentage of task wall time and cost

## Pass Gate

The branch is production-eligible only if, over the selected workload suite:

- branch task success rate is equal or higher than upstream
- branch false-completion rate is lower than upstream
- branch repeated-error rate is lower than upstream
- branch cost per successful task is not worse than configured threshold
- branch foreground latency is not worse than configured threshold
- no sidecar blocks foreground execution
- urgent alerts fire for all blocked/degraded/fallback-exhausted tasks
- memory/judge approvals preserve audit separation

## Storage

Initial implementation may use local SQLite plus artifact files.

Production-scale storage must support pluggable backends:

- local filesystem for raw artifacts
- Azure Blob/S3-compatible object storage for raw events and transcripts
- Delta Lake or parquet-compatible tables for analytic telemetry
- lexical/vector/graph indexes for approved knowledge only
- optional Kafka/Redpanda-compatible bus for multi-instance deployments

The supervisor contract must not depend on the storage backend.

## Human-In-The-Loop

Operator approval is required for:

- enabling enforcement policy
- promoting cross-tenant/global lessons
- exporting training/evaluation corpora
- continuing after budget exhaustion
- overriding failed validation

The harness records operator decisions as first-class evidence.
