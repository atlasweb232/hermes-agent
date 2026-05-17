# Curator Policy Framework Architecture

## Purpose

Hermes separates runtime execution from offline learning:

- primary chat model answers the user
- worker models execute delegated work
- curator model reviews structured evidence offline
- deterministic validators decide what can become policy

Curator output is advisory. It is never enforcement by itself.

## Model Roles

```text
primary chat model != worker model != curator model
```

The curator role is configured under:

```yaml
supervisor:
  curator:
    enabled: true
    provider: ollama
    model: gemma2:2b
    base_url: http://127.0.0.1:11434
    mode: advisory
    approval_required: true
    timeout_seconds: 120
    max_records: 10
    min_score: 0.5
```

Initial supported runtime adapter:

- `ollama` via `POST /api/generate`
- `codex` via non-interactive `codex exec`

Framework placeholders:

- `custom` / OpenAI-compatible endpoint
- `deepseek`
- Cerebras `gpt-oss-120b` via OpenAI-compatible `base_url`

Codex runs as an external advisory worker:

```bash
codex exec --skip-git-repo-check --sandbox read-only \
  --ignore-rules --output-last-message <tmpfile> -
```

The prompt is passed on stdin. The final response is read from the temp file so
Codex event output does not contaminate the candidate text.

DeepSeek should be configured through the OpenAI-compatible `custom` provider
unless a dedicated worker adapter is added.

## CLI Surface

The architecture target is API-first. CLI commands are thin local wrappers for
operator smoke tests and should call the same service functions as the backend.

```bash
hermes curator config
hermes curator model --provider ollama --model gemma2:2b --base-url http://127.0.0.1:11434
hermes curator test
hermes curator policy-run
```

Raw config still works:

```bash
hermes config set supervisor.curator.provider ollama
hermes config set supervisor.curator.model gemma2:2b
hermes config set supervisor.curator.base_url http://127.0.0.1:11434
```

## API Surface

The backend should expose the curator/control-plane operations directly so the
dashboard, gateway, Telegram supervisor, and automation do not shell out to the
CLI.

```http
GET  /api/curator/config
POST /api/curator/config
POST /api/curator/test
POST /api/curator/policy-run
GET  /api/curator/candidates
POST /api/curator/candidates/:id/approve
POST /api/curator/candidates/:id/reject
POST /api/curator/candidates/:id/archive
POST /api/curator/candidates/prune
```

Expected response shape for `POST /api/curator/policy-run`:

```json
{
  "status": "completed",
  "records_scanned": 1,
  "candidates_created": 1,
  "candidates": [
    {
      "candidate_id": "curpol_...",
      "kind": "command_repair_policy",
      "status": "proposed",
      "validation": {
        "status": "valid",
        "eligible_for_approval": true,
        "approved_for_enforcement": false,
        "warnings": [],
        "errors": []
      }
    }
  ]
}
```

Approval endpoints must preserve the candidate evidence payload. Approval may
mark a candidate eligible for later policy-engine use, but it must not erase
`validation`, `source_record_id`, `failed_path`, `working_path`, or
`curator_output`.

Archive and prune endpoints must also preserve evidence. They mark candidates
`archived` and append action metadata; they do not delete rows.

## Evidence Flow

```text
tool outcome
  -> deterministic runtime lesson capture
  -> hermes_memory_records(kind=tool_routing_lesson)
  -> curator policy pass
  -> hermes_meta_candidates(kind=command_repair_policy, status=proposed)
  -> deterministic validation
  -> explicit approval
  -> future policy engine may enforce approved policy
```

The runtime lesson is authoritative evidence. The curator output is a proposed
interpretation of that evidence.

## Generic Rollup Quality Gates

Generic rollup is intentionally conservative. It should not turn every recent
memory row into active supervisor guidance.

Before creating or updating a `hermes_meta_candidates` row, rollup applies these
deterministic gates:

- curator-only record kinds, such as `tool_routing_lesson`, are skipped and left
  for specialized curator passes
- memory records with terminal statuses such as `archived`, `rejected`, or
  `rolled_back` are skipped
- existing candidates with terminal statuses such as `approved`, `applied`,
  `archived`, `rejected`, or `rolled_back` are not downgraded back to
  `proposed`
- candidates need structured evidence before promotion or active retention
- synthetic/test markers such as `Smoke:`, `retry-empty`, `loop forever`,
  `crashy`, and `prior #` are skipped
- Kanban `task_outcome` records must be high-signal completed outcomes with a
  memory packet before they can become candidates
- reconcile applies the same candidate-quality gates before promotion, so old
  proposed candidates created before the filters do not get promoted later
- housekeeping can archive invalid proposed candidates that fail the quality
  gates, keeping normal candidate review focused on active usable guidance

The filters are configurable:

