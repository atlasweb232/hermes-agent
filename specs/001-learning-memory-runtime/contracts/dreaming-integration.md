# Dreaming Integration Contract

## Purpose

Dreaming is an offline proposal generator over approved evidence. It may
identify skill, test, CI/CD, routing, memory wiki, cost, observability,
training, onboarding, toolset, policy, and architecture improvements, but it
does not mutate runtime state.

Dreaming output is proposal-only. It must not inject prompts, publish skills,
update wiki claims, change config, queue goals, enforce policy, edit repos,
deploy code, or export training data directly. Every conversion target must
pass deterministic validation, judge review, and operator or tenant-admin
approval before another subsystem acts on it.

## Feature Toggles

The feature remains disabled by default.

Required toggles:

- `supervisor.dreaming.enabled`
- `supervisor.dreaming.local.enabled`
- `supervisor.dreaming.global.enabled`
- `supervisor.dreaming.allow_skill_candidates`
- `supervisor.dreaming.allow_ci_cd_proposals`
- `supervisor.dreaming.allow_test_gap_proposals`
- `supervisor.dreaming.allow_policy_proposals`
- `supervisor.dreaming.require_judge`
- `supervisor.dreaming.require_operator_approval`

If dreaming is disabled, a sidecar tick records skipped-by-toggle and produces
no proposal.

## Roles

Local dreaming role metadata:

```json
{
  "role": "local_dreaming",
  "mode": "local",
  "tenant_id": "tenant-id",
  "repo_id": "repo-id",
  "visibility": "tenant_repo",
  "can_publish_global": false,
  "input_policy": "tenant_repo_approved_evidence_only"
}
```

Local dreaming remains tenant/repo scoped. It cannot publish globally or read
another tenant/repo packet.

Global dreaming role metadata:

```json
{
  "role": "global_dreaming",
  "mode": "global",
  "tenant_id": null,
  "repo_id": null,
  "visibility": "global",
  "can_publish_global": false,
  "input_policy": "redacted_approved_shareable_global_only"
}
```

Global dreaming consumes only records marked global, redacted, approved, and
shareable. It never receives tenant-private raw evidence.

## Evidence Packet Schema

Dreaming input packets are bounded evidence summaries, not transcripts or logs.

```json
{
  "packet_id": "packet-id",
  "source_ref": "wikiclaim-or-memory-id",
  "content_summary": "redacted bounded summary",
  "tenant_id": "tenant-id-or-null",
  "repo_id": "repo-id-or-null",
  "scope": "local-or-global",
  "approved": true,
  "redacted": true,
  "shareable": false,
  "kind": "memory|wiki|ci|test|skill|telemetry"
}
```

Packets must exclude raw secrets, raw full transcripts, raw tenant-private
cross-tenant evidence, and unbounded logs.

## Proposal Types

Required proposal types:

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

Legacy proposal types remain parseable for compatibility: `playbook`, `test`,
`routing`, `policy`, `cleanup`, `architecture`, and `training`.

## Proposal DTO

```json
{
  "id": "dream_hash",
  "proposal_type": "skill_candidate",
  "summary": "short reviewable proposal summary",
  "rationale": "why the approved evidence supports this",
  "evidence_refs": ["packet-id"],
  "scope": {
    "tenant_id": "tenant-id-or-null",
    "repo_id": "repo-id-or-null",
    "visibility": "local-or-global"
  },
  "risk": "low|medium|high",
  "trigger": "manual|sidecar_interval|service_start",
  "requested_action": "proposal-only next action",
  "runtime_effect": false,
  "affected_feature_ids": ["US15"],
  "conversion_target": "skill_candidate",
  "expected_benefit": "bounded benefit statement",
  "forbidden_direct_actions": ["publish_skill", "edit_repo"],
  "suggested_validation": ["validation that must pass after conversion"],
  "role_metadata": {},
  "evidence_packets": [],
  "judge_state": {"status": "pending"},
  "operator_state": {"status": "pending"}
}
```

`runtime_effect` must be `false`.

## Conversion Targets

Allowed conversion targets:

- `memory_candidate`
- `memory_wiki_update`
- `global_memory_wiki`
- `skill_candidate`
- `test_backlog_item`
- `spec_task`
- `ci_cd_task`
- `policy_candidate`
- `allocator_policy_candidate`
- `routing_advisory`
- `observability_task`
- `tenant_onboarding_task`
- `toolset_recommendation`
- `cost_review_item`
- `training_corpus_candidate`
- `architecture_review_item`

Conversion creates only a candidate in the target subsystem. It does not approve,
publish, deploy, edit, enforce, inject, or export.

## Validator Output

Validators return structured output:

```json
{
  "accepted": false,
  "proposal_id": "dream_hash",
  "proposal_type": "ci_cd_hardening",
  "error_codes": ["forbidden_direct_runtime_effect"],
  "warnings": [],
  "conversion_target": "ci_cd_task",
  "required_gates": ["deterministic_validator", "judge", "operator"]
}
```

Validators must reject direct runtime effects, direct mutation requests, missing
or unknown evidence refs, unsupported conversion targets, tenant scope widening,
global input that is not redacted/approved/shareable, secret patterns, raw
transcripts, and unbounded logs.

## Judge And Operator State

Judge state records deterministic or LLM judge decisions:

```json
{"status": "pending|approved|reject|needs_human", "decision": "approve|reject|needs_human"}
```

Operator state records tenant-admin or operator decisions:

```json
{"status": "pending|approved|rejected", "decision": "approve|reject", "operator": "id"}
```

Both gates must approve before conversion. Rejected proposals remain reviewable
but inert.

## Dashboard DTO

Dashboard review DTOs expose:

- proposal id, tenant id, repo id, type, status, and risk
- summary, evidence refs, affected feature ids, expected benefit
- conversion target, forbidden direct actions, suggested validation
- role metadata
- validator errors
- judge state and decision
- operator state and action history
- created and updated timestamps

Dashboard DTOs are read-only review surfaces. They cannot apply proposal
effects directly.
