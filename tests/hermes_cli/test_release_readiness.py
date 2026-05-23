from hermes_cli.release_readiness import (
    CommandEvidence,
    ReleaseReadinessReport,
    build_release_readiness_markdown,
)


def test_t362_release_readiness_report_includes_closure_surfaces():
    markdown = build_release_readiness_markdown(
        ReleaseReadinessReport(
            branch="132-learning-memory-runtime",
            head="abc123",
            validation_date="2026-05-23",
            production_smoke={
                "status": "passed",
                "gates": [
                    {"name": "runtime_failure_capture", "status": "passed"},
                    {"name": "runtime_impact", "status": "passed"},
                ],
            },
            runtime_impact={
                "kind": "runtime_impact",
                "foreground": {
                    "foreground_sidecar_blocking": False,
                    "raw_worker_updates_in_context": False,
                },
                "latency_attribution": {
                    "foreground_ms": 100,
                    "background_sidecar_ms": 250,
                },
                "context_attribution": {
                    "context_admitted_tokens": 300,
                    "offloaded_worker_events": 4,
                },
                "cost_attribution": {"estimated_cost_usd": 0.01},
                "raw_logs_loaded": False,
                "raw_transcripts_loaded": False,
            },
            sidecar_status={
                "status": "ready",
                "mode": "oneshot",
                "foreground_blocking": False,
                "sidecars": [
                    {
                        "name": "curator",
                        "status": "ready",
                        "mode": "oneshot",
                        "foreground_blocking": False,
                    }
                ],
            },
            model_role_doctor={
                "status": "degraded",
                "diagnostics": [
                    {"role": "goal_judge", "status": "degraded"},
                ],
            },
            cost_status={
                "status": "reported",
                "totals": {
                    "estimated_cost_usd": 0.038,
                    "prompt_tokens": 189,
                    "completion_tokens": 198,
                    "run_count": 1,
                },
            },
            command_evidence=(
                CommandEvidence(
                    command="hermes runtime production-smoke --json",
                    status="passed",
                    summary="deterministic smoke passed",
                ),
            ),
            known_blockers=("live Azure smoke not opted in",),
        )
    )

    assert "## Production Closure Gates" in markdown
    assert "runtime_failure_capture" in markdown
    assert "## Runtime Impact Evidence" in markdown
    assert "foreground sidecar blocking" in markdown
    assert "## Sidecar Status" in markdown
    assert "curator" in markdown
    assert "## Cost And Context Totals" in markdown
    assert "0.038" in markdown
    assert "## Known Blockers" in markdown
    assert "live Azure smoke not opted in" in markdown


def test_t362_release_readiness_report_redacts_secret_like_values():
    markdown = build_release_readiness_markdown(
        ReleaseReadinessReport(
            branch="branch",
            head="head",
            validation_date="2026-05-23",
            production_smoke={
                "status": "passed",
                "gates": [
                    {
                        "name": "secret_scan",
                        "status": "passed",
                        "access_token": "sk-should-not-appear",
                    }
                ],
            },
            runtime_impact={"foreground": {}, "latency_attribution": {}, "context_attribution": {}},
            sidecar_status={"status": "ready"},
            model_role_doctor={"status": "ready"},
            cost_status={"totals": {}},
            command_evidence=(
                CommandEvidence(
                    command="cmd",
                    status="passed",
                    summary="token=sk-should-not-appear",
                ),
            ),
        )
    )

    assert "sk-should-not-appear" not in markdown
    assert "[REDACTED]" in markdown

