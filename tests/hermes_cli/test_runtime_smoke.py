from hermes_cli.runtime_smoke import run_allocator_comparison_smoke


def test_allocator_comparison_smoke_reports_branch_value():
    result = run_allocator_comparison_smoke(upstream_ref=None)

    assert result.status == "passed"
    assert result.allocator_decision["action"] == "dispatch"
    assert result.allocator_decision["worker_id"] == "codex"
    assert result.branch_capabilities["goal_allocator"] is True


def test_allocator_comparison_smoke_covers_phase_13_runtime_invariants():
    result = run_allocator_comparison_smoke(upstream_ref=None)
    payload = result.to_dict()

    assert payload["status"] == "passed"
    assert payload["scenario"] == "phase_13_self_healing_runtime_smoke"
    assert payload["repeated_failed_loop_result"]["status"] == "passed"
    assert payload["repeated_failed_loop_result"]["decision"]["action"] in {"dispatch", "pause"}
    assert payload["repeated_failed_loop_result"]["decision"]["worker_id"] != "claude-code"
    assert payload["repeated_failed_loop_result"]["same_worker_retry_count"] == 0
    assert payload["repeated_failed_loop_result"]["second_health_check_recovery_candidates"] == 0

    foreground = payload["foreground_responsiveness_result"]
    assert foreground["status"] == "passed"
    assert foreground["health_foreground_callback_called"] is False
    assert foreground["progress_foreground_callback_called"] is False
    assert foreground["elapsed_seconds"] < 0.5
    assert foreground["progress_sidecar_authorities"]["complete_tasks"] is False
    assert foreground["progress_sidecar_authorities"]["mutate_routing"] is False

    restart = payload["restart_resume_result"]
    assert restart["status"] == "passed"
    assert restart["expensive_sidecar_called"] is False
    assert restart["decisions"]["task_resume"]["decision"] == "resume"
    assert restart["decisions"]["task_unknown"]["decision"] == "request_status"
    assert restart["decisions"]["task_cooling"]["decision"] == "pause"
    assert restart["cooldown_preserved_until"] == 5_000
    assert restart["unknown_in_flight_safe_to_dispatch"] is False

    assert payload["raw_worker_streams_result"]["status"] == "passed"
    assert payload["raw_worker_streams_result"]["stream_event_store_only"] is True
    assert payload["raw_worker_streams_result"]["supervisor_context_appended"] is False
    assert payload["raw_worker_streams_result"]["raw_stream_in_supervisor_context"] is False
