# Runtime Learning Release Readiness

Branch: `132-learning-memory-runtime`

Validation date: 2026-05-23

Validated HEAD: `6ff6b161d`

## Summary

Production-closure validation requires review for the runtime-learning branch.

| Gate Group | Status | Evidence |
| --- | --- | --- |
| production smoke | passed | 13 passed, 0 failed |
| runtime impact | runtime_impact | foreground_blocking=False; foreground_ms=4500.0; background_ms=900.0 |
| sidecar readiness | degraded | 8 sidecar checks |
| model-role doctor | degraded | degraded roles: curator, learning_judge, goal_judge |
| cost/context | reported | cost=0.0; tokens=0; context=1800.0 |

## Production Closure Gates

| Gate | Status | Details |
| --- | --- | --- |
| runtime_failure_capture | passed | candidate_id=curadv_37a16cc1e5cce9a9 |
| codex_fallback_path | passed | fallback_worker=codex |
| curator_candidate_creation | passed | - |
| learning_judge_decision | passed | - |
| operator_approval_boundary | passed | - |
| skill_publication | passed | - |
| bounded_skill_packet | passed | - |
| harmful_feedback_demotes | passed | - |
| sidecars_non_blocking | passed | - |
| model_roles_structured | passed | - |
| notification_route | passed | - |
| runtime_impact | passed | - |
| secret_sentinel_scan | passed | - |

## Runtime Impact Evidence

| Metric | Value |
| --- | --- |
| foreground sidecar blocking | False | must remain false |
| raw worker updates in context | False | must remain false |
| raw logs loaded | False | must remain false |
| raw transcripts loaded | False | must remain false |
| foreground latency ms | 4500.0 | task-visible latency |
| background sidecar ms | 900.0 | async latency attribution |
| context admitted tokens | 1800.0 | supervisor context budget |
| offloaded worker events | 0 | stored as refs |

## Sidecar Status

| Sidecar | Status | Mode | Non-blocking | Details |
| --- | --- | --- | --- | --- |
| curator | degraded | oneshot | False | lock_held, runner=not_run, budget=allowed |
| learning_judge | degraded | oneshot | False | lock_held, runner=not_run, budget=allowed |
| dreaming | ready | oneshot | False | runner=ready_no_runner, budget=allowed |
| wiki | ready | oneshot | False | runner=ready_no_runner, budget=allowed |
| bus_consumer | degraded | oneshot | False | lock_held, runner=not_run, budget=allowed |
| sync | ready | oneshot | False | runner=ready_no_runner, budget=allowed |
| progress_summarizer | degraded | oneshot | False | lock_held, runner=not_run, budget=allowed |
| housekeeping | ready | oneshot | False | runner=ready_no_runner, budget=allowed |

## Cost And Context Totals

| Metric | Value |
| --- | --- |
| estimated cost usd | 0.0 |  |
| prompt/input tokens | 0 |  |
| completion/output tokens | 0 |  |
| run count | 0 |  |

## Command Evidence

| Command | Status | Summary |
| --- | --- | --- |
| python3 -m hermes_cli.main runtime production-smoke --tenant-id production-smoke-tenant --repo-id hermes-agent --artifact-root /tmp/hermes-production-closure/artifacts --json | passed | execution_mode=deterministic_local; elapsed_ms=239; gates=13 |
| python3 -m hermes_cli.main runtime impact --tenant-id tenant-a --repo-id repo-a --json | runtime_impact | foreground_blocking=False; raw_logs_loaded=False; raw_transcripts_loaded=False |
| python3 -m hermes_cli.main runtime sidecars readiness --run-once --json | degraded | checked=8; ready=4; degraded=4; foreground_blocking=False |
| python3 -m hermes_cli.main config role doctor --roles curator,learning_judge,goal_judge,code_review_judge --json | degraded | roles_checked=4; secrets_printed=False |
| python3 -m hermes_cli.main runtime costs status --artifact-root /tmp/hermes-production-closure/artifacts --json | reported | run_count=0; total_estimated_cost_usd=0.0; total_tokens=0 |
| python3 -m hermes_cli.main runtime benchmark azure-smoke --json | skipped | live_azure_smoke_not_opted_in; deterministic_fixture=passed |

## Known Blockers

- Sidecar readiness degraded in one-shot local smoke: curator: lock_held; learning_judge: lock_held; bus_consumer: lock_held; progress_summarizer: lock_held
- Model-role doctor degraded: curator: missing_auth; learning_judge: missing_auth; goal_judge: missing_auth
- missing_azure_live_smoke_configuration
- live_azure_smoke_not_opted_in
- Live Azure/provider smoke was not opted in; deterministic local closure smoke was used.

## Release-readiness conclusion

The branch is not fully production-closure-ready until the failed gates or known blockers above are resolved. Enforcement must remain disabled.
