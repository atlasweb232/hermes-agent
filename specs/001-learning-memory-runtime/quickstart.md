# Quickstart: Runtime Learning Memory Framework

## 1. Run Existing Safety Tests

```bash
pytest tests/hermes_cli/test_supervisor_memory.py tests/hermes_cli/test_policy_engine.py tests/hermes_cli/test_config.py -q
```

## 2. Run The Sidecar Once

```bash
hermes memory sidecar --once --json
```

Expected: rollup, monitor, policy, and housekeeping blocks complete without foreground chat involvement.

## 3. Run Learning Judge Once

```bash
hermes memory judge-run --json
```

Expected: eligible proposed candidates receive approve, reject, or needs-human decisions. Malformed judge output fails closed.

## 4. Verify Dreaming Is Default Disabled

```bash
hermes memory sidecar --once --json
```

Expected: dreaming is skipped unless `supervisor.dreaming.enabled=true`. When implemented and enabled, dreaming runs from the sidecar only when its interval is due. Manual `hermes memory dream run --json` is for smoke tests and operator one-offs.

## 5. Publish And Consume A Runtime Event

```bash
hermes memory bus publish --topic runtime.policy_audit --json-payload '{"schema_version":1,"source":"quickstart","summary":"audit smoke"}'
hermes memory bus consume --consumer quickstart --once --json
```

Expected: event is consumed or failed with structured metadata.

## 6. Verify Retrieval Injection

```bash
python - <<'PY'
from hermes_cli.supervisor_memory import retrieve_learning_context
print(retrieve_learning_context(None, query="ask claude code two plus two"))
PY
```

Expected: only approved, scoped, evidence-backed advisory memory is returned.

## 7. Verify No Enforcement

```bash
python - <<'PY'
from hermes_cli.policy_engine import evaluate_command_policy
print(evaluate_command_policy(command='worker-router claude "two plus two"'))
PY
```

Expected: audit metadata may be present, but `effective_command` remains unchanged unless future enforcement mode is explicitly enabled with judge and operator approval.
