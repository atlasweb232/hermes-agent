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
