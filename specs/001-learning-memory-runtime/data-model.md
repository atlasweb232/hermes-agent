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

## SupervisorTaskPacket

- `id`: stable packet id
- `source`: `chat`, `dashboard`, `gateway`, `cli`, or automation source
- `tenant_id`: tenant if known
- `repo_id`: target repo if known
- `cwd`: working directory if known
- `raw_request_summary`: compact redacted user request
- `task_type`: normalized task class
- `complexity`: `trivial`, `standard`, or `complex`
- `requires_speckit`: boolean
- `clarifications`: unresolved or answered scope questions
- `memory_packet_id`: retrieved memory packet attached to the task
- `success_criteria`: user-visible success conditions
- `constraints`: safety, secret, file ownership, deployment, and approval constraints
- `status`: `intake`, `needs_clarification`, `planned`, `delegated`, `validated`, `completed`, `blocked`
- `created_at`, `updated_at`: timestamps

## PlannerPacket

- `id`: stable planner packet id
- `task_packet_id`: parent supervisor task packet
- `planner_role`: `planner`, `speckit_creator`, or combined role
- `preferred_model`: configured strong reasoning model
- `branch_name`: numbered feature branch
- `worktree_path`: isolated worktree path if used
- `required_artifacts`: spec, plan, tasks, contracts, quickstart, research
- `memory_packet_id`: advisory memory attached to planning
- `return_schema`: required planner response shape
- `status`: `queued`, `running`, `completed`, `failed`, `blocked`

## SpecKitArtifactSet

- `id`: stable artifact set id
- `task_packet_id`: parent supervisor task packet
- `branch_name`: numbered feature branch
- `worktree_path`: worktree path, if any
- `spec_path`: path to `spec.md`
- `plan_path`: path to `plan.md`
- `tasks_path`: path to `tasks.md`
- `artifact_status`: `missing`, `draft`, `validated`, `committed`
- `commit_sha`: commit preserving artifacts, if committed

## WorkerDelegationPacket

- `id`: stable worker packet id
- `task_packet_id`: parent supervisor task packet
- `worker_id`: selected worker
- `worker_kind`: `codex`, `claude_code`, `deepseek_tui`, `cursor`, `minimax_via_claude_code`, or configured provider
- `repo_id`: target repo
- `branch_name`: target branch
- `worktree_path`: isolated worktree path
- `objective`: bounded task objective
- `owned_files`: allowed write scope
- `constraints`: safety and workflow constraints
- `validation_commands`: commands or checks the worker must run
- `memory_packet_id`: advisory memory attached to execution
- `return_schema`: required result fields
- `status`: `queued`, `running`, `completed`, `failed`, `blocked`

## WorkerResult

- `id`: stable worker result id
- `delegation_packet_id`: source delegation packet
- `summary`: concise result
- `changed_files`: changed file paths
- `commands_run`: commands and outcomes
- `validation_status`: `passed`, `failed`, `not_run`, or `blocked`
- `blockers`: unresolved blockers
- `memory_notes`: lessons or irrelevant memory feedback
- `created_at`: timestamp

## ValidationReport

- `id`: stable report id
- `task_packet_id`: parent supervisor task packet
- `artifact_set_id`: Spec Kit artifacts checked
- `worker_result_ids`: worker results reviewed
- `git_diff_summary`: compact changed-file summary
- `test_results`: structured validation results
- `requirement_coverage`: mapping to Spec Kit tasks or success criteria
- `status`: `passed`, `failed`, `blocked`
- `created_at`: timestamp

## SessionSummary

- `id`: stable summary id
- `task_packet_id`: parent supervisor task packet
- `master_instructions`: compact user/operator instructions
- `decisions`: supervisor routing and approval decisions
- `delegations`: workers and task packets used
- `validation_report_id`: final validation report
- `memory_outcome`: memory used, ignored, helpful, harmful, or newly written
- `commit_refs`: branch and commit pointers
- `created_at`: timestamp

## WorktreeAssignment

- `id`: stable assignment id
- `task_packet_id`: parent supervisor task packet
- `agent_id`: planner, worker, or reviewer agent
- `branch_name`: assigned branch
- `worktree_path`: assigned worktree
- `owned_files`: write scope
- `status`: `active`, `released`, `blocked`, `abandoned`

## SupervisorTaskLedgerEntry

