# Deterministic Completion Gate Architecture

## Purpose

Hermes workers can edit files, merge branches, run tools, and summarize work, but
their natural-language summaries are not authoritative. The completion gate makes
repo state authoritative by requiring deterministic checks before the supervisor
can report delegated repository work as complete.

## Control Flow

```text
user task
  -> supervisor
  -> delegate_task worker
  -> worker returns summary
  -> completion gate runs deterministic repo checks
  -> delegate result is annotated with gate evidence
  -> final-response guard forces blocked status if gate failed
```

The model can propose completion. The gate decides whether completion is allowed.

## Enforcement Points

1. `run_agent.AIAgent._dispatch_delegate_task`

   Runs after every `delegate_task` call when
   `supervisor.completion_gate.run_after_delegate_task` is enabled. It infers the
   repository from task text or the current workspace, runs validators, and
   attaches a `completion_gate` object to the tool result.

2. `run_agent.AIAgent._apply_completion_gate_to_final_response`

   Runs before `run_conversation` returns. If the latest completion gate is
   blocked, the final answer is replaced with a deterministic blocked report.
   Success language from the worker is treated as untrusted narrative.

3. `hermes_cli.completion_gate`

   Contains the validator and response-guard implementation. It is independent
   of the model and can be unit tested without an LLM.

## Default Checks

The default gate runs:

```bash
git ls-files -u
rg -n '<<<<<<<|=======|>>>>>>>' .
git diff --check
```

The gate passes only when:

- there are no unmerged index entries
- no conflict markers are present
- `git diff --check` reports no whitespace/error markers

## Configuration

Default config:

```yaml
supervisor:
  completion_gate:
    enabled: true
    run_after_delegate_task: true
    fail_on_missing_repo: false
    required_checks:
      - git_unmerged_paths
      - conflict_markers
      - diff_check
    build_commands: []
    max_output_chars: 8000
```

Project-specific build gates can be added:

```yaml
supervisor:
  completion_gate:
    build_commands:
      - dotnet build atlas-email-desktop/src/AtlasDesktop/AtlasDesktop.csproj
```

If a build command is configured and the toolchain is missing, the build check
fails and the task is blocked. That is intentional: missing validators are a
blocked state, not a successful state.

## Worker Result Semantics

When the gate fails, Hermes rewrites successful worker entries:

```json
{
  "status": "blocked",
  "results": [
    {
      "worker_status": "completed",
      "status": "blocked",
      "error": "completion gate blocked worker success claim"
    }
  ],
  "completion_gate": {
    "status": "blocked",
    "checks": []
  }
}
```

This preserves the worker's original claim while preventing the supervisor from
treating it as truth.

## Final Response Semantics

If a worker says "done" but the gate fails, the user receives:

```text
Blocked: deterministic completion gate did not pass.

Repository: /path/to/repo
Failed checks:
- conflict_markers: failed (...)

Worker narrative was suppressed because it claimed success without passing the gate.
```

The final response may still include the original worker narrative for audit, but
it is clearly marked untrusted.

## Limitations

- Repo inference is best-effort. Hermes detects absolute git repo paths in the
  task text and falls back to `TERMINAL_CWD` or process cwd.
- Default checks are repo-integrity checks, not full product validation. Add
  `build_commands` or future validators for project-specific guarantees.
- The gate currently stores evidence in the session result/tool payload. A future
  extension should persist validation runs to state DB for dashboard and learning
  rollups.

## Why This Prevents The Observed Failure

In the failed Atlas branch test, a worker claimed conflicts were resolved while
`git status` still contained `UU` and `AA` entries and conflict markers remained.
With this gate enabled, the worker result would be rewritten to `blocked`, and
the final response guard would prevent Hermes from saying the merge was complete.
