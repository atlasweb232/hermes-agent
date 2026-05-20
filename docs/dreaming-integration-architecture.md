# Dreaming Integration Architecture

## Purpose

Dreaming is offline synthesis over approved evidence. It looks for patterns,
gaps, repeated failures, missing tests, missing skills, and architecture
improvements. It must remain proposal-only until judge and operator gates
convert its output into approved memory, wiki updates, skill candidates, test
tasks, goals, or policy candidates.

This document updates the original dreaming design for tenant runtime cells,
global memory, SkillClaw/skills, CI/CD automation, and E2E testing.

## Non-Negotiable Rule

Dreaming cannot directly mutate live runtime state.

Dreaming must not directly:

- inject prompts
- approve memory
- publish skills
- update wiki claims
- change config
- create or resume goals
- rewrite routing
- enforce policy
- export training data
- edit repos
- deploy code

It can only produce proposals.

## Inputs

Dreaming input is evidence-only:

- approved memory
- memory wiki claims
- runtime failure summaries
- task outcome summaries
- validation reports
- policy audit records
- worker health aggregates
- skill outcome feedback
- skill gap candidates
- CI/CD failure summaries
- E2E test reports
- cost/context telemetry summaries

Inputs must exclude:

- raw secrets
- raw full transcripts
- unbounded logs
- unapproved private cross-tenant evidence
- speculative dreaming proposals as sole evidence

## Outputs

Dreaming proposal types:

- `skill_candidate`
- `skill_repair`
- `test_gap`
- `ci_cd_hardening`
- `memory_wiki_update`
- `routing_improvement`
- `allocator_policy_candidate`
- `observability_gap`
- `tenant_onboarding_improvement`
- `toolset_recommendation`
- `cost_optimization`
- `training_corpus_candidate`
- `architecture_review_item`

Every proposal must include:

- proposal id
- tenant/repo/scope
- proposal type
- summary
- rationale
- evidence refs
- risk level
- expected benefit
- affected feature ids
- required approval path
- forbidden direct actions
- suggested validation

## Local Dreaming

Local dreaming runs inside or near a tenant runtime cell.

Scope:

- tenant
- repo
- device/runtime cell
- configured toolsets
- current memory/wiki/task outcomes

Use local dreaming for:

- repo-specific skill gaps
- tenant-specific CI/CD hardening
- repeated worker failure patterns
- missing validation tests
- tenant onboarding friction
- local cost/context optimization

Local dreaming cannot publish globally.

## Global Dreaming

Global dreaming runs over redacted approved global memory/wiki records only.

Scope:

- global/domain approved lessons
- redacted cross-tenant patterns
- shareability-approved memory
- aggregate telemetry

Use global dreaming for:

- cross-tenant skill candidates
- broad CI/CD playbooks
- common failure repair proposals
- toolset templates
- global benchmark improvements
- training corpus candidates

Global dreaming cannot read tenant-private raw evidence.

## Triggering

Dreaming should be service-driven by default and manually triggerable for
testing.

Triggers:

- sidecar interval due
- enough new approved memory/wiki records
- repeated failure threshold crossed
- skill harmful feedback threshold crossed
- E2E feature test gap detected
- CI/CD failure cluster detected
- operator manual command

Manual command remains for smoke and operator runs:

```bash
hermes memory dream run --json
```

Production sidecar trigger:

```text
learning sidecar tick
  -> rollup
  -> monitor
  -> policy audit
  -> housekeeping
  -> dreaming if enabled and due
```

Dreaming runs out of band. Foreground chat, delegation, terminal, and goal
continuation must never wait on dreaming.

## Approval Flow

```text
dreaming proposal
  -> deterministic validator
  -> judge review
  -> operator or tenant-admin approval
  -> converted candidate
  -> validation
  -> approved memory / wiki update / skill candidate / test task / policy candidate
  -> retrieval or future execution
```

Conversion targets:

- approved memory candidate
- memory wiki update candidate
- skill candidate
- test backlog item
- Spec Kit task
- CI/CD hardening task
- policy audit candidate
- routing/allocator advisory
- training corpus candidate

No conversion target may bypass its own validation path.

## Skill Integration

Dreaming may propose:

- new skills from repeated successful workflows
- skill repairs from harmful feedback
- skill retirement from stale or harmful usage
- skill split/merge from duplicate patterns
- role-specific skill packets for planner, worker, QA, browser, CI/CD, or
  deployment workers

Dreaming does not write `SKILL.md` directly. A skill compiler or SkillClaw
adapter may turn approved proposals into skill candidates.

Skill candidate conversion must follow
[`skill-memory-pipeline-architecture.md`](./skill-memory-pipeline-architecture.md)
and
[`../specs/001-learning-memory-runtime/contracts/skill-memory-pipeline.md`](../specs/001-learning-memory-runtime/contracts/skill-memory-pipeline.md).

## CI/CD And Test Integration

Dreaming may propose:

- missing CI workflow stages
- smoke tests
- rollback steps
- artifact publishing
- protected environment approval steps
- test fixtures for recurring failures
- E2E feature test cases
- benchmark workload additions

CI/CD proposals become Spec Kit tasks or toolset tasks only after approval.

## Tenant Dashboard

Dashboard should expose:

- proposals by tenant/repo/type/status/risk
- evidence refs
- expected benefit
- cost estimate
- required approval
- conversion target
- judge decision
- operator action history

Tenant admins see tenant-scope proposals. Global admins see global proposals
and tenant proposals only according to policy.

## Feature Toggles

Required toggles:

- `supervisor.features.dreaming`
- `supervisor.dreaming.enabled`
- `supervisor.dreaming.local.enabled`
- `supervisor.dreaming.global.enabled`
- `supervisor.dreaming.allow_skill_candidates`
- `supervisor.dreaming.allow_ci_cd_proposals`
- `supervisor.dreaming.allow_test_gap_proposals`
- `supervisor.dreaming.require_judge`
- `supervisor.dreaming.require_operator_approval`

Defaults:

- disabled unless configured
- proposal-only
- judge required
- operator approval required
- no direct runtime mutation

## E2E Requirements

Minimum E2E tests:

- local dreaming creates tenant-scoped skill gap proposal only
- global dreaming reads only redacted approved shareable memory
- dreaming proposal cannot enter prompt injection
- dreaming proposal cannot publish skill directly
- dreaming proposal cannot update config or queue goal
- dreaming proposal can become a skill candidate only after judge/operator gates
- dreaming can propose CI/CD test hardening task without editing repo
- dashboard lists proposal evidence and approval state
- disabling dreaming records skipped-by-toggle and produces no proposal

## Failure Modes

Dreaming failures should be recorded but non-blocking:

- provider timeout
- malformed output
- missing evidence refs
- unsupported scope broadening
- secret leakage
- duplicate proposal
- destructive command suggestion
- direct enforcement request
- direct skill/wiki/config mutation request

Any of these should fail closed and record a rejected/invalid proposal or job
failure.
