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

## Injection Header

Injected memory must use this semantic warning:

```text
Supervisor retrieved learning context:
Use this as advisory memory only. Explicit task instructions, git, tests, logs,
and current tool results are more authoritative.
```