```yaml
supervisor:
  learning:
    rollup_filters:
      curator_only_record_kinds:
        - tool_routing_lesson
      require_evidence_for_candidates: true
      archive_invalid_proposed: true
      archive_invalid_approved: true
      terminal_existing_statuses:
        - approved
        - applied
        - archived
        - rejected
        - rolled_back
      synthetic_title_patterns:
        - "Smoke:"
        - retry-empty
        - retry-corrected
        - loop forever
        - crashy
        - "prior #"
      task_outcome:
        enabled: true
        allowed_event_kinds:
          - completed
        require_memory_packet: true
        min_score: 0.75
```

Rollup records skip counts in learning-run metrics. This makes it visible when
old Kanban smoke-test artifacts are being suppressed rather than silently
promoted.

## Command-Repair Candidate

A command-repair candidate records:

- policy version
- source memory record id
- failed path
- working path
- failed commands
- working command
- curator output
- validation status
- validation warnings/errors

The current policy version is:

```text
2026.05.16
```

## Validation

The first validator is deliberately conservative:

- flags unsupported claims such as Docker/GPU/Kubernetes when those terms are
  absent from the source evidence
- rejects secret-like assignments in curator output
- warns when output misses the observed success path

Example warning:

```yaml
code: unsupported_claim_warning
claim: docker
reason: Docker was not present in the runtime lesson evidence.
```

This directly addresses the observed Gemma 2B curator behavior where it inferred
Docker relevance from a Claude routing lesson even though Docker was unrelated.

## Enforcement Boundary

This framework does not automatically rewrite terminal commands yet. The first
policy-engine layer is audit-only:

```text
incoming terminal command
  -> normalize command
  -> match approved command_repair_policy candidates
  -> emit runtime_policy_audit metadata
  -> execute original command unchanged
```

That engine must not hardcode per-failure fixes. It should consume approved
policy data with bounded selectors. Rewrite templates remain a future
enforcement layer.

## Injection And Enforcement

The unresolved runtime issue is not memory capture or curation. It is injection
and enforcement: Hermes can store a lesson and curate a policy candidate, but the
terminal tool path must still consult approved policy before execution.

The generic policy engine runs as a terminal pre-tool step:

```text
terminal(function_args.command)
  -> command normalizer
  -> approved policy lookup
  -> selector match
  -> audit/noop decision
  -> terminal execution
  -> runtime_policy_audit metadata
```

Policy lookup rules:

- only `command_repair_policy` candidates with `status=approved` or `status=applied`
- validation payload must exist
- `validation.eligible_for_approval=true`
- `validation.approved_for_enforcement` is not sufficient by itself; a dedicated
  policy-engine approval flag or allowlist should be introduced before automatic
  rewrites are enabled
- proposed candidates are never enforced
- raw curator prose is never parsed as an executable rule

The policy data consumed by the engine should be structured:

```json
{
  "policy_type": "command_repair",
  "policy_version": "2026.05.16",
  "source_record_id": "memrec_...",
  "match": {
    "binary": "worker-router",
    "subcommand": "claude"
  },
  "rewrite": {
    "binary": "claude",
    "args": ["-p", "{{prompt}}", "--model", "sonnet"]
  },
  "limits": {
    "max_rewrites_per_session": 1,
    "requires_same_intent": true
  }
}
```

Every matched policy annotates the tool result:

```json
{
  "runtime_policy_audit": {
    "status": "matched",
    "mode": "audit",
    "policy_id": "curpol_...",
    "source_record_id": "memrec_...",
    "action": "would_rewrite",
    "from": "worker-router claude --model sonnet -p \"two plus two\"",
    "to": "claude -p \"two plus two\" --model sonnet",
    "policy_version": "2026.05.16"
  }
}
```

Guardrails:

- never rewrite commands containing secret-like values
- never rewrite destructive commands
- never rewrite across unrelated binaries unless the policy explicitly allows it
- cap rewrites per session
- emit metrics for matched, rewritten, blocked, and skipped policies
- allow disabling enforcement with config

Suggested config:

```yaml
supervisor:
  policy_engine:
    enabled: true
    mode: audit
    max_matches: 3
    allowed_policy_types:
      - command_repair
```

`mode=audit` should log what would have happened without changing the command.
The current implementation treats `mode=enforce` as audit until deterministic
rewrite templating and explicit enforcement approval are added.

## Candidate Housekeeping

Housekeeping is a control-plane/background operation, not a chat/tool hot-path
operation. Its job is to keep `hermes_meta_candidates` useful by archiving stale
or noisy candidates while preserving the evidence trail.

Default policy:

```yaml
supervisor:
  learning:
    housekeeping:
      enabled: true
      interval_seconds: 3600
      max_scan: 1000
      max_candidates_per_run: 100
      max_runtime_seconds: 10
      proposed_ttl_days: 7
      rejected_ttl_days: 30
      approved_ttl_days: 0
      max_candidates_per_kind: 25
```

Lifecycle states:

```text
proposed -> approved -> applied
proposed -> rejected
proposed/rejected/approved -> archived
applied -> rolled_back
```

`approved_ttl_days=0` means approved candidates are durable by default.
Operators must explicitly opt into approved-candidate cleanup.

