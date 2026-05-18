# Worker Progress And Supervisor Context Gate Contract

## Purpose

Long-running worker streams must not consume supervisor context. Hermes must
store raw worker output durably, produce compact checkpoint packets at decision
boundaries, and inject only bounded typed packets into supervisor context.

This contract is immediate-priority because uncontrolled worker progress streams
can exhaust the supervisor context window, erase master instructions, and cause
task drift.

## Authority Split

```text
worker runtime wrapper
  -> emits mandatory raw/progress events
  -> writes stdout/stderr/artifacts by reference
  -> updates heartbeat and attempt state

cheap progress sidecar
  -> summarizes raw events/log refs
  -> extracts checkpoints and blockers
  -> emits bounded WorkerCheckpointPacket

supervisor context gate
  -> rejects raw streams
  -> accepts only typed bounded packets
  -> injects decision-boundary packets only
```

## Mandatory Worker Runtime Events

The worker dispatcher/wrapper must emit these events programmatically. Worker
models may add prose, but model cooperation is not trusted for liveness.

- `worker_started`
- `worker_heartbeat`
- `worker_stream_ref`
- `worker_progress_checkpoint`
- `worker_blocked`
- `worker_degraded`
- `worker_validation`
- `worker_final`

Every event must include:

```json
{
  "event_id": "evt_...",
  "task_id": "task_...",
  "allocation_id": "alloc_...",
  "attempt_id": "attempt_...",
  "worker_id": "claude-code",
  "repo_id": "atlasweb-mini",
  "branch": "134-atlas-email-azure-port",
  "created_at": 0,
  "artifact_refs": [],
  "store_only": true
}
```

Raw stream chunks must always set `store_only=true`.

## Supervisor Context Admission

The supervisor context gate may admit only these packet types:

- `worker_checkpoint`
- `worker_blocked`
- `worker_validation`
- `worker_final`
- `allocation_decision`
- `recovery_packet`

The gate must reject:

- raw stdout/stderr
- untyped worker prose
- full terminal transcripts
- unbounded tool output
- raw log tails
- speculative dreaming/curator proposals

## Decision Boundaries

Supervisor re-entry may happen only at decision boundaries:

1. task accepted
2. Spec Kit checkpoint created or updated
3. worker requests clarification or approval
4. worker is blocked/degraded
5. validation completed
6. final worker result submitted
7. allocator has no safe worker and must pause/escalate

Normal progress updates go to Slack/UI and observability, not supervisor prompt
context.

## Packet Budget

Each admitted packet must be bounded:

```json
{
  "packet_type": "worker_checkpoint",
  "max_chars": 2000,
  "max_evidence_refs": 12,
  "summary": "...",
  "status": "in_progress",
  "decision_needed": null,
  "evidence_refs": ["log://...", "git://...", "test://..."]
}
```

If the packet exceeds budget, Hermes must summarize or reject it before
supervisor injection.

## Cheap Progress Summarizer Sidecar

Progress summarization is sidecar work and should use the configured
`low_cost_reasoning` tier by default.

Suitable models:

- local Gemma through Ollama when available
- Cerebras-hosted `gpt-oss-120b`
- DeepSeek or MiniMax low-cost reasoning tiers

The sidecar may:

- summarize worker logs
- extract blockers
- classify timeout/empty/quota/auth/network signatures
- produce checkpoint packets
- deduplicate noisy repeated progress

The sidecar must not:

- decide task completion
- approve memory
- mutate routing policy
- change model configuration
- inject raw logs into supervisor context

## Slack/UI Streaming

Slack and dashboard streams may display worker progress, but those streams are
delivery views over the event bus/log refs. Displaying a progress chunk must not
imply it was added to supervisor context.

## Tests

Required tests:

- raw worker stream event is stored but rejected by supervisor context gate
- untyped worker prose is rejected
- bounded checkpoint packet is accepted
- oversized checkpoint is summarized or rejected
- heartbeat is emitted without model cooperation
- timeout/empty output emits `worker_degraded`
- cheap sidecar emits checkpoint without blocking foreground runtime
- Slack progress delivery does not append to supervisor chat history
- final worker result packet is mandatory before supervisor completion
