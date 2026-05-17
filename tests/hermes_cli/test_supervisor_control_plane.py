from pathlib import Path
import json
import sys
from unittest.mock import patch

from hermes_cli.supervisor_control_plane import (
    apply_override_action,
    assess_task_convergence,
    create_recovery_packet,
    create_task_ledger_entry,
    evaluate_task_goal_continuation,
    ensure_supervisor_control_schema,
    get_task_ledger_entry,
    goal_continuation_allowed,
    list_task_ledger_entries,
    list_worker_heartbeats,
    record_worker_heartbeat,
    set_task_goal,
)
from hermes_state import SessionDB


def _make_db(tmp_path: Path) -> SessionDB:
    return SessionDB(db_path=tmp_path / "state.db")


def test_supervisor_task_ledger_schema_and_round_trip(tmp_path):
    db = _make_db(tmp_path)
    try:
        ensure_supervisor_control_schema(db)
        ensure_supervisor_control_schema(db)

        entry = create_task_ledger_entry(
            db,
            task_id="task_1",
            tenant_id="atlas",
            repo_id="repo-a",
            task_description="Migrate a private repo",
            worker_id="codex",
            worker_kind="worker",
            lease_owner="codex",
            lease_seconds=60,
            retry_budget=2,
            spec_kit_refs=["spec.md", "tasks.md"],
            git_refs=["branch:132-learning-memory-runtime"],
            metadata={"supervisor_packet_ref": "packet_1"},
            now=100.0,
        )

        assert entry.state == "running"
        assert entry.lease_expires_at == 160.0
        assert entry.retry_budget == 2
        assert entry.spec_kit_refs == ["spec.md", "tasks.md"]
        assert entry.git_refs == ["branch:132-learning-memory-runtime"]
        assert entry.metadata_json["supervisor_packet_ref"] == "packet_1"
        assert list_task_ledger_entries(db, tenant_id="atlas", repo_id="repo-a")[0].task_id == "task_1"
    finally:
        db.close()