Manual CLI smoke tests:

```bash
hermes memory candidates prune --dry-run --json
hermes memory candidates prune --yes --json
hermes memory candidates archive <candidate_id> --reason "superseded"
```

The same service function should back future API endpoints:

```http
POST /api/curator/candidates/prune
POST /api/curator/candidates/:id/archive
```

Housekeeping triggers:

- manual CLI/API prune request
- learning sidecar tick when `interval_seconds` has elapsed
- future backend scheduler job running in a worker thread/process

Housekeeping guardrails:

- bounded scan count
- bounded archive count per run
- bounded runtime
- archive, never delete
- preserve existing `evidence_json`
- append action history with `housekeeping_run_id`, previous status, reason, and timestamp
- never block terminal execution, delegation, or chat response generation

This answers the "old candidates should not be there" problem without losing
auditability. Old or low-value candidates become invisible to normal active
candidate review by using `status=archived`, but they remain available for
forensics and later migration into memory wiki/cold storage.

## Controlled Memory Injection

Runtime injection is read-only advisory context. It does not enforce, rewrite,
route, merge, or execute anything.

Worker context retrieval reads from `hermes_meta_candidates` directly and only
injects candidates that pass all of these gates:

- status is `approved` or `applied`
- candidate passes the same quality gate used by promotion/housekeeping
- candidate score is above `supervisor.learning.injection.min_score`
- candidate matches the current task query/title/body when `require_match=true`
- compact output stays within `max_candidates` and `max_chars`

Default config:

```yaml
supervisor:
  learning:
    injection:
      enabled: true
      statuses:
        - approved
        - applied
      max_candidates: 5
      min_score: 0.6
      max_chars: 2500
      require_match: true
```

Injected worker context is labeled:

```text
## Supervisor retrieved learning context
Use this as advisory memory only; explicit task instructions, git, tests, and logs are more authoritative.
```

This deliberately separates retrieval/injection from enforcement. The future
policy engine may consume approved candidates for audit/rewrite decisions, but
that is a separate layer with separate approval.

## Current Implementation Status

Implemented:

- configurable curator model role
- Ollama curator adapter
- Codex curator adapter
- advisory command-repair candidate generation
- validation warnings/errors
- validation-preserving approval path
- stable upsert/dedupe per source lesson and policy version
- candidate housekeeping service
- CLI archive/prune wrappers
- sidecar-triggered bounded housekeeping
- DB-backed controlled learning retrieval/injection for worker context
- terminal policy engine audit mode for approved command-repair policies

Not implemented yet:

- backend HTTP API routes
- dashboard/control-plane UI
- command rewrite/block enforcement
- policy-engine metrics
- memory wiki promotion/storage
- dreaming/offline synthesis phase
- hot/warm/cold memory tiering
- terminal policy enforcement from approved clean candidates

## Spec Kit Roadmap

The remaining runtime learning work is now captured as a Spec Kit feature:

- `specs/001-learning-memory-runtime/spec.md`
- `specs/001-learning-memory-runtime/plan.md`
- `specs/001-learning-memory-runtime/tasks.md`

The implementation sequence is:

1. Supervisor orchestration protocol with Spec Kit gating, packet schemas,
   prompt templates, worker dispatch gates, validation gates, and session
   summaries.
2. Learning judge with strict schema and fail-closed approval.
3. SQLite-backed runtime event bus for asynchronous learning signals.
4. Hybrid metadata/lexical/vector/graph retrieval with tiered hot/warm/cold
   advisory injection.
5. Memory wiki compiler for durable evidence-backed claims.
6. Dreaming phase for proposal-only offline synthesis.
7. Learning job observability through CLI/API/dashboard surfaces.
8. Future enforcement only after judge and operator approval.

The Spec Kit constitution for this work is `.specify/memory/constitution.md`.
It makes the separation boundary explicit: raw events, curator candidates,
judge decisions, approved memory, wiki knowledge, dreaming proposals, and
enforcement policies remain separate layers with explicit promotion paths.

## Supervisor Orchestration Protocol

For non-trivial implementation work, Hermes should not directly jump from user
request to worker execution. The supervisor first creates structured packets and
preserves the work through Spec Kit and git:

```text
user/dashboard request
  -> supervisor intake
  -> clarification if required
  -> task classification
  -> advisory memory packet retrieval
  -> supervisor task packet
  -> Spec Kit planner packet
  -> numbered branch/worktree and Spec Kit artifacts
  -> bounded worker delegation packet
  -> worker result
  -> supervisor validation report
  -> session summary and learning writeback
```

Prompt templates guide the model, but runtime packet validation enforces the
protocol. A worker dispatch is invalid without repo, branch/worktree, objective,
constraints, owned files, validation commands, memory packet, and return schema.
A non-trivial task cannot be marked complete without validation evidence,
Spec Kit/git preservation status, and a session summary.

The role model is intentionally provider-neutral:

- supervisor owns user conversation, routing, approval, validation, and final
  response