- `id`: stable ledger entry id
- `task_packet_id`: parent supervisor task packet
- `status`: `created`, `planned`, `delegated`, `running`, `validating`, `completed`, `blocked`, `failed`, `reclaimed`, `reassigned`, or `abandoned`
- `active_worker_id`: current worker, if any
- `active_delegation_packet_id`: current worker packet, if any
- `lease_owner`: worker or supervisor process holding the task
- `lease_expires_at`: timestamp when the task may be reclaimed
- `heartbeat_at`: last worker/progress heartbeat
- `retry_count`: recovery or validation retry count
- `retry_budget`: maximum retry count before escalation
- `progress_signature`: compact summary of latest git/test/progress state
- `last_error_signature`: repeated command/error signature, if any
- `validation_status`: `unknown`, `passed`, `failed`, or `blocked`
- `spec_refs`: Spec Kit artifact refs
- `git_refs`: branch, worktree, commit, and diff summary refs
- `memory_packet_id`: memory packet used for the current attempt
- `recovery_packet_ids`: recovery packets created for this task
- `override_actions`: audited supervisor overrides
- `created_at`, `updated_at`: timestamps

## WorkerHeartbeat

- `id`: stable heartbeat id
- `task_packet_id`: parent supervisor task packet
- `delegation_packet_id`: worker packet, if any
- `worker_id`: worker emitting progress
- `action`: current action or command class
- `progress_summary`: concise progress update
- `command_signature`: normalized command signature, if any
- `error_signature`: normalized error signature, if any
- `git_delta`: changed-file or diff summary
- `test_delta`: validation/test progress summary
- `status`: `running`, `blocked`, `failed`, or `completed`
- `created_at`: timestamp

## RecoveryPacket

- `id`: stable recovery packet id
- `task_packet_id`: parent supervisor task packet
- `source_delegation_packet_id`: worker packet being recovered, if any
- `reason`: `stale_lease`, `repeated_error`, `no_progress`, `validation_failed`, `constraint_violation`, or `operator_override`
- `objective`: original bounded task objective
- `partial_work_summary`: git diff/log/worktree summary
- `failed_commands`: failed command/error evidence
- `validation_failures`: failed validation evidence
- `memory_packet_id`: memory packet used by the failed attempt
- `recommended_next_action`: replan, retry, alternate worker, stronger reviewer, or abandon
- `next_worker_candidates`: ordered worker/model fallback candidates
- `created_at`: timestamp

## SupervisorOverrideAction

- `id`: stable override action id
- `task_packet_id`: parent supervisor task packet
- `action`: `interrupt`, `request_status`, `pause`, `block`, `reclaim`, `reassign`, `escalate`, or `abandon`
- `reason`: operator or policy reason
- `actor`: `operator`, `supervisor_policy`, or service id
- `previous_worker_id`: worker affected
- `next_worker_id`: reassigned worker, if any
- `recovery_packet_id`: recovery packet used, if any
- `created_at`: timestamp

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
- `features_json`: exact match, lexical match, vector similarity, graph proximity, semantic match, recency, confidence, tier, and penalty components
- `decision`: `include`, `exclude`, or `defer`
- `reason`: short explanation for audit

## MemoryIndexDocument

- `id`: stable index document id
- `memory_id`: approved memory represented by the document
- `tier`: `hot`, `warm`, or `cold`
- `text`: compact redacted text for lexical/vector indexing
- `metadata_json`: tenant, repo, machine, tool, task type, signatures, scope, status, confidence, and timestamps
- `embedding_model`: model used for vectorization, if any
- `embedding_ref`: local vector row id or external vector backend id
- `fts_rowid`: lexical index row id, if any
- `status`: `active`, `stale`, `deleted`
- `created_at`, `updated_at`: timestamps

## MemoryGraphNode

- `id`: stable node id
- `node_type`: `tenant`, `repo`, `machine`, `tool`, `worker`, `provider`, `model`, `task_type`, `error_signature`, `success_signature`, `memory`, `wiki_claim`, `dreaming_proposal`, or `policy`
- `key`: normalized unique key within the node type
- `label`: human-readable label
- `metadata_json`: optional redacted node metadata

## MemoryGraphEdge

- `id`: stable edge id
- `source_node_id`: source node
- `target_node_id`: target node
- `edge_type`: `APPLIES_TO`, `OBSERVED_ON`, `USES_TOOL`, `USES_MODEL`, `AVOIDS_ERROR`, `RECOMMENDS_ACTION`, `DERIVED_FROM`, `PROMOTED_TO`, or `RELATED_TO`
- `weight`: numeric edge strength
- `evidence_uri`: evidence pointer for the relationship
- `created_at`: timestamp

