# Skill And Memory Pipeline Architecture

## Purpose

Hermes memory records what happened and what was learned. Skills define how an
agent should perform a recurring class of work. The platform needs both:

- memory for evidence, retrieval, audit, and learning provenance
- skills for reusable procedural execution patterns

SkillClaw is relevant as a skill evolution and distribution layer, but it should
sit downstream of the Hermes memory framework rather than replace it.

## Definitions

### Memory

Evidence-backed knowledge derived from runtime:

- raw runtime events
- task outcomes
- runtime failures
- curator candidates
- judge decisions
- approved memory
- memory wiki claims
- dreaming proposals
- policy audits
- retrieval packets

Memory answers: what happened, why it matters, where it applies, and what
evidence supports it.

### Skill

A reusable procedural artifact, usually `SKILL.md` plus optional files, that
tells an agent how to perform a task pattern.

Skills answer: when doing this class of work, what process, tools, commands,
constraints, validation, and failure handling should the agent follow.

### SkillClaw Role

SkillClaw can:

- manage skill libraries
- intercept sessions through a proxy
- record session artifacts
- deduplicate and evolve skills
- publish skills to local/shared storage
- validate skill candidates before publishing
- distribute skill updates across agents/devices/teams

In Hermes, SkillClaw should be treated as a skill compiler/evolver, not the
source of truth for memory or policy.

## Pipeline

Default invocation path:

```text
user request
  -> tenant connector
  -> supervisor task packet
  -> task classifier
  -> memory retrieval
  -> skill retrieval
  -> supervisor initialization
  -> planner / Spec Kit creator
  -> worker dispatch with bounded skills
  -> validation
  -> outcome feedback
  -> memory candidate
  -> judge/operator approval
  -> approved memory / wiki
  -> skill candidate
  -> skill validation
  -> tenant/global skill library
```

Skills should be selected before planner/worker dispatch, not injected
randomly mid-task.

## Skill Retrieval

Skill retrieval uses the same task classifier metadata as memory retrieval:

- tenant
- repo
- task type
- toolset
- worker role
- language/framework
- platform
- error signature
- success signature
- security/sensitivity level
- scope: user, device, repo, tenant, domain, global

Hard filters run before semantic matching:

- tenant visibility
- repo visibility
- tool compatibility
- role compatibility
- approval status
- safety status
- enabled feature flags

Only compact skill summaries or selected skill sections should enter supervisor
context. Full skill files may be referenced by workers or loaded into worker
context when needed.

## Injection Points

### Supervisor Initialization

The supervisor receives:

- top relevant skill summaries
- skill ids and versions
- why each skill matched
- confidence and scope
- required validation hooks

The supervisor does not receive the full skill library.

### Planner / Spec Kit Creator

Planner may receive planning skills such as:

- Spec Kit planning
- repo gap analysis
- migration planning
- CI/CD design
- tenant onboarding design

### Implementation Worker

Worker receives task-relevant execution skills such as:

- Azure Container Apps deploy
- GitHub Actions workflow creation
- TinyFish browser QA
- desktop chat/voice validation
- Claude Code/Codex worker invocation

### QA / Browser / Deployment Workers

Specialized workers receive only their role-specific skills.

## Skill Authority

Skills are advisory execution aids. They never outrank:

1. explicit user/operator instruction
2. tenant security policy
3. repo protection policy
4. current git/test/runtime evidence
5. supervisor validation gates
6. judge/operator approval requirements

Skills cannot:

- approve memory
- enable enforcement
- bypass protected branches
- expose secrets
- override tenant boundaries
- mark tasks complete without validation

## Evolution Flow

Skill evolution should be gated:

1. runtime evidence accumulates
2. curator proposes lesson
3. judge reviews candidate
4. operator or tenant policy approves
5. memory/wiki record is promoted
6. skill compiler proposes skill candidate
7. skill validator runs deterministic or sandboxed tests
8. skill candidate is published to tenant library
9. retrieval stats and outcome feedback update confidence

Direct raw transcript to skill publishing is not allowed.

## Tenant And Global Skill Libraries

Each tenant has a private skill library.

Allowed scopes:

- user
- device
- repo
- tenant
- domain
- global

Global skills require:

- redaction
- judge approval
- operator approval
- cross-tenant shareability metadata
- validation evidence
- version history
- rollback path

## Skill State

Each skill record should track:

- `skill_id`
- `name`
- `version`
- `scope`
- `tenant_id`
- `repo_id`
- `toolset`
- `worker_role`
- `task_type`
- `language`
- `platform`
- `approval_state`
- `safety_state`
- `content_sha`
- `source_memory_refs`
- `source_wiki_refs`
- `validation_refs`
- `usage_count`
- `helpful_count`
- `harmful_count`
- `last_used_at`
- `retired_at`

## Skill Feedback

After a task:

- if skill helped, increment helpful confidence
- if irrelevant, decay retrieval score
- if harmful, create runtime failure and demote/retire candidate
- if missing, create skill gap candidate

Feedback should be attached to the task/session and skill version.

## SkillClaw Integration Modes

### Local Dev Mode

- Hermes manages local skills under `~/.hermes/skills`.
- SkillClaw may inspect/evolve local skill bundles.
- No shared publishing unless explicitly enabled.

### Tenant Mode

- Tenant runtime cell has tenant-local skill library.
- SkillClaw evolve worker can run as a tenant sidecar.
- Published skills remain tenant-private.

### Global Mode

- Global skill evolution runs only on redacted approved memory/wiki records.
- Global skill publication requires approval and validation.
- Tenants opt into global skill ingestion.

## E2E Tests

Minimum tests:

- task classifier selects correct skill ids
- disabled skill feature prevents injection
- tenant-private skill never appears in another tenant
- planner receives planning skill only
- worker receives role-specific execution skill
- harmful skill feedback creates demotion candidate
- approved memory can produce skill candidate
- skill validation blocks publish on failure
- SkillClaw shared storage sync preserves version and content hash

## First Implementation Slice

1. Skill metadata schema and local registry adapter.
2. Skill retrieval query using existing task classifier.
3. Bounded skill packet builder.
4. Supervisor and worker packet fields for skill refs.
5. Skill outcome feedback records.
6. Skill candidate state produced from approved memory/wiki.
7. Optional SkillClaw adapter interface.

This keeps the implementation useful before deploying a full evolve server.