- planner/Spec Kit creator uses the strongest configured reasoning model
- implementation workers can be Claude Code Sonnet, Minimax via Claude Code,
  DeepSeek TUI, Cursor, Codex, or another configured worker
- judge/reviewer should be separate from the implementation worker when
  practical

Spec Kit may be skipped only for read-only investigation, trivial local fixes,
explicit user opt-out, or emergency debugging. The skip reason is recorded.

### Foundation Modules

The first implementation slice adds only deterministic control-plane pieces:

- `hermes_cli/runtime_packets.py` defines packet schemas and validation gates
- `hermes_cli/runtime_templates.py` loads required supervisor/worker prompt
  templates from `hermes_cli/runtime_templates/`
- `hermes_cli/learning_jobs.py` persists background job records in
  `hermes_learning_jobs`
- `supervisor.runtime_orchestration`, `supervisor.learning_judge`,
  `supervisor.learning_bus`, `supervisor.memory_tiers`, and
  `supervisor.learning_jobs` config blocks define defaults

These modules do not dispatch workers yet. They establish the runtime contracts
that future orchestration, judge, bus, retrieval, wiki, and dreaming slices must
use.

The first orchestration CLI surface is packet/gate oriented:

- `hermes runtime task init --request ... --json`
- `hermes runtime speckit plan --task-id ... --request ... --repo-id ... --branch-name ... --json`
- `hermes runtime delegate --task-id ... --worker ... --repo-id ... --branch-name ... --worktree-path ... --objective ... --owned-file ... --validation-command ... --memory-packet-id ... --json`
- `hermes runtime validate --task-id ... --feature-dir ... --branch-name ... --json`

These commands create or validate protocol artifacts. They do not yet spawn
planners, workers, or reviewers. Task initialization now creates a compact
memory packet through the supervisor memory router unless the caller passes
`--no-memory-packet`.

## Supervisor Convergence Control Plane

The supervisor protocol prevents bad dispatch and bad completion, but long
running work also needs convergence controls. A worker can drift, loop, stop
heartbeating, or repeatedly fail validation. That cannot be solved by prompt
instructions alone. It needs a durable task ledger and deterministic override
rules.

The durable authority chain should be:

```text
supervisor task ledger
  -> worker lease
  -> heartbeat / progress events
  -> loop and staleness detector
  -> recovery packet
  -> supervisor override action
  -> reassignment or escalation
  -> validation report
  -> session summary
```

Each delegated task should track:

- objective and success criteria
- task packet, planner packet, worker packet, and Spec Kit artifact refs
- repo, branch, worktree, owned files, and current git/diff refs
- active worker, lease owner, lease expiry, and heartbeat timestamp
- retry count, retry budget, and elapsed runtime
- progress signature from git/test/log deltas
- repeated command/error signatures
- validation status and failed validation evidence
- memory packet used
- recovery packet history and override action history

Worker execution is disposable. The durable truth is the supervisor task
ledger, Spec Kit artifacts, git/worktree evidence, memory packets, validation
reports, and recovery packets. If a worker stalls, the task is reclaimed; the
worker does not own the task forever.

Default override rules should be deterministic:

```text
if heartbeat stale > heartbeat_timeout:
  mark lease stale
  create recovery packet
  reclaim task

if same error signature repeats >= max_repeated_errors:
  stop retry loop
  create recovery candidate
  replan or escalate

if no git/test/progress delta across no_progress_window:
  request worker status
  if still no useful progress, reclaim and reassign

if validation fails after retry_budget:
  escalate to stronger planner/reviewer or alternate worker
  preserve failed validation evidence

if worker violates constraints:
  revoke task ownership
  quarantine output
  require supervisor/operator review
```

Reassignment uses a recovery packet instead of raw transcript replay:

```text
original objective
  + Spec Kit refs
  + previous worker packet
  + partial diff/log summary
  + failed commands and validation evidence
  + memory packet used
  + blocker summary
  + recommended next action
  -> next worker
```

The fallback order is configurable. A typical policy is:

```text
Codex planner/reviewer
  -> Claude Code Sonnet implementation
  -> DeepSeek TUI fallback
  -> Minimax/Cursor fallback
  -> Codex recovery review
```

This layer is also where `/goal` must be constrained. `/goal` is a session
continuation mechanism, not task authority. It may enqueue continuation prompts
for an already-authorized task, but it must not override lease ownership,
reclaim decisions, blocked state, reassignment, Spec Kit requirements, or
validation-gated completion.

The convergence layer should publish learning events for stale leases,
repeated-error loops, no-progress loops, failed validations, reassignments, and
successful recoveries. Those events can later feed the memory wiki, training
corpus, and dreaming proposals without giving any of those layers direct
control over live execution.

## Learning Judge Boundary

The learning judge is a separate auxiliary-model approval gate for proposed
meta-learning candidates. It runs after curator/rollup candidate creation and
before any candidate can be treated as trusted supervisor guidance.

