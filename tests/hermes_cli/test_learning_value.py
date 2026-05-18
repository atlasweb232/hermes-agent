from hermes_cli.global_memory import persist_global_lesson
from hermes_cli.learning_value import (
    LowEndEvalRun,
    build_learning_value_report,
    compare_low_end_eval_runs,
    count_repeated_error_signatures,
    run_learning_value_probe,
)
from hermes_state import SessionDB


def _db(tmp_path):
    return SessionDB(db_path=tmp_path / "state.db")


def _event():
    return {
        "event_id": "evt-claude-router",
        "tenant_id": "atlas",
        "tool": "claude",
        "task_type": "worker_routing",
        "failure_signature": "cmd:worker-router:claude:parse-error",
        "success_signature": "cmd:claude:sonnet:print-mode",
        "normalized_text": "worker-router claude failed before direct claude sonnet print mode succeeded",
    }


def _lesson():
    return {
        "id": "global-claude-router-repair",
        "approval_state": "approved",
        "scope": "global",
        "visibility": "global_candidate",
        "sensitivity": "internal",
        "claim_type": "command_repair_policy",
        "tenant_id": "atlas",
        "tool": "claude",
        "task_type": "worker_routing",
        "failure_signature": "cmd:worker-router:claude:parse-error",
        "success_signature": "cmd:claude:sonnet:print-mode",
        "normalized_text": "Prefer direct Claude Code invocation after worker-router claude parse errors.",
        "confidence": 0.91,
        "approval_provenance": {"judge_id": "judge-1", "operator_approved": True},
        "evidence_refs": ["global://evidence/claude-router"],
        "cross_tenant_shareable": True,
    }


def test_count_repeated_error_signatures_counts_extra_repeats_only():
    events = [
        {"command": "worker-router claude one", "error_signature": "parse", "status": "failed"},
        {"command": "worker-router claude two", "error_signature": "parse", "status": "failed"},
        {"command": "worker-router claude three", "error_signature": "parse", "status": "failed"},
        {"command": "claude -p ok", "status": "success"},
    ]

    assert count_repeated_error_signatures(events) == 2


def test_learning_value_probe_uses_persisted_memory_without_llm_sidecars(tmp_path):
    db = _db(tmp_path)
    try:
        persist_global_lesson(db, _lesson())

        result = run_learning_value_probe(
            db,
            _event(),
            worker_model="cheap-worker",
            worker_provider="deepseek",
            outcome="success",
            validation_complete=True,
            tool_events=[
                {"command": "worker-router claude one", "error_signature": "parse", "status": "failed"},
                {"command": "worker-router claude two", "error_signature": "parse", "status": "failed"},
                {"command": "claude --model sonnet -p ok", "status": "success"},
            ],
        )

        report = result["report"]
        assert report["worker_model"] == "cheap-worker"
        assert report["global_lesson_hits"] >= 1
        assert report["memory_hits"] == 1
        assert report["hot_cache_hits"] == 1
        assert report["skipped_curator_count"] == 1
        assert report["skipped_dreaming_count"] == 1
        assert report["estimated_packet_tokens"] > 0
        assert report["repeated_error_count"] == 1
        assert report["memory_effect"] == "helped"
        assert result["precuration"]["decision"]["should_run_expensive_curator"] is False
    finally:
        db.close()


def test_learning_value_report_marks_memory_unused_without_hits():
    report = build_learning_value_report(
        _event(),
        hydration={"status": "empty", "advisory_items": [], "hot_cache_hits": [], "estimated_tokens": 0},
        precuration={"decision": {"should_run_expensive_curator": True}, "metrics": {"global_lesson_miss": 1}},
        outcome="failed",
        validation_complete=False,
    )

    assert report.memory_effect == "unused"
    assert report.global_lesson_misses == 1
    assert report.skipped_curator_count == 0


def test_low_end_eval_comparison_reports_memory_assisted_improvement():
    baseline = LowEndEvalRun(
        id="base",
        task_id="task-1",
        mode="baseline",
        worker_model="cheap",
        status="failed",
        tool_error_count=5,
        repeated_error_count=3,
        validation_complete=False,
        estimated_tokens=1000,
        wall_time_seconds=120,
        escalation_count=2,
        memory_hits=0,
    )
    assisted = LowEndEvalRun(
        id="assist",
        task_id="task-1",
        mode="memory_assisted",
        worker_model="cheap",
        status="success",
        tool_error_count=1,
        repeated_error_count=0,
        validation_complete=True,
        estimated_tokens=700,
        wall_time_seconds=45,
        escalation_count=0,
        memory_hits=1,
    )

    comparison = compare_low_end_eval_runs(baseline, assisted)

    assert comparison.improved is True
    assert comparison.verdict == "memory_assisted_improved"
    assert comparison.deltas["tool_error_reduction"] == 4
    assert comparison.deltas["repeated_error_reduction"] == 3

