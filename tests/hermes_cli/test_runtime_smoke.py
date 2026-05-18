from hermes_cli.runtime_smoke import run_allocator_comparison_smoke


def test_allocator_comparison_smoke_reports_branch_value():
    result = run_allocator_comparison_smoke(upstream_ref=None)

    assert result.status == "passed"
    assert result.allocator_decision["action"] == "dispatch"
    assert result.allocator_decision["worker_id"] == "codex"
    assert result.branch_capabilities["goal_allocator"] is True