```text
raw event / memory record
  -> curator or deterministic rollup proposes candidate
  -> learning judge emits strict JSON decision
  -> candidate becomes approved, rejected, or needs_human
  -> operator/policy may later allow enforcement
```

The judge output schema is intentionally narrow:

- `candidate_id`
- `decision`: `approve`, `reject`, or `needs_human`
- `confidence`
- `rationale`
- `risk_flags`
- `allow_enforcement`

Malformed judge output is rejected by strict parsing. If the judge model times
out or is unavailable, Hermes fails closed by escalating the candidate to human
review rather than approving it.

The CLI surface is:

- `hermes memory judge-run --json`

The default config uses `supervisor.learning_judge.provider: codex` and
`supervisor.learning_judge.model: codex`. This keeps curation/judging separate
from the primary chat model. Judge approval remains advisory: config writes or
active enforcement require a later operator-approved policy path. The default
`allow_enforcement_approval: false` prevents judge output alone from applying
runtime policy.

## Durable Learning Event Bus

Hermes uses a local SQLite event bus for runtime learning events that should
survive process restarts without introducing Kafka or another service into the
single-VM deployment. The first bus table stores:

- topic
- tenant, repo, and task scope
- payload JSON
- idempotency key
- queued, leased, consumed, or dead status
- lease owner and lease expiry
- attempt counters and max retry limit

The CLI surface is:

- `hermes memory bus publish --topic ... --payload-json ... --json`
- `hermes memory bus list --topic ... --status ... --json`
- `hermes memory bus consume --topic ... --consumer ... --ack --json`

Runtime publication is best-effort. Terminal command policy audit events,
learning rollup candidate events, and policy reconciliation events publish to
the bus, but failures are swallowed so command execution and learning sidecars
do not block on observability. Consumers lease events with expiry, so stale
leases can be reclaimed after restart. Events that exceed retry limits move to
`dead` rather than looping forever.

This bus is intentionally not the memory wiki or dreaming layer. It is the
durable event transport that those later layers can consume.

## Tenant-Scoped Observability And Drilldown

Observability must be tenant-scoped from the first implementation. A useful
operator view is not just a raw job table; it is a filtered task/job ledger with
line-item drilldown:

```text
tenant selector
  -> repo filter
  -> job/task list
  -> line-item detail drawer
  -> evidence bundle
  -> optional read-only Ask analysis
```

The lean list view should show:

- tenant
- repo
- job/task id
- task description
- status
- active worker or agent
- started and updated time
- blocker
- completion and validation state
- last sidecar, judge, memory, wiki, dreaming, or policy status

Opening a line item should lazy-load detail rather than bloating the list:

```text
Overview | Agents | Spec Kit | Memory | Validation | Events | Ask
```

The detail evidence bundle should include refs, not raw transcripts:

- original task request or compact task summary
- supervisor task packet
- initial assignment and active/past agents
- planner/Spec Kit refs: `spec.md`, `plan.md`, `tasks.md`, contracts,
  quickstart, and architecture docs
- branch, worktree, commit, and diff summary refs
- worker delegation packets and worker results
- validation commands, results, output hashes, and blockers
- memory packet, approved memory, wiki claims, dreaming proposals, candidates,
  and policy audit refs
- sidecar events, learning jobs, recovery packets, and override actions
- final/session summary when available

The Ask tab is a scoped analysis feature, not a general chat. Its flow is:

```text
operator question about one line item
  -> build tenant/repo/task-scoped evidence bundle
  -> optionally query repo in read-only mode
  -> call analysis LLM with compact evidence
  -> return analytical answer with citations
```

Guardrails:

- tenant and repo filters are mandatory unless the operator has explicit
  cross-tenant permission
- repository access is read-only by default
- evidence bundles exclude raw logs, raw transcripts, and secret-looking values
- answers must cite task ids, job ids, file refs, commit refs, validation refs,
  memory ids, or event ids
- the Ask path cannot mutate tasks, repo files, config, memory, wiki, dreaming
  proposals, candidates, or policies

This keeps the first dashboard lean while preserving the backend capability to
answer analytical questions about a specific task or job.

Implemented Phase 8 surfaces:

- `hermes memory jobs list/status --json` exposes filtered learning job records
  by tenant, repo, task, worker, job type, status, date window, and blocker text.
- `hermes memory observe list --json` returns dashboard line-item DTOs for
  learning jobs and memory/policy candidates. The list shape is intentionally
  compact so large tenants can page through active and historical work.
- `hermes memory observe detail <line_item_id> --json` builds a scoped evidence
  bundle from refs: task summary, assignment metadata, Spec Kit refs, branch
  refs, validation refs, memory refs, event refs, and artifact refs.
- `hermes memory observe ask <line_item_id> --question ... --json` returns a
  read-only scoped analysis result. The deterministic fallback can answer from
  the evidence bundle without a model; a future backend can inject an analysis
  LLM while preserving the same no-mutation contract.
- Dashboard plugin endpoints under `/api/plugins/kanban/observability/...`
  expose the same list, detail, and Ask DTOs for a lean tenant/repo/task view.

