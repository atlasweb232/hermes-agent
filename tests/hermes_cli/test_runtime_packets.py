from hermes_cli.runtime_packets import (
    PlannerPacket,
    SupervisorTaskPacket,
    ValidationReport,
    WorkerDelegationPacket,
)


def test_supervisor_task_packet_requires_skip_reason_when_speckit_disabled():
    packet = SupervisorTaskPacket(
        id="taskpkt_1",
        source="dashboard",
        raw_request_summary="fix the app",
        task_type="implementation",
        complexity="standard",
        requires_speckit=False,
    )

    result = packet.validate()

    assert result.valid is False
    assert "skip_reason" in result.errors[0]


def test_worker_delegation_packet_rejects_missing_owned_files_and_validation():
    packet = WorkerDelegationPacket(
        id="delegate_1",
        task_packet_id="taskpkt_1",
        worker_id="claude",
        worker_kind="claude_code",
        repo_id="atlasweb-mini",
        branch_name="132-learning-memory-runtime",
        worktree_path="/tmp/wt",
        objective="implement feature",
        owned_files=[],
        constraints=["do not revert unrelated changes"],
        validation_commands=[],
        memory_packet_id="mempkt_1",
        return_schema={"summary": "string"},
    )

    result = packet.validate()

    assert result.valid is False
    assert "owned_files" in result.missing
    assert "validation_commands" in result.missing


def test_planner_and_validation_packets_accept_required_fields():
    planner = PlannerPacket(
        id="planner_1",
        task_packet_id="taskpkt_1",
        planner_role="planner",
        preferred_model="gpt-5.5",
        branch_name="132-learning-memory-runtime",
        required_artifacts=["spec.md", "plan.md", "tasks.md"],
        return_schema={"artifacts": "object"},
    )
    validation = ValidationReport(
        id="val_1",
        task_packet_id="taskpkt_1",
        artifact_set_id="specart_1",
        worker_result_ids=["result_1"],
        git_diff_summary="changed runtime packets",
        test_results={"status": "passed"},
        requirement_coverage={"T005": "done"},
        status="passed",
    )

    assert planner.validate().valid is True
    assert validation.validate().valid is True

