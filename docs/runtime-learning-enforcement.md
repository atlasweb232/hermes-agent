# Runtime Learning Enforcement

This branch records how the VM Hermes runtime enforces the learning architecture from the atlas `128-hermes-agent-platform` spec.

## Runtime Branch

- VM repo: `/home/rakib/.hermes/hermes-agent`
- Runtime branch: `runtime-learning-enforcement`
- Base learning port: `memory-framework-on-current-main`

## Enforced Today

The active enforcement path is DB-backed and task-event driven:

1. Kanban task lifecycle events are captured for terminal outcomes: `completed`, `blocked`, `gave_up`, `crashed`, `timed_out`, `spawn_failed`, `reclaimed`, and `completion_blocked_hallucination`.
2. Captured events are mirrored into `state.db` as `hermes_memory_records` rows with `kind = task_outcome` plus linked `hermes_memory_evidence` rows.
3. The learning sidecar runs `rollup -> monitor -> reconcile` and records each pass in `hermes_learning_runs`.
4. Useful records become `hermes_meta_candidates` with status `proposed` unless promotion policy later approves them.
5. Promotion and auto-apply are policy gated. Auto-apply remains disabled by default.

## Persistent Supervisor Constitution

The VM stores persistent supervisor rules in `/home/rakib/.hermes/SOUL.md`. Hermes loads this file into the system prompt for new sessions. The constitution block tells the supervisor to preserve master instructions, prefer git/tests/logs over memory, delegate with bounded task packets, persist outcomes, and avoid automatic policy-changing actions without explicit approval.

## Learning Sidecar Service

The VM installs a user service:

- unit: `hermes-learning-sidecar.service`
- command: `python -m hermes_cli.main memory sidecar --interval 300`
- home: `/home/rakib/.hermes`
- repo: `/home/rakib/.hermes/hermes-agent`

The service keeps the learning loop active after SSH disconnects because user linger is enabled for `rakib`.

## Manual Checks

```bash
systemctl --user status hermes-learning-sidecar
hermes memory monitor --json
hermes memory sidecar --once --json
python3 - <<PY
import sqlite3
from pathlib import Path
conn = sqlite3.connect(Path.home() / ".hermes/state.db")
cur = conn.cursor()
for table in ["hermes_memory_records", "hermes_memory_evidence", "hermes_learning_runs", "hermes_meta_candidates"]:
    print(table, cur.execute("select count(*) from " + table).fetchone()[0])
PY
```

## Still Not Enforced

The full memory-wiki compiler and dreaming/DGM loop are not part of this enforcement pass. They remain separate follow-up work after the task outcome capture and learning sidecar are proven with the branch-118 validation test.