The implementation deliberately treats dashboard tabs as DTO groups rather than
frontend-heavy screens: Overview is the line item, Agents/Spec Kit/Memory/
Validation/Events are lazy evidence-bundle collections, and Ask is a separate
read-only analysis response. This keeps observability cheap while leaving room
for a richer UI later.

## Hybrid Memory Retrieval

Hermes should not use pure vector RAG for operational memory. Vector similarity
is useful, but scope and evidence are more important than semantic closeness.
The retrieval pipeline is:

```text
TaskRetrievalQuery
  -> hard metadata filters
  -> lexical search for exact identifiers
  -> vector search over eligible compact memory documents
  -> graph expansion over eligible relationships
  -> rerank/scoring
  -> compact MemoryPacket
```

Hard filters run before vector similarity. They exclude non-approved memory,
missing evidence, wrong tenant/repo/machine scopes, archived/rejected status,
and secret-unsafe content. Vector search only ranks eligible compact memory
documents; it never makes a memory trusted by itself.

The first implementation should stay local-first:

- SQLite metadata tables for scope, task type, tool, signatures, status,
  confidence, tier, and timestamps
- SQLite FTS5 for lexical matches on commands, flags, files, branches, tools,
  providers, models, and error signatures
- optional local vector backend such as `sqlite-vec`, `sqlite-vss`, or LanceDB
- SQLite graph node/edge tables before considering Neo4j or another graph
  service

Graph edges explain why memory applies:

- memory applies to tenant/repo/machine/tool/task type
- memory avoids an error signature
- memory recommends a success signature or action
- memory derives from an event or was promoted into a wiki claim/policy

Every retrieval run should be auditable: query features, hard filters, lexical
candidates, vector candidates, graph paths, final score features, and packet
output are recorded for later inspection.

The first implementation lands the local scaffolding:

- `hermes_cli/memory_retrieval.py` classifies task queries, normalizes
  candidate metadata, scores relevance, emits retrieval-run audit fields,
  builds compact advisory packets, and records outcome feedback.
- `hermes_cli/memory_index.py` stores local metadata and lexical/vector
  placeholders in SQLite. Vector matching is disabled as a backend by default
  and cannot bypass hard tenant, repo, status, or evidence filters.
- `hermes_cli/memory_graph.py` stores node/edge relationships so later
  retrieval can explain why a memory applies to a tenant, repo, tool, task
  type, error signature, or success signature.
- `retrieve_learning_context` now uses structured retrieval by default and
  returns both compact candidates and a packet header that clearly marks memory
  as advisory.

Hot/warm/cold tiers are currently computed from candidate age and confidence.
Hot means recent operational memory, warm means usable lower-confidence memory,
and cold means durable high-confidence or old memory. Outcome feedback nudges
candidate confidence up for helpful memory and down for irrelevant or harmful
memory. Deterministic command-repair memories can be escalated into proposed
policy candidates, but they still require judge/operator approval before
runtime enforcement.

## Why This Shape

One-off failure fixes do not scale. Hermes needs reusable machinery:

- runtime captures exact evidence
- curator generalizes offline
- validators reject unsupported claims
- approval keeps policy changes auditable
- enforcement uses data, not raw LLM prose

This lets small local models like Ollama `gemma2:2b` do cheap background
curation while stronger providers such as Codex or Cerebras GPT-OSS can be used
for higher-quality policy synthesis when configured.

## Memory Wiki And Dreaming Roadmap

The memory wiki is the durable knowledge layer above raw events and learning
candidates. Raw events are too noisy to retrieve directly at large scale, and
candidates are still operational suggestions. Wiki claims normalize approved,
evidence-backed memory into stable knowledge records that can feed future
lexical, vector, and graph indexes.

The intended flow is:

```text
raw runtime events
  -> learning bus
  -> rollup / curator
  -> proposed candidates
  -> judge / operator approval
  -> approved memory
  -> memory wiki claims
  -> retrieval index / graph index / future training corpus
  -> task-specific memory packets
  -> supervisor / worker orchestration
```

A candidate may say:

```text
Prefer direct Claude invocation after worker-router Claude failures.
```

A wiki claim should be more normalized and scoped:

```text
Claim:
On the AWS Linux Hermes VM, Claude Code direct CLI invocation with
`claude --model sonnet -p` is more reliable than `worker-router claude`
when the wrapper emits argument parsing failures.

Evidence:
- approved candidate ids
- learning event ids
- command audit ids
- successful command result

Scope:
tenant=atlas, repo=hermes-agent, tool=claude-code, platform=aws-linux

Confidence:
0.91
```

At scale, the wiki prevents thousands of repeated orchestrations from creating
thousands of duplicate prompt memories. It provides stable deduplicated claims,
attached evidence, explicit scope, confidence, and safety metadata. That makes
retrieval cleaner across tenants, repositories, tools, machines, providers,
models, task types, error signatures, and success signatures.

