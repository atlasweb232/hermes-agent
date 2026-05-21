# Runtime Learning Release Readiness

Branch: `132-learning-memory-runtime`

Validation date: 2026-05-21

Validated HEAD: `352979a12`

Baseline sync:

```text
git pull --ff-only origin 132-learning-memory-runtime
Already up to date.
git rev-parse --short HEAD
352979a12
```

## Summary

Aggregate release-readiness validation passed for the runtime-learning branch.

No production code changes were required. This report is the only repository artifact created for the validation pass.

## Focused test validation

| Area | Command | Result |
| --- | --- | --- |
| setup/isolation | `python3 -m pytest -q tests/hermes_cli/test_learning_memory_setup_bookkeeping.py -o addopts=` | `1 passed in 1.02s` |
| runtime learning and memory injection | `python3 -m pytest -q tests/hermes_cli/test_runtime_memory_injection.py tests/hermes_cli/test_memory_retrieval.py tests/hermes_cli/test_task_memory_profiles.py tests/hermes_cli/test_supervisor_memory.py -o addopts=` | `52 passed in 16.02s` |
| judge/curator/dreaming | `python3 -m pytest -q tests/hermes_cli/test_learning_judge.py tests/hermes_cli/test_memory_dreaming.py tests/hermes_cli/test_curator_run.py -o addopts=` | `61 passed in 7.43s` |
| global memory/wiki/corpus remittance | `python3 -m pytest -q tests/hermes_cli/test_global_memory.py tests/hermes_cli/test_memory_wiki.py tests/hermes_cli/test_memory_wiki_backends.py tests/hermes_cli/test_mlops_corpus.py -o addopts=` | `73 passed in 12.84s` |
| production global bus | `python3 -m pytest -q tests/hermes_cli/test_global_bus_production.py tests/hermes_cli/test_learning_bus.py -o addopts=` | `14 passed in 4.50s` |
| goal allocator and self-healing | `python3 -m pytest -q tests/hermes_cli/test_goal_allocator.py tests/hermes_cli/test_self_healing_workflow.py tests/hermes_cli/test_runtime_orchestrator.py -o addopts=` | `37 passed in 7.81s` |
| feature toggles and E2E runner | `python3 -m pytest -q tests/hermes_cli/test_runtime_features.py tests/hermes_cli/test_runtime_e2e.py tests/hermes_cli/test_runtime_smoke.py -o addopts=` | `16 passed in 7.38s` |
| tenant platform | `python3 -m pytest -q tests/hermes_cli/test_tenant_platform.py -o addopts=` | `26 passed in 3.38s` |
| skill memory pipeline | `python3 -m pytest -q tests/hermes_cli/test_skill_memory.py -o addopts=` | `13 passed in 3.28s` |
| Azure deployment orchestration/hardening | `python3 -m pytest -q tests/hermes_cli/test_azure_deployment_orchestration.py tests/hermes_cli/test_platform_hardening.py -o addopts=` | `26 passed in 1.33s` |
| operator dashboard | `python3 -m pytest -q tests/hermes_cli/test_operator_dashboard.py -o addopts=` | `9 passed in 0.84s` |
| benchmark/cost/telemetry | `python3 -m pytest -q tests/hermes_cli/test_runtime_benchmark.py tests/hermes_cli/test_sidecar_models.py tests/hermes_cli/test_model_roles.py tests/hermes_cli/test_gateway_runtime_health.py -o addopts=` | `30 passed in 4.02s` |

Total focused pytest coverage in this pass: 358 passing tests.

## Representative CLI smoke validation

All CLI smoke commands were run with an isolated `HERMES_HOME=/tmp/hermes-release-readiness/home`.

| Surface | Command | Result |
| --- | --- | --- |
| memory sidecar | `python3 -m hermes_cli.main memory sidecar --once --json` | exit `0`; one sidecar tick completed with no candidates in the isolated home |
| global bus check | `python3 -m hermes_cli.main memory bus check --json --lag` | exit `0`; status `disabled`, backend `sqlite`, fallback enabled |
| dashboard status | `python3 -m hermes_cli.main dashboard --status` | exit `0`; status command completed |
| status surface | `python3 -m hermes_cli.main status --all` | exit `0`; component status rendered with redacted/missing credentials |
| feature status | `python3 -m hermes_cli.main runtime features status --json` | exit `0`; feature status JSON rendered |
| runtime E2E list | `python3 -m hermes_cli.main runtime e2e list --json` | exit `0`; listed deterministic local runtime suites |
| benchmark fixture | `python3 -m hermes_cli.main runtime benchmark run --suite /tmp/hermes-release-readiness/benchmark-suite.json --artifact-root /tmp/hermes-release-readiness/bench --json` | exit `0`; benchmark run completed in fixture mode |
| benchmark cost status | `python3 -m hermes_cli.main runtime costs status --artifact-root /tmp/hermes-release-readiness/bench --json` | exit `0`; one run reported, estimated cost `$0.038`, production gate allowed |
| Azure fake/local preflight | `python3 -m hermes_cli.main deploy preflight --target azure` | exit `0`; fake adapter preflight checks passed, SQLite fallback reported |

## Validation artifacts

Temporary local validation artifacts were written outside the repository under `/tmp/hermes-release-readiness/`:

- `validation.log`
- `cli-smoke.log`
- CLI smoke stdout/stderr captures
- fixture benchmark suite and benchmark artifacts

These files were not committed.

## Findings and failures

No test failures occurred.

No minimal code fixes were required.

Observation: `hermes dashboard --status` completed successfully, but under the Hermes terminal wrapper it reported the wrapper shell command line as a dashboard process because the command line itself contained `dashboard --status`. This did not fail the smoke check and no runtime fix was made in this report-only pass.

## Release-readiness conclusion

The branch is release-ready for the focused runtime-learning validation scope covered above. SQLite/default-local behavior, opt-in production bus behavior, memory/wiki/corpus safety boundaries, approval/dashboard surfaces, Azure fake/local deployment gates, and benchmark/cost telemetry all passed representative validation.
