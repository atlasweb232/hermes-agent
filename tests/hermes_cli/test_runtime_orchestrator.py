import json
import sys
from pathlib import Path
from unittest.mock import patch

from hermes_cli.runtime_orchestrator import (
    create_planner_packet,
    discover_speckit_artifacts,
    initialize_task,
    validate_completion,
    validate_worker_delegation,
)
from hermes_cli.runtime_packets import (
    SessionSummary,
    ValidationReport,
    WorkerDelegationPacket,
)


def test_dashboard_intake_requires_clarification_for_missing_repo_and_done_state():
    result = initialize_task(
        request="Please add the TinyFish form fill feature",
        source="dashboard",
    )

    assert result.validation.valid is True
    assert result.task_packet.requires_speckit is True
    assert result.task_packet.status == "needs_clarification"
    assert "repository" in result.task_packet.clarifications[0].lower()
    assert any("done" in q.lower() for q in result.task_packet.clarifications)


def test_speckit_skip_requires_recorded_reason():
    result = initialize_task(
        request="Implement a feature",
        source="cli",
        repo_id="hermes-agent",
        skip_speckit=True,
        skip_reason="user requested emergency patch",
    )

    assert result.validation.valid is True
    assert result.task_packet.requires_speckit is False
    assert result.task_packet.skip_reason == "user requested emergency patch"


def test_create_planner_packet_requires_no_clarification():
    result = initialize_task(
        request="Implement a feature",
        source="dashboard",
    )

    try:
        create_planner_packet(result.task_packet, branch_name="132-learning-memory-runtime")
    except ValueError as exc:
        assert "clarification" in str(exc)
    else:
        raise AssertionError("expected planner packet creation to fail")


def test_create_planner_packet_for_valid_speckit_task():
    result = initialize_task(
        request="Implement the runtime protocol",
        source="cli",
        repo_id="hermes-agent",
        success_criteria=["runtime packets validate"],
    )

    planner = create_planner_packet(
        result.task_packet,
        branch_name="132-learning-memory-runtime",
    )

    assert planner.validate().valid is True
    assert planner.task_packet_id == result.task_packet.id
    assert "tasks.md" in planner.required_artifacts


def test_worker_delegation_validation_blocks_missing_required_fields():
    packet = WorkerDelegationPacket(
        id="delegate_1",
        task_packet_id="taskpkt_1",
        worker_id="claude",
        worker_kind="claude_code",
        repo_id="hermes-agent",
        branch_name="132-learning-memory-runtime",
        worktree_path="/tmp/wt",
        objective="",
        owned_files=[],
        constraints=[],
        validation_commands=[],
        memory_packet_id="mempkt_1",
        return_schema={},
    )

    validation = validate_worker_delegation(packet)

    assert validation.valid is False
    assert "objective" in validation.missing
    assert "owned_files" in validation.missing
    assert "return_schema" in validation.missing


def test_completion_gate_requires_validated_artifacts_and_summary(tmp_path):
    feature_dir = tmp_path / "specs" / "001-demo"
    feature_dir.mkdir(parents=True)
    for name in ("spec.md", "plan.md", "tasks.md"):
        (feature_dir / name).write_text("ok", encoding="utf-8")
    artifact_set = discover_speckit_artifacts(
        feature_dir,
        task_packet_id="taskpkt_1",
        branch_name="001-demo",
    )
    report = ValidationReport(
        id="val_1",
        task_packet_id="taskpkt_1",
        artifact_set_id=artifact_set.id,
        worker_result_ids=["result_1"],
        git_diff_summary="diff",
        test_results={"status": "passed"},
        requirement_coverage={"T001": "done"},
        status="passed",
    )
    summary = SessionSummary(
        id="summary_1",
        task_packet_id="taskpkt_1",
        master_instructions="do the work",
        decisions=["used speckit"],
        delegations=["claude"],
        validation_report_id=report.id,
        memory_outcome="none",
        commit_refs=["abc123"],
    )

    validation = validate_completion(
        artifact_set=artifact_set,
        validation_report=report,
        session_summary=summary,
    )

    assert validation.valid is True


def test_runtime_task_init_cli_json(capsys):
    from hermes_cli import main as hermes_main

    argv = [
        "hermes",
        "runtime",
        "task",
        "init",
        "--request",
        "Implement runtime orchestration",
        "--repo-id",
        "hermes-agent",
        "--success-criteria",
        "tests pass",
        "--json",
    ]

    with patch.object(sys, "argv", argv):
        hermes_main.main()

    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "created"
    assert data["requires_speckit"] is True
    assert data["needs_clarification"] is False


def test_runtime_validate_cli_json(tmp_path, capsys):
    from hermes_cli import main as hermes_main

    feature_dir = tmp_path / "specs" / "001-demo"
    feature_dir.mkdir(parents=True)
    for name in ("spec.md", "plan.md", "tasks.md"):
        (feature_dir / name).write_text("ok", encoding="utf-8")

    argv = [
        "hermes",
        "runtime",
        "validate",
        "--task-id",
        "taskpkt_1",
        "--feature-dir",
        str(feature_dir),
        "--branch-name",
        "001-demo",
        "--json",
    ]

    with patch.object(sys, "argv", argv):
        hermes_main.main()

    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "passed"
    assert data["validation"]["valid"] is True