The wiki should feed both retrieval indexes:

- Vector index: compact claim text, summary, task type, tool, failure pattern,
  success pattern, and evidence summary.
- Graph index: claim relationships such as `APPLIES_TO tenant/repo/tool`,
  `OBSERVED_ON machine/platform`, `AVOIDS_ERROR error_signature`,
  `RECOMMENDS_ACTION command/playbook`, and `SUPPORTED_BY event/candidate`.

Dreaming is separate. It is an offline synthesis phase that reads wiki claims,
unresolved candidates, repeated failures, job histories, policy audits, and
worker outcomes. It emits proposal-only records such as new playbooks, tests,
routing changes, cleanup candidates, or policy ideas. Dreaming output must not
be injected into prompts, applied to config, or enforced directly. It must pass
judge and operator gates before it can affect runtime behavior.

Dreaming should be service-driven by default once enabled. The production
trigger is the learning sidecar, not the foreground chat loop:

```text
learning sidecar tick
  -> rollup
  -> monitor
  -> reconcile
  -> housekeeping
  -> wiki compile if due
  -> dreaming run if enabled and due
  -> judge proposal/candidate queues if enabled
```

Manual CLI exists for smoke tests, debugging, and operator-triggered one-offs:

```bash
hermes memory dream run --json
hermes memory dream status --json
```

The sidecar must treat dreaming as a bounded background block. It records a
learning job, publishes bus events, and returns dreaming metrics, but rollup,
monitoring, reconciliation, and housekeeping must continue if dreaming fails or
times out. Foreground chat, terminal execution, and worker delegation must never
wait on dreaming.

Default config should keep dreaming disabled until validators and gates are
installed:

```yaml
supervisor:
  dreaming:
    enabled: false
    interval_seconds: 3600
    run_on_start: false
    allow_llm: true
    provider: codex
    model: codex
    timeout_seconds: 300
    max_proposals_per_run: 10
    evidence_window: 100
    allow_cross_tenant: false
    allow_policy_proposals: true
    require_judge: true
    require_operator_approval: true
```

The long-term training-data value comes from this separation. Raw transcripts
and logs are not appropriate proprietary training data. The useful substrate is
curated records with:

- goal and task type
- tenant/repo/platform/tool scope
- failure signature
- successful action
- evidence references
- confidence
- approval provenance
- safety metadata such as `secret_safe` and cross-tenant shareability

Those records can support future AGI-centric model training without collapsing
tenant boundaries or treating speculative proposals as operational truth.

The authority chain remains:

```text
wiki claim
  -> retrieved into task packet as advisory context
  -> deterministic high-confidence memory may become a policy candidate
  -> judge reviews
  -> operator approves
  -> policy engine audits or enforces
```

Memory wiki claims are therefore a retrieval and training substrate, not direct
runtime authority.

## Migration Intelligence Training Corpus

For large-scale private-repo migration, the useful corpus is not a dump of
chat logs or terminal output. The useful corpus is structured migration
intelligence: evidence-backed records that connect an old repo state, a target
architecture, the attempted work, failures, repairs, and validation evidence.

The canonical training unit should be:

```text
migration task
  -> source repo state
  -> target repo state or desired architecture
  -> Spec Kit plan
  -> agent actions
  -> failures encountered
  -> fixes applied
  -> validation evidence
  -> durable lesson
  -> reusable policy / playbook / test
```

Each export record should preserve references, not raw private data:

- source repository id, branch, commit, language/framework/dependency profile,
  and architecture summary
- target repository id, branch, commit, desired runtime, desired architecture,
  and validation strategy
- Spec Kit artifact refs such as `spec.md`, `plan.md`, `tasks.md`, contracts,
  and architecture docs
- task id, worker id, worker model, tool calls, and bounded action summaries
- before/after commit refs, changed-file summaries, redacted diff hashes, and
  optional redacted patch excerpts
- failure signature, bad action, root cause, successful repair signature, and
  successful action summary
- validation command refs, validation output hashes, completion evidence, and
  any required manual review refs
- safety metadata: redaction status, secret-safety status, tenant boundary,
  cross-tenant shareability, approval provenance, and export status

The first dataset families should be:

- `repo_migration_plan`: repo facts and goal -> high-quality migration plan
- `migration_failure_repair`: task context plus failed action/error evidence
  -> correct repair
- `before_after_diff`: legacy implementation plus target implementation,
  redacted diff, reasoning, tests, and lesson
- `validation_recipe`: change type -> required checks, tests, logs, and
  completion evidence
- `architecture_pattern`: repo structure, dependencies, and files ->
  architecture summary
- `policy_playbook`: repeated lesson plus evidence -> reusable playbook,
  advisory, audit, or enforceable policy candidate

The strongest record for future distilled coding models is:

```text
legacy code context
  + desired target behavior
  + agent mistake
  + corrected diff
  + validation evidence
  + scoped lesson
```

This creates training data for planning, repair, validation discipline, and
drift resistance. It also produces regression anchors for future models:

