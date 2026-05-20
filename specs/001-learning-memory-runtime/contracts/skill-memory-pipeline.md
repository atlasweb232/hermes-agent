# Skill Memory Pipeline Contract

## Purpose

Skills are versioned procedural artifacts used by supervisors, planners, and
workers. Memory remains the evidence source. This contract defines how Hermes
selects, injects, validates, evolves, and optionally syncs skills without
allowing skills to override tenant, memory, approval, or validation gates.

## Skill Metadata

Every skill known to the runtime must have a metadata record:

- `skill_id`
- `name`
- `version`
- `scope`
- `tenant_id`
- `repo_id`
- `domain`
- `toolset`
- `worker_role`
- `task_type`
- `language`
- `platform`
- `approval_state`
- `safety_state`
- `content_sha256`
- `bundle_tree_sha256`
- `source_memory_refs`
- `source_wiki_refs`
- `validation_refs`
- `usage_count`
- `helpful_count`
- `irrelevant_count`
- `harmful_count`
- `last_used_at`
- `retired_at`
- `created_at`
- `updated_at`

Allowed `scope` values:

- `user`
- `device`
- `repo`
- `tenant`
- `domain`
- `global`

Allowed `approval_state` values:

- `draft`
- `candidate`
- `validated`
- `approved`
- `rejected`
- `retired`

Allowed `safety_state` values:

- `unknown`
- `safe`
- `restricted`
- `unsafe`

## Skill Retrieval Query

Skill retrieval uses the same task classifier metadata as memory retrieval:

- `tenant_id`
- `repo_id`
- `user_id`
- `session_id`
- `task_id`
- `task_type`
- `intent`
- `toolset`
- `worker_role`
- `language`
- `platform`
- `error_signatures`
- `success_signatures`
- `entities`
- `sensitivity`
- `feature_state`

Hard filters must run before lexical or semantic ranking:

- tenant visibility
- repo visibility
- scope visibility
- approval state
- safety state
- worker role compatibility
- toolset compatibility
- feature toggle state
- retired status
- sensitivity policy

Cross-tenant retrieval is disallowed unless the skill is global, redacted,
approved, shareable, and the tenant has opted in.

## Skill Scoring

After hard filters, scoring may use:

- exact tenant/repo/toolset/task match
- worker role match
- language/platform match
- error/success signature match
- lexical match over compact skill summary
- semantic similarity over approved skill summary
- confidence from helpful/irrelevant/harmful feedback
- recency
- scope penalty for broader-than-repo skills

Harmful feedback must demote or block a skill until repair/approval clears it.

## Skill Packet

Only bounded skill packets may enter prompt context.

Required fields:

- `packet_id`
- `tenant_id`
- `repo_id`
- `task_id`
- `worker_role`
- `skills`
- `token_estimate`
- `created_at`

Each skill item includes:

- `skill_id`
- `name`
- `version`
- `scope`
- `summary`
- `match_reason`
- `confidence`
- `validation_hooks`
- `source_refs`
- `safety_notes`

The packet must not contain:

- raw secrets
- full transcripts
- unbounded logs
- full unrelated skill libraries
- unapproved skill candidates

## Injection Points

Skill packets may be attached to:

- supervisor task packet
- planner packet
- worker delegation packet
- QA/browser/deployment packet
- validation report
- session summary

The supervisor gets compact summaries. Workers may receive role-specific skill
refs or selected skill sections. Full bundles are loaded only when the worker
role and toolset allow it.

## Skill Authority

Skills are advisory. They do not override:

- explicit user/operator instruction
- tenant policy
- repo protection policy
- secret policy
- current git/test/runtime evidence
- Spec Kit requirements
- validation gates
- judge/operator approval requirements

Skills cannot approve memory, enable enforcement, publish themselves, mark work
complete, or bypass supervisor validation.

## Outcome Feedback

After a task, Hermes records skill outcome feedback:

- `feedback_id`
- `tenant_id`
- `repo_id`
- `task_id`
- `session_id`
- `skill_id`
- `skill_version`
- `worker_role`
- `impact`: `helpful`, `irrelevant`, `harmful`, or `unknown`
- `evidence_refs`
- `validation_refs`
- `reason`
- `created_at`

Feedback drives retrieval confidence, repair candidates, demotion, or
retirement. Harmful feedback creates a runtime learning signal.

## Skill Candidate State

Skill candidates may be produced from:

- approved memory
- memory wiki claims
- judged dreaming proposals
- repeated skill gap feedback
- validated successful workflows

Candidate states:

- `proposed`
- `validated`
- `approved`
- `rejected`
- `published`
- `retired`

Publishing requires validation and approval. Raw session data alone is not
enough to publish a skill.

## SkillClaw Adapter

SkillClaw integration is optional and adapter-based.

Adapter capabilities:

- read local skill bundle
- write local skill candidate bundle
- compute content and tree hashes
- read validation result
- stage tenant skill candidate
- stage global skill candidate
- sync approved bundles when enabled

Default behavior:

- local mode only
- shared sync disabled
- no raw session publishing
- no cross-tenant sharing

## CLI/API Surfaces

Planned runtime surfaces:

- `hermes skills runtime search --json`
- `hermes skills runtime packet --json`
- `hermes skills feedback --json`
- `hermes skills candidates --json`

All surfaces must be tenant/repo scoped and return stable JSON.

## E2E Requirements

The E2E suite must prove:

- task classifier selects the expected skill ids
- disabled skill feature prevents injection
- tenant-private skill never appears in another tenant
- planner receives planning skill only
- worker receives role-specific execution skill
- harmful skill feedback creates demotion/repair candidate
- approved memory can produce skill candidate
- SkillClaw adapter preserves version and content hash
- shared sync remains disabled by default
