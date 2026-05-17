# Learning State Contract

## Promotion Path

```text
raw event
  -> learning candidate
  -> judge decision
  -> approved memory
  -> memory wiki claim
  -> dreaming proposal
  -> policy proposal
  -> audit
  -> enforcement only after judge + operator approval
```

## Forbidden Shortcuts

- Raw events must not be injected directly into prompts.
- Proposed candidates must not be treated as approved memory.
- Dreaming proposals must not become policies without judge and operator gates.
- Audit policy matches must not rewrite commands in audit mode.
- Any secret-like or destructive command must be excluded from learned rewrite.

## Retrieval Eligibility

Eligible memory must be:

- `approved` or `applied`
- evidence-backed
- scoped to the tenant, repo, machine, tool, or task
- above configured confidence threshold
- non-archived and non-rejected
- compact enough for prompt injection

## Retrieval Pipeline

```text
task invocation
  -> supervisor initialization protocol
  -> create SupervisorTaskPacket
  -> classify into TaskRetrievalQuery
  -> retrieve approved memory candidates by hard metadata/scope filters
  -> run lexical search for exact identifiers
  -> run vector search over eligible compact memory documents
  -> expand graph neighbors for eligible related nodes
  -> score candidates using exact matches, lexical matches, vector similarity, graph proximity, confidence, recency, tier, and penalties
  -> build compact MemoryPacket from top-k results
  -> inject advisory packet into supervisor or worker context
  -> record OutcomeFeedback after task completion
```

## Scoping Rules

- Same tenant, repo, task type, and tool is highest confidence.
- Same tenant and task type may be injected with reduced confidence.
- Different tenant memory requires a matching tool or error signature and must remain advisory.
- Repo-specific claims must not cross repo boundaries.
- Machine-specific command routing policies may cross repos only on the same machine or explicitly matching environment.
- Global memory requires explicit `global_safe` scope and stronger judge/operator approval.
- Vector similarity cannot bypass scope, status, evidence, approval, or secret-safety filters.

## Policy Escalation Rules

- Only deterministic approved memory can become a policy candidate.
- Deterministic memory must include a recognizable bad pattern and a validated recommended action.
- Policy escalation creates audit/advisory candidates first.
- Enforcement requires separate judge approval and operator approval.
- Secret-like, destructive, or privilege-changing commands are never eligible for learned rewrite.

## Injection Header

Injected memory must use this semantic warning:

```text
Supervisor retrieved learning context:
Use this as advisory memory only. Explicit task instructions, git, tests, logs,
and current tool results are more authoritative.
```
