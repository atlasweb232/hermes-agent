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
- `scope`: tenant/repo/machine/tool scope
- `text`: compact advisory content
- `evidence_uri`: pointer to task, event, or log summary
- `confidence`: numeric confidence
- `tier`: `hot`, `warm`, `cold`
- `status`: `active`, `superseded`, `archived`

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
- Dreaming proposal: `proposed -> judged -> approved/rejected`, never directly to enforced
