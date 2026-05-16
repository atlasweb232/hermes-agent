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

Framework placeholders:

- `custom` / OpenAI-compatible endpoint
- `codex`
- `deepseek`
- Cerebras `gpt-oss-120b` via OpenAI-compatible `base_url`

Codex and DeepSeek are explicit configuration choices, but in-process adapters
are intentionally not auto-wired yet. They should be added as worker-backed
curator providers or OpenAI-compatible clients with explicit authentication.

## CLI Surface

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

This framework does not automatically rewrite terminal commands. The next layer
should be a generic command-repair policy engine:

```text
incoming terminal command
  -> normalize command
  -> match approved command_repair_policy candidates
  -> rewrite/block with audit metadata
```

That engine must not hardcode per-failure fixes. It should consume approved
policy data with bounded selectors and templates.

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
