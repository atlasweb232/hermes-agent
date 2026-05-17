# Data Model: Runtime Learning Memory Framework

## RuntimeEvent

- `id`: stable event id
- `topic`: event topic such as `runtime.tool_result`, `runtime.task_outcome`, `runtime.policy_audit`, `learning.candidate.proposed`
- `payload_json`: redacted structured payload
- `status`: `pending`, `processing`, `consumed`, `failed`
- `consumer`: current consumer name
- `lease_until`: timestamp for processing ownership
- `attempts`: processing attempt count
- `error`: structured failure summary
- `created_at`, `updated_at`, `consumed_at`: timestamps

## LearningCandidate

- Existing meta candidate fields: `id`, `tenant_id`, `repo_id`, `kind`, `claim`, `evidence_json`, `score`, `status`, timestamps
- Statuses: `proposed`, `approved`, `rejected`, `archived`, `rolled_back`, `needs_human`
- Candidate kinds include `playbook`, `routing_hint`, `recovery_hint`, `memory_rule`, `command_repair_policy`

## JudgeDecision

- `id`: stable decision id
- `candidate_id`: evaluated candidate or policy proposal
- `judge_task`: `learning_judge` or future `policy_judge`
- `decision`: `approve`, `reject`, `needs_human`
- `risk`: `low`, `medium`, `high`
- `reason`: short rationale
- `required_scope`: scope where decision is valid
- `enforcement_allowed`: boolean, false by default
- `raw_output_hash`: hash of raw model output, not raw transcript
- `created_at`: timestamp

## ApprovedMemory

- `id`: stable memory id
- `source_candidate_id`: candidate that produced it
- `memory_type`: routing hint, playbook, recovery hint, rule, policy
- `tenant_id`: tenant where memory is known to apply, if scoped
- `repo_id`: repo where memory is known to apply, if scoped
- `tool`: tool or worker affected by the memory, if applicable
- `task_type`: normalized task class such as `worker_routing`, `branch_triage`, `form_fill`, or `merge_repair`
- `intent`: normalized user/workflow intent
- `error_signature`: normalized signature of the avoided failure, if applicable
- `success_signature`: normalized signature of the known-good path, if applicable
- `scope`: explicit applicability scope such as `global_safe`, `tenant_safe`, `repo_safe`, `machine_safe`, `tool_safe`, or `task_type_safe`
- `text`: compact advisory content
- `evidence_uri`: pointer to task, event, or log summary
- `confidence`: numeric confidence
- `tier`: `hot`, `warm`, `cold`
- `last_used_at`: timestamp for retrieval feedback
- `last_verified_at`: timestamp for evidence refresh
- `status`: `active`, `superseded`, `archived`

## TaskRetrievalQuery

- `tenant_id`: active tenant, if known
- `repo_id`: active repository, if known
- `cwd`: current working directory
- `task_type`: normalized task class
- `intent`: task intent
- `tools`: tools or workers likely to be used
- `entities`: branch names, provider names, service names, files, or external systems
- `error_signatures`: known failure patterns detected in task text or recent tool output
- `success_signatures`: known success patterns detected in task text or recent tool output
- `required_scope`: minimum scope required for injection
- `raw_query`: compact redacted source text for audit

## MemoryRelevanceScore

- `memory_id`: approved memory being scored
- `query_id`: retrieval query or task invocation id
- `score`: final numeric relevance score
- `features_json`: exact match, semantic match, recency, confidence, tier, and penalty components
- `decision`: `include`, `exclude`, or `defer`
- `reason`: short explanation for audit

## MemoryPacket

- `id`: stable packet id
- `query_id`: retrieval query that produced the packet
- `items`: ordered approved memory ids and short summaries
- `max_chars`: prompt budget used to build the packet
- `advisory_header`: required warning that explicit instructions and current evidence are more authoritative
- `created_at`: timestamp

## OutcomeFeedback

- `id`: stable feedback id
- `task_id`: task/session/work item id
- `packet_id`: injected memory packet id
- `memory_id`: approved memory item affected by feedback
- `outcome`: `helpful`, `irrelevant`, `harmful`, or `unknown`
- `evidence_uri`: pointer to task result or tool output
- `confidence_delta`: bounded adjustment proposed for approved memory
- `tier_action`: `promote`, `demote`, `keep`, or `archive_candidate`
- `created_at`: timestamp

## MemoryWikiClaim

- `id`: stable wiki claim id
- `title`: concise title
- `body`: durable claim
- `evidence`: list of approved memory or event pointers
- `confidence`: numeric confidence
- `last_verified_at`: timestamp
- `status`: `active`, `stale`, `archived`

## DreamingProposal

- `id`: stable proposal id
- `proposal_type`: playbook, test, routing, policy, cleanup, architecture
- `summary`: proposal text
- `rationale`: why it may help
- `evidence`: wiki/memory/event pointers
- `risk`: `low`, `medium`, `high`
- `status`: `proposed`, `judged`, `approved`, `rejected`, `archived`

## LearningJob

- `id`: stable job id
- `job_type`: sidecar, curator, judge, wiki, dreaming, housekeeping, reconcile
- `status`: `queued`, `running`, `completed`, `failed`, `blocked`
- `owner`: process or worker id
- `heartbeat_at`: last progress timestamp
- `started_at`, `finished_at`: timestamps
- `metrics_json`: counts and ratios
- `error_json`: structured error if failed

## State Transitions

- Runtime event: `pending -> processing -> consumed`
- Runtime event failure: `processing -> pending` until retry limit, then `failed`
- Candidate: `proposed -> approved` only after quality gate and judge/operator rules
- Candidate rejection: `proposed -> rejected` or `needs_human`
- Approved memory: `active -> superseded -> archived`
- Approved memory feedback: `active -> active` with confidence/tier adjustment, or `active -> superseded/archived` after repeated harmful feedback
- Dreaming proposal: `proposed -> judged -> approved/rejected`, never directly to enforced