def test_stale_heartbeat_and_lease_reclaim_are_detected(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(
            db,
            task_id="task_stale",
            tenant_id="atlas",
            repo_id="repo-a",
            worker_id="codex",
            lease_seconds=10,
            now=100.0,
        )
        record_worker_heartbeat(
            db,
            task_id="task_stale",
            worker_id="codex",
            progress_signature="p1",
            lease_seconds=10,
            now=105.0,
        )

        result = assess_task_convergence(
            db,
            task_id="task_stale",
            config={"supervisor": {"control_plane": {"heartbeat_timeout_seconds": 20}}},
            now=200.0,
        )

        assert result.status == "reclaimable"
        assert result.reclaimable is True
        assert "lease_expired" in result.reasons
        assert "heartbeat_stale" in result.reasons
        assert result.recommended_action == "reclaim"
    finally:
        db.close()


def test_loop_and_drift_detector_repeated_signatures(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(db, task_id="task_loop", worker_id="claude", retry_budget=5, now=100.0)
        for i in range(3):
            record_worker_heartbeat(
                db,
                task_id="task_loop",
                worker_id="claude",
                status="failed",
                progress_signature="same-progress",
                command_signature="worker-router claude",
                error_signature="unknown option",
                git_head="abc123",
                test_signature="not-run",
                now=110.0 + i,
            )

        result = assess_task_convergence(
            db,
            task_id="task_loop",
            config={"supervisor": {"control_plane": {"heartbeat_timeout_seconds": 999}}},
            now=120.0,
        )

        assert "no_progress_loop" in result.reasons
        assert "repeated_error_signature" in result.reasons
        assert "repeated_command_signature" in result.reasons
    finally:
        db.close()


def test_recovery_packet_preserves_evidence_and_recommends_next_worker(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(
            db,
            task_id="task_recover",
            worker_id="codex",
            git_refs=["branch:feature-x", "commit:abc"],
            now=100.0,
        )
        record_worker_heartbeat(
            db,
            task_id="task_recover",
            worker_id="codex",
            status="failed",
            command_signature="pytest tests/foo.py",
            error_signature="AssertionError",
            metadata={"validation_failure": "pytest failed", "memory_packet_id": "mempkt_1"},
            now=110.0,
        )

        packet = create_recovery_packet(
            db,
            task_id="task_recover",
            reason="validation failed",
            config={"supervisor": {"control_plane": {"worker_fallback_order": ["codex", "claude-code", "deepseek"]}}},
        )

        assert packet.status == "ready"
        assert packet.failed_commands == ["pytest tests/foo.py"]
        assert packet.error_signatures == ["AssertionError"]
        assert packet.validation_failures == ["pytest failed"]
        assert packet.memory_packet_refs == ["mempkt_1"]
        assert packet.git_refs == ["branch:feature-x", "commit:abc"]
        assert packet.next_worker_recommendation == "claude-code"
    finally:
        db.close()


def test_override_actions_reclaim_reassign_and_goal_boundaries(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(db, task_id="task_override", worker_id="codex", retry_budget=3)

        reclaim = apply_override_action(
            db,
            task_id="task_override",
            action="reclaim",
            operator="rakib",
            reason="stale heartbeat",
        )
        assert reclaim.previous_state == "running"
        assert reclaim.new_state == "reclaimed"
        assert goal_continuation_allowed(db, task_id="task_override")["allowed"] is False

        reassign = apply_override_action(
            db,
            task_id="task_override",
            action="reassign",
            operator="rakib",
            reason="fallback worker",
            worker_id="claude-code",
        )
        assert reassign.new_state == "reassigned"
        entry = get_task_ledger_entry(db, "task_override")
        assert entry is not None
        assert entry.worker_id == "claude-code"
        assert entry.retry_count == 2
        assert goal_continuation_allowed(db, task_id="task_override")["reason"].endswith(":reassigned")
    finally:
        db.close()


def test_goal_continuation_allowed_for_healthy_running_task(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(db, task_id="task_goal", worker_id="codex", goal="finish migration")

        result = goal_continuation_allowed(db, task_id="task_goal")

        assert result["allowed"] is True
        assert result["reason"] == "goal_is_supervisor_owned"
    finally:
        db.close()


def test_task_goal_continuation_uses_supervisor_owned_judge(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(
            db,
            task_id="task_goal_eval",
            worker_id="codex",
            goal="finish branch inspection",
            goal_max_turns=3,
        )

        result = evaluate_task_goal_continuation(
            db,
            task_id="task_goal_eval",
            last_response="I inspected one file but need another step.",
            judge_fn=lambda _goal, _response: ("continue", "more inspection needed", False),
        )

        assert result.should_continue is True
        assert result.verdict == "continue"
        assert "Continuing supervisor task goal" in result.continuation_prompt
        entry = get_task_ledger_entry(db, "task_goal_eval")
        assert entry.goal_json["turns_used"] == 1
        assert entry.goal_json["continuation_count"] == 1
    finally:
        db.close()


def test_task_goal_judge_cannot_override_reclaimed_task(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(db, task_id="task_goal_blocked", worker_id="codex", goal="finish")
        apply_override_action(db, task_id="task_goal_blocked", action="reclaim", reason="stale")

        result = evaluate_task_goal_continuation(
            db,
            task_id="task_goal_blocked",
            last_response="done",
            judge_fn=lambda _goal, _response: ("done", "looks complete", False),
        )

        assert result.should_continue is False
        assert result.verdict == "blocked"
        assert result.reason.endswith(":reclaimed")
        assert get_task_ledger_entry(db, "task_goal_blocked").goal_json["status"] == "active"
    finally:
        db.close()


def test_task_goal_can_be_set_after_task_creation(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(db, task_id="task_set_goal", worker_id="codex")
        entry = set_task_goal(db, task_id="task_set_goal", goal="produce validation evidence", max_turns=2)

        assert entry.goal_json["goal"] == "produce validation evidence"
        assert entry.goal_json["max_turns"] == 2
        assert goal_continuation_allowed(db, task_id="task_set_goal")["allowed"] is True
    finally:
        db.close()


def test_task_goal_done_does_not_auto_complete_supervisor_task(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(db, task_id="task_goal_done", worker_id="codex", goal="finish")

        result = evaluate_task_goal_continuation(
            db,
            task_id="task_goal_done",
            last_response="finished",
            judge_fn=lambda _goal, _response: ("done", "goal satisfied", False),
        )

        entry = get_task_ledger_entry(db, "task_goal_done")
        assert result.should_continue is False
        assert result.status == "done"
        assert entry.state == "running"
        assert entry.goal_json["status"] == "done"
        assert entry.goal_json["history"][0]["verdict"] == "done"
    finally:
        db.close()


def test_task_goal_pauses_when_turn_budget_is_exhausted(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(
            db,
            task_id="task_goal_budget",
            worker_id="codex",
            goal="finish",
            goal_max_turns=1,
        )

        result = evaluate_task_goal_continuation(
            db,
            task_id="task_goal_budget",
            last_response="not finished",
            judge_fn=lambda _goal, _response: ("continue", "needs another step", False),
        )

        entry = get_task_ledger_entry(db, "task_goal_budget")
        assert result.should_continue is False
        assert result.status == "paused"
        assert entry.goal_json["status"] == "paused"
        assert "turn budget exhausted" in entry.goal_json["paused_reason"]
    finally:
        db.close()


def test_upsert_without_goal_preserves_existing_task_goal(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(db, task_id="task_goal_preserve", worker_id="codex", goal="finish")
        create_task_ledger_entry(
            db,
            task_id="task_goal_preserve",
            worker_id="codex",
            task_description="updated description",
        )

        entry = get_task_ledger_entry(db, "task_goal_preserve")
        assert entry.task_description == "updated description"
        assert entry.goal_json["goal"] == "finish"
    finally:
        db.close()


def test_heartbeat_history_is_ordered_newest_first(tmp_path):
    db = _make_db(tmp_path)
    try:
        create_task_ledger_entry(db, task_id="task_hb", worker_id="codex")
        record_worker_heartbeat(db, task_id="task_hb", worker_id="codex", progress_signature="first", now=1.0)
        record_worker_heartbeat(db, task_id="task_hb", worker_id="codex", progress_signature="second", now=2.0)

        rows = list_worker_heartbeats(db, task_id="task_hb")

        assert [row.progress_signature for row in rows] == ["second", "first"]
    finally:
        db.close()


def test_runtime_control_cli_json_smoke(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(home))
    import hermes_state

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", home / "state.db")
    from hermes_cli import main as hermes_main

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "runtime",
            "control",
            "create",
            "--task-id",
            "task_cli",
            "--tenant-id",
            "atlas",
            "--repo-id",
            "repo-a",
            "--description",
            "CLI control task",
            "--goal",
            "finish cli control task",
            "--worker",
            "codex",
            "--json",
        ],
    ):
        hermes_main.main()
    created = json.loads(capsys.readouterr().out)
    assert created["task_id"] == "task_cli"
    assert created["state"] == "running"
    assert created["goal_json"]["goal"] == "finish cli control task"

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "runtime",
            "control",
            "heartbeat",
            "--task-id",
            "task_cli",
            "--worker",
            "codex",
            "--progress",
            "p1",
            "--json",
        ],
    ):
        hermes_main.main()
    heartbeat = json.loads(capsys.readouterr().out)
    assert heartbeat["task_id"] == "task_cli"

    with patch.object(sys, "argv", ["hermes", "runtime", "control", "status", "--task-id", "task_cli", "--json"]):
        hermes_main.main()
    status = json.loads(capsys.readouterr().out)
    assert status["heartbeat_at"] is not None

    with patch.object(sys, "argv", ["hermes", "runtime", "control", "goal", "--task-id", "task_cli", "--json"]):
        hermes_main.main()
    goal_status = json.loads(capsys.readouterr().out)
    assert goal_status["goal_json"]["goal"] == "finish cli control task"

    with patch.object(
        sys,
        "argv",
        [
            "hermes",
            "runtime",
            "control",
            "goal",
            "--task-id",
            "task_cli",
            "--last-response",
            "not done yet",
            "--json",
        ],
    ):
        with patch("hermes_cli.supervisor_control_plane.evaluate_task_goal_continuation") as mocked:
            mocked.return_value.to_dict.return_value = {
                "task_id": "task_cli",
                "status": "continue",
                "should_continue": True,
            }
            hermes_main.main()
    goal_result = json.loads(capsys.readouterr().out)
    assert goal_result["should_continue"] is True
