# Event Bus Contract

## Topics

- `runtime.tool_result`: command/tool output summary and status
- `runtime.task_outcome`: task completion, blocker, failure, or recovery result
- `runtime.policy_audit`: policy engine audit match or skip result
- `learning.candidate.proposed`: candidate created by rollup or curator
- `learning.candidate.validated`: candidate passed structural validation
- `learning.candidate.judged`: judge decision recorded
- `learning.memory.approved`: approved memory ready for retrieval
- `learning.wiki.claim`: wiki claim created or updated
- `learning.dreaming.proposal`: dreaming proposal emitted

## Payload Rules

- Payloads must be JSON objects.
- Payloads must be secret-redacted before persistence.
- Payloads must include source, timestamp, and schema version.
- Payloads should include evidence pointers, not raw transcript bodies.

## Consumer Rules

- Consumers acquire a lease before processing.
- Consumers must update attempts and errors on failure.
- Consumers must be idempotent for duplicate event delivery.
- Consumers must mark events failed after retry limit.
- Consumers must not block foreground chat, terminal, or delegation.