- canonical migration tasks
- known failure cases
- golden corrected diffs
- required validation evidence
- forbidden bad fixes
- tenant-scope rules
- regression prompts for release evaluation

The export path is intentionally gated:

```text
wiki claim
  -> training corpus candidate
  -> redaction and safety validator
  -> judge review
  -> operator approval
  -> dataset export
```

Raw transcripts, raw logs, unredacted terminal output, secrets, and speculative
dreaming proposals must not enter the training corpus. Dreaming may propose a
training candidate, but only approved wiki claims or approved memory can be
materialized into exportable records.

## Native Goal Loop Relationship

Hermes also has a native `/goal` mechanism in `hermes_cli/goals.py` and
gateway wiring. It is a per-session continuation controller, not a memory
compiler and not a dreaming sidecar.

The goal mechanism works as follows:

```text
operator sets /goal
  -> GoalState is persisted in SessionDB state_meta as goal:<session_id>
  -> normal agent turn runs
  -> auxiliary goal_judge evaluates final response
  -> if done: mark goal done
  -> if not done and budget remains: enqueue a normal continuation user prompt
  -> if budget exhausted or judge repeatedly emits malformed output: pause
```

Important properties:

- The continuation is a normal user-message turn, not a system-prompt mutation.
- The goal loop does not swap toolsets or bypass runtime approvals.
- Goal judge failures are fail-open to continuation, with parse-failure
  auto-pause after repeated malformed judge output.
- User messages preempt queued continuation prompts.
- `/subgoal` adds explicit completion criteria that the judge must verify.

This can help supervisor orchestration as a native progress loop. For example,
the supervisor may use a goal to continue a long Spec Kit implementation until
validation evidence and session summary criteria are met. It should not replace
the supervisor protocol: task packets, planner packets, worker delegation
packets, validation reports, session summaries, memory packets, judge/operator
approval, and policy boundaries remain the authoritative orchestration records.

Dreaming is different. Dreaming is offline pattern synthesis over wiki claims,
events, candidates, job history, policy audits, and worker outcomes. It emits
proposal records only. A goal loop may keep working on an already-authorized
task; dreaming may only propose future work or policy ideas. Dreaming output
must not be queued as a goal, injected into worker context, or applied as
policy unless it passes the normal judge/operator gates.

## Dreaming Risk Mitigations

Dreaming is useful because an LLM can synthesize patterns that deterministic
rules may miss, but the LLM output is not trusted. The implementation must
layer programmatic controls around the model.

Dreaming input should be evidence-only:

- wiki claim ids
- candidate ids
- learning event ids
- job summaries
- policy audit ids
- redacted compact excerpts only when needed

Dreaming output must use a strict schema. At minimum:

```json
{
  "proposal_type": "playbook|test|routing|policy|cleanup|architecture",
  "summary": "...",
  "rationale": "...",
  "evidence_refs": ["..."],
  "scope": {},
  "risk": "low|medium|high",
  "trigger": "manual|sidecar_interval|service_start",
  "requested_action": "...",
  "runtime_effect": false
}
```

Malformed output is rejected. Before persistence, deterministic validators
must check:

- every evidence ref exists
- no raw secrets or secret-looking values are present
- no destructive command is proposed without high-risk escalation
- no unsupported tenant/repo/platform/tool scope broadening
- no cross-tenant sharing unless explicitly allowed
- no duplicate proposal already exists for the same type, scope, and summary
- no config mutation or enforcement request bypasses policy proposal status
- no direct wiki write, training export, goal queue, or prompt injection request
- rationale and risk are present

Dreaming proposals must be stored separately from approved memory, wiki claims,
and policy candidates. Retrieval must not read proposal storage. The policy
engine must not read proposal storage. Worker context injection must not read
proposal storage. Proposal lifecycle is:

```text
proposed
  -> judged
  -> approved/rejected/archived
```

Only a later conversion step can produce approved memory, a wiki update, a
validation recipe, a playbook, or a policy candidate. That conversion must go
through the same judge/operator boundary as the rest of the learning system.

Default scope should be narrow:

```text
tenant=current
repo=current
platform=current
tool=current
cross_tenant_shareable=false
```

Global or cross-tenant lessons require explicit approval. Confidence and
freshness must decay when claims become stale or receive negative feedback.
Every transition records who/what proposed it, evidence refs, judge decision,
operator decision, timestamps, config version, and whether any runtime effect
was allowed.

Dreaming should also have kill switches:

```yaml
supervisor:
  dreaming:
    enabled: false
    interval_seconds: 3600
    run_on_start: false
    allow_llm: true
    provider: codex
    model: codex
    timeout_seconds: 300
    allow_cross_tenant: false
    allow_policy_proposals: true
    require_judge: true
    require_operator_approval: true
    max_proposals_per_run: 10
    evidence_window: 100
```

Negative tests must prove proposals are not injected, indexed as approved
memory, queued as goals, applied to config, used by the policy engine, or
allowed to cross tenant boundaries by default.