## RetrievalRun

- `id`: stable retrieval run id
- `query_id`: task retrieval query id
- `hard_filters_json`: required metadata filters
- `lexical_candidates_json`: candidate ids and lexical scores
- `vector_candidates_json`: candidate ids and vector similarities
- `graph_candidates_json`: candidate ids and graph paths
- `reranked_candidates_json`: final ranked candidates and feature contributions
- `packet_id`: resulting memory packet id
- `created_at`: timestamp

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
- `scope`: tenant, repo, machine, platform, tool, provider, model, task type, error signature, and success signature labels
- `confidence`: numeric confidence
- `safety`: `secret_safe`, `cross_tenant_shareable`, redaction status, and export eligibility
- `index_payload`: compact text and metadata suitable for lexical, vector, and graph indexing
- `training_payload`: optional curated training-data shape derived from the claim, never raw transcript text
- `last_verified_at`: timestamp
- `status`: `active`, `stale`, `archived`

## DreamingProposal

- `id`: stable proposal id
- `proposal_type`: playbook, test, routing, policy, cleanup, architecture
- `summary`: proposal text
- `rationale`: why it may help
- `evidence`: wiki/memory/event pointers
- `scope`: proposed applicability boundaries
- `risk`: `low`, `medium`, `high`
- `trigger`: `manual`, `sidecar_interval`, or `service_start`
- `interval_due_at`: timestamp when sidecar-driven dreaming was due
- `job_id`: learning job that produced the proposal
- `validator_errors`: deterministic validation errors, if any
- `judge_decision_id`: judge decision reference, if reviewed
- `operator_decision`: approval/rejection metadata, if reviewed
- `status`: `proposed`, `judged`, `approved`, `rejected`, `archived`

Dreaming proposals are not retrieval memory and are not policies. They become
runtime-relevant only after judge/operator approval converts them into an
approved memory candidate, wiki update, or policy candidate.

## TrainingCorpusRecord

- `id`: stable export record id
- `source_wiki_claim_id`: source wiki claim
- `dataset_family`: `repo_migration_plan`, `migration_failure_repair`, `before_after_diff`, `validation_recipe`, `architecture_pattern`, or `policy_playbook`
- `goal`: normalized goal or task type
- `legacy_repo_ref`: source repository id, branch, commit, language/framework/dependency profile, and architecture summary
- `target_repo_ref`: target repository id, branch, commit, desired architecture, runtime, and validation strategy
- `spec_refs`: Spec Kit artifact refs such as `spec.md`, `plan.md`, and `tasks.md`
- `diff_refs`: before/after commit refs, patch summaries, changed-file summaries, and redacted diff hashes
- `scope`: tenant, repo, platform, tool, provider/model, and shareability boundary
- `failure_signature`: compact failure pattern if applicable
- `bad_action`: known incorrect action if applicable
- `successful_action`: verified action or playbook if applicable
- `validation_evidence`: test command refs, log hashes, validation reports, and completion evidence
- `evidence_refs`: wiki, candidate, event, session, and policy audit pointers
- `confidence`: numeric confidence at export time
- `approval_provenance`: judge/operator/version metadata
- `safety`: redaction, secret safety, and cross-tenant shareability flags
- `drift_eval`: stable regression prompt, expected behavior, forbidden bad fix, and required evidence labels
- `export_status`: `candidate`, `approved`, `exported`, `rejected`, or `archived`
- `payload`: sanitized structured training payload

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
- Supervisor task packet: `intake -> needs_clarification/planned -> delegated -> validated -> completed`
- Supervisor task ledger: `created -> planned -> delegated -> running -> validating -> completed`
- Supervisor task recovery: `running -> blocked/reclaimed -> reassigned -> running`
- Supervisor task failure: `running/validating -> failed/abandoned`
- Spec Kit artifact set: `missing -> draft -> validated -> committed`
- Worker delegation packet: `queued -> running -> completed/failed/blocked`
- Memory index document: `active -> stale -> deleted`, rebuilt from approved memory when source metadata changes
- Retrieval run: immutable audit record after packet construction
- Candidate: `proposed -> approved` only after quality gate and judge/operator rules
- Candidate rejection: `proposed -> rejected` or `needs_human`
- Approved memory: `active -> superseded -> archived`
- Approved memory feedback: `active -> active` with confidence/tier adjustment, or `active -> superseded/archived` after repeated harmful feedback
- Dreaming proposal: `proposed -> judged -> approved/rejected`, never directly to enforced
