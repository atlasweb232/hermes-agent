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

This framework does not automatically rewrite terminal commands yet. The next
layer should be a generic command-repair policy engine:

```text
incoming terminal command
  -> normalize command
  -> match approved command_repair_policy candidates
  -> rewrite/block with audit metadata
```

That engine must not hardcode per-failure fixes. It should consume approved
policy data with bounded selectors and templates.

## Injection And Enforcement

The unresolved runtime issue is not memory capture or curation. It is injection
and enforcement: Hermes can store a lesson and curate a policy candidate, but the
terminal tool path must still consult approved policy before execution.

The generic policy engine should run as a terminal pre-tool step:

```text
terminal(function_args.command)
  -> command normalizer
  -> approved policy lookup
  -> selector match
  -> rewrite/block/noop decision
  -> terminal execution
  -> runtime_policy_applied audit metadata
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

Every applied policy must annotate the tool result:

```json
{
  "runtime_policy_applied": {
    "policy_id": "curpol_...",
    "source_record_id": "memrec_...",
    "action": "rewrite",
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
    enabled: false
    mode: audit
    max_rewrites_per_session: 1
    allowed_policy_types:
      - command_repair
```

`mode=audit` should log what would have happened without changing the command.
`mode=enforce` should require explicit approval of the policy-engine layer.

## Current Implementation Status

Implemented:

- configurable curator model role
- Ollama curator adapter
- Codex curator adapter
- advisory command-repair candidate generation
- validation warnings/errors
- validation-preserving approval path
- stable upsert/dedupe per source lesson and policy version

Not implemented yet:

- backend HTTP API routes
- dashboard/control-plane UI
- generic terminal policy engine
- command rewrite/block enforcement
- policy-engine metrics

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
