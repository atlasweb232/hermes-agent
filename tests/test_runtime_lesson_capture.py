import json

from hermes_cli.runtime_lesson_capture import (
    RuntimeLessonObserver,
    ToolOutcome,
    append_lesson_capture_note,
    apply_runtime_failure_gate_to_final_response,
    capture_delegated_worker_runtime_failure,
    capture_supervisor_runtime_failure,
    classify_terminal_status,
    parse_terminal_failure,
    persist_runtime_lesson,
    redact_sensitive_text,
)
from hermes_state import SessionDB


def test_parse_terminal_failure_from_json_exit_code():
    assert parse_terminal_failure(json.dumps({"exit_code": 2, "stderr": "bad"})) is True
    assert parse_terminal_failure(json.dumps({"exit_code": 0, "stdout": "ok"})) is False


def test_classify_terminal_status_detects_timeout_and_empty_output():
    assert classify_terminal_status(json.dumps({"exit_code": 124, "error": "timed out"}), failed=True) == "timed_out"
    assert classify_terminal_status(json.dumps({"exit_code": 0, "output": ""}), failed=False) == "empty_output"
    assert classify_terminal_status(json.dumps({"exit_code": 0, "output": "4"}), failed=False) == "success"
    progress_only = (
        "2026-05-18T14:05:44Z worker=claude phase=starting cwd=/home/rakib\n"
        "2026-05-18T14:05:50Z worker=claude phase=completed exit_code=0"
    )
    assert (
        classify_terminal_status(
            json.dumps({"exit_code": 0, "output": progress_only}),
            failed=False,
            command='worker-router claude "two plus two"',
        )
        == "empty_output"
    )


def test_redacts_common_secret_shapes():
    text = "token=sk-abc123456789XYZ password=supersecret bot=123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    safe = redact_sensitive_text(text)

    assert "sk-abc" not in safe
    assert "supersecret" not in safe
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in safe
    assert "[REDACTED]" in safe


def test_observer_captures_claude_router_failure_then_direct_success():
    observer = RuntimeLessonObserver(min_failures=3)
    for command in (
        'worker-router claude "two plus two"',
        'worker-router claude -p "two plus two"',
        'worker-router claude --model sonnet "two plus two"',
    ):
        assert observer.observe(
            ToolOutcome(tool_name="terminal", command=command, failed=True)
        ) is None

    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='claude --model sonnet -p "two plus two"',
            failed=False,
            result_excerpt="4",
            session_id="session-1",
            cwd="/tmp/project",
        )
    )

    assert lesson is not None
    assert lesson.kind == "routing_hint"
    assert "worker-router claude" in lesson.claim
    assert lesson.evidence["failure_count"] == 3
    assert lesson.evidence["working_path"] == "claude --model sonnet -p"


def test_observer_does_not_emit_without_successful_alternative():
    observer = RuntimeLessonObserver(min_failures=1)

    assert observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router claude "two plus two"',
            failed=True,
        )
    ) is None
    assert observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='claude -p "two plus two"',
            failed=True,
        )
    ) is None


def test_observer_captures_generic_long_tool_loop_failure():
    observer = RuntimeLessonObserver(long_failure_seconds=30)

    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router watch agent',
            failed=True,
            result_excerpt="timed out",
            duration_seconds=120.0,
            session_id="session-loop",
            cwd="/tmp/project",
        )
    )

    assert lesson is not None
    assert lesson.kind == "supervisor_tool_loop_failure"
    assert lesson.evidence["failure_type"] == "supervisor_tool_loop_failure"
    assert lesson.evidence["command_family"] == "worker-router"
    assert lesson.evidence["requires_judge"] is True


def test_observer_captures_generic_evidence_mismatch_after_failed_route():
    observer = RuntimeLessonObserver(long_failure_seconds=30)
    observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router watch agent',
            failed=True,
            result_excerpt="timed out",
            duration_seconds=120.0,
        )
    )

    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='echo $((2+2))',
            failed=False,
            result_excerpt="4",
            duration_seconds=0.3,
        )
    )

    assert lesson is not None
    assert lesson.kind == "supervisor_evidence_mismatch"
    assert lesson.evidence["failed_command_family"] == "worker-router"
    assert lesson.evidence["substitute_command_family"] == "echo"
    assert lesson.evidence["operator_approval_required"] is True


def test_runtime_failure_gate_requires_disclosure_after_failed_worker():
    observer = RuntimeLessonObserver(long_failure_seconds=30)
    observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router claude "what is two plus two"',
            failed=True,
            result_excerpt="timed out",
            duration_seconds=120.0,
            status="timed_out",
        )
    )

    gate = observer.runtime_failure_gate()
    response = apply_runtime_failure_gate_to_final_response("Answer: 4", gate)

    assert gate.status == "degraded"
    assert gate.last_failed_family == "worker-router"
    assert "Worker delegation degraded" in response
    assert "supervisor fallback" in response
    assert "Answer: 4" in response


def test_runtime_failure_gate_clears_after_later_successful_worker():
    observer = RuntimeLessonObserver(long_failure_seconds=30)
    observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router claude "what is two plus two"',
            failed=True,
            status="timed_out",
        )
    )
    observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='codex exec "what is two plus two"',
            failed=False,
            result_excerpt="4",
            status="success",
        )
    )

    assert observer.runtime_failure_gate().status == "passed"


def test_observer_counts_hermes_worker_router_wrapper_failures():
    observer = RuntimeLessonObserver(min_failures=3)
    for command in (
        'hermes worker-router claude "two plus two"',
        'worker-router claude "two plus two"',
        'hermes worker-router claude --help',
    ):
        assert observer.observe(
            ToolOutcome(tool_name="terminal", command=command, failed=True)
        ) is None

    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='claude -p "two plus two" --model sonnet',
            failed=False,
            result_excerpt="4",
        )
    )

    assert lesson is not None
    assert lesson.evidence["failure_count"] == 3
    assert lesson.evidence["working_command"] == 'claude -p "two plus two" --model sonnet'


def test_persist_runtime_lesson_writes_memory_only(tmp_path):
    observer = RuntimeLessonObserver(min_failures=1)
    observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router claude "two plus two"',
            failed=True,
        )
    )
    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='claude --model sonnet -p "two plus two"',
            failed=False,
            result_excerpt="4",
        )
    )
    db = SessionDB(tmp_path / "state.db")

    capture = persist_runtime_lesson(db, lesson)

    assert capture["lesson_captured"] is True
    records = db.list_memory_records(kind="tool_routing_lesson", limit=5)
    assert records[0]["id"] == capture["record_id"]
    assert records[0]["payload_json"]["secret_safe"] is True
    assert db.list_meta_candidates(kind="routing_hint", limit=5) == []


def test_persist_generic_supervisor_failure_writes_supervisor_runtime_failure(tmp_path):
    observer = RuntimeLessonObserver(long_failure_seconds=30)
    lesson = observer.observe(
        ToolOutcome(
            tool_name="terminal",
            command='worker-router watch agent',
            failed=True,
            result_excerpt="timed out",
            duration_seconds=120.0,
        )
    )
    db = SessionDB(tmp_path / "state.db")

    capture = persist_runtime_lesson(db, lesson)

    assert capture["lesson_captured"] is True
    records = db.list_memory_records(kind="supervisor_runtime_failure", limit=5)
    assert records[0]["id"] == capture["record_id"]
    assert records[0]["payload_json"]["failure_type"] == "supervisor_tool_loop_failure"
    assert records[0]["payload_json"]["worker_family"] == "supervisor"
    assert records[0]["payload_json"]["requested_route"] == "worker-router"
    assert records[0]["payload_json"]["actual_route"] == "worker-router"
    assert records[0]["payload_json"]["latency_seconds"] == 120.0


def test_capture_supervisor_runtime_failure_rich_metadata_is_bounded_and_redacted(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    try:
        result = capture_supervisor_runtime_failure(
            db,
            failure_type="supervisor_tool_timeout",
            detector="test.supervisor",
            task_id="task-rich",
            tenant_id="tenant-a",
            repo_id="repo-a",
            worker_id="supervisor",
            worker_family="supervisor",
            requested_route="worker-router claude api_key=sk-abc123456789XYZ",
            actual_route="echo fallback",
            command_family="worker-router",
            status="timed_out",
            latency_seconds=121.5,
            allocation_refs=["hermes:allocation:alloc-rich:attempt-1"],
            evidence_refs=["hermes:runtime-lesson:rich"],
            validation_mismatch={"expected": "worker answer", "actual": "supervisor fallback", "password": "hunter2"},
            output_excerpt="token=sk-abc123456789XYZ\n" + "raw\n" * 200,
            session_id="session-rich",
            extra={"provider_log": "secret text", "safe": "ok"},
        )

        assert result["runtime_failure_captured"] is True
        record = db.list_memory_records(kind="supervisor_runtime_failure", limit=1)[0]
        payload = record["payload_json"]
        assert record["tenant_id"] == "tenant-a"
        assert record["repo_id"] == "repo-a"
        assert record["task_id"] == "task-rich"
        assert payload["failure_type"] == "supervisor_tool_timeout"
        assert payload["worker_family"] == "supervisor"
        assert "sk-abc" not in payload["requested_route"]
        assert "[REDACTED]" in payload["requested_route"]
        assert payload["actual_route"] == "echo fallback"
        assert payload["command_family"] == "worker-router"
        assert payload["status"] == "timed_out"
        assert payload["latency_seconds"] == 121.5
        assert payload["allocation_refs"] == ["hermes:allocation:alloc-rich:attempt-1"]
        assert payload["validation_mismatch"]["password"] == "[REDACTED]"
        serialized = json.dumps(payload)
        assert "sk-abc" not in serialized
        assert "hunter2" not in serialized
    finally:
        db.close()


def test_capture_delegated_worker_failure_persists_structured_record_without_raw_secret(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    try:
        capture = capture_delegated_worker_runtime_failure(
            db,
            task_id="task-131b",
            worker_id="subagent-2",
            route="delegate_task:codex",
            status="timeout",
            evidence_refs=["hermes:delegate:task-131b:subagent-2"],
            output_excerpt="token=sk-abc123456789XYZ\n" + "raw log line\n" * 200,
            validation_mismatch={"expected": "tests passed", "actual": "no output"},
            session_id="session-131b",
            expected_route="delegate_task:claude",
        )

        assert capture["runtime_failure_captured"] is True
        records = db.list_memory_records(kind="supervisor_runtime_failure", limit=1)
        record = records[0]
        payload = record["payload_json"]
        assert record["task_id"] == "task-131b"
        assert payload["task_id"] == "task-131b"
        assert payload["worker_id"] == "subagent-2"
        assert payload["route"] == "delegate_task:codex"
        assert payload["requested_route"] == "delegate_task:claude"
        assert payload["actual_route"] == "delegate_task:codex"
        assert payload["worker_family"] == "subagent-2"
        assert payload["command_family"] == "delegate_task"
        assert payload["status"] == "timeout"
        assert payload["evidence_refs"] == ["hermes:delegate:task-131b:subagent-2"]
        assert payload["validation_mismatch"]["expected"] == "tests passed"
        assert payload["validation_mismatch"]["actual"] == "no output"
        assert payload["route_substitution"] is True
        assert payload["validation_mismatch"]["expected_route"] == "delegate_task:claude"
        assert payload["validation_mismatch"]["actual_route"] == "delegate_task:codex"
        assert payload["secret_safe"] is True
        serialized = json.dumps(payload)
        assert "sk-abc" not in serialized
        assert len(payload["output_excerpt"]) < 900
    finally:
        db.close()


def test_append_lesson_capture_note_preserves_json_result():
    result = append_lesson_capture_note(
        json.dumps({"exit_code": 0, "stdout": "4"}),
        {
            "lesson_captured": True,
            "record_id": "memrec_1",
            "kind": "routing_hint",
            "claim": "prefer direct claude",
        },
    )

    parsed = json.loads(result)
    assert parsed["exit_code"] == 0
    assert parsed["runtime_lesson_capture"]["status"] == "captured"
    assert "candidate_id" not in parsed["runtime_lesson_capture"]


def test_agent_observer_hook_persists_lesson(tmp_path, monkeypatch):
    from run_agent import AIAgent

    db = SessionDB(tmp_path / "state.db")
    agent = object.__new__(AIAgent)
    agent._session_db = db
    agent.session_id = "session-hook-test"

    assert agent._observe_runtime_lesson(
        "terminal",
        {"command": 'worker-router claude "two plus two"', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 2, "stderr": "bad args"}),
        True,
    )
    assert agent._observe_runtime_lesson(
        "terminal",
        {"command": 'worker-router claude -p "two plus two"', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 2, "stderr": "bad args"}),
        True,
    )
    assert agent._observe_runtime_lesson(
        "terminal",
        {"command": 'worker-router claude --model sonnet "two plus two"', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 2, "stderr": "bad args"}),
        True,
    )
    result = agent._observe_runtime_lesson(
        "terminal",
        {"command": 'claude --model sonnet -p "two plus two"', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 0, "stdout": "4"}),
        False,
    )

    parsed = json.loads(result)
    assert parsed["runtime_lesson_capture"]["status"] == "captured"
    assert db.list_memory_records(kind="tool_routing_lesson", limit=1)
    assert db.list_meta_candidates(kind="routing_hint", limit=1) == []


def test_agent_observer_hook_persists_generic_supervisor_failure(tmp_path):
    from run_agent import AIAgent

    db = SessionDB(tmp_path / "state.db")
    agent = object.__new__(AIAgent)
    agent._session_db = db
    agent.session_id = "session-generic-hook-test"

    result = agent._observe_runtime_lesson(
        "terminal",
        {"command": 'worker-router watch agent', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 124, "stderr": "timed out"}),
        True,
        120.0,
    )

    parsed = json.loads(result)
    assert parsed["runtime_lesson_capture"]["status"] == "captured"
    records = db.list_memory_records(kind="supervisor_runtime_failure", limit=1)
    assert records[0]["payload_json"]["failure_type"] == "supervisor_tool_loop_failure"


def test_agent_runtime_failure_gate_discloses_worker_degradation(tmp_path):
    from run_agent import AIAgent

    db = SessionDB(tmp_path / "state.db")
    agent = object.__new__(AIAgent)
    agent._session_db = db
    agent.session_id = "session-runtime-gate-test"
    agent._observe_runtime_lesson(
        "terminal",
        {"command": 'worker-router claude "what is two plus two"', "workdir": str(tmp_path)},
        json.dumps({"exit_code": 124, "error": "timed out"}),
        True,
        120.0,
    )

    response = agent._apply_runtime_failure_gate_to_final_response("The answer is 4.")

    assert "Worker delegation degraded" in response
    assert "worker-router" in response
    assert "The answer is 4." in response


def test_agent_delegate_task_result_captures_child_timeout_before_gate(tmp_path):
    from run_agent import AIAgent

    db = SessionDB(tmp_path / "state.db")
    agent = object.__new__(AIAgent)
    agent._session_db = db
    agent.session_id = "session-delegate-runtime"
    agent._current_task_id = "task-delegate-runtime"
    result = json.dumps(
        {
            "results": [
                {
                    "task_index": 0,
                    "status": "timeout",
                    "summary": None,
                    "error": "token=sk-abc123456789XYZ child timed out",
                    "exit_reason": "timeout",
                }
            ]
        }
    )

    agent._capture_delegate_runtime_failures({"role": "worker"}, result)

    records = db.list_memory_records(kind="supervisor_runtime_failure", limit=1)
    payload = records[0]["payload_json"]
    assert records[0]["task_id"] == "task-delegate-runtime"
    assert payload["worker_id"] == "subagent-0"
    assert payload["route"] == "delegate_task:worker"
    assert payload["status"] == "timeout"
    assert payload["evidence_refs"] == ["hermes:delegate:task-delegate-runtime:subagent-0"]
    assert payload["validation_mismatch"]["exit_reason"] == "timeout"
    assert "sk-abc" not in json.dumps(payload)


def test_agent_delegate_task_injects_bounded_empty_output_advisory(tmp_path, monkeypatch):
    from run_agent import AIAgent

    db = SessionDB(tmp_path / "state.db")
    db.upsert_meta_candidate(
        candidate_id="metacand_empty_output",
        kind="recovery_hint",
        claim="Repeated empty output from codex; request artifact refs before accepting completion.",
        evidence_json={
            "policy_type": "supervisor_runtime_failure_advisory",
            "mode": "advisory",
            "failure_classifications": ["empty_output"],
            "payload": {
                "tenant_id": "atlas",
                "repo_id": "hermes-agent",
                "task_id": "task-delegate-runtime",
                "worker_id": "subagent-0",
                "route": "delegate_task:codex",
                "command_family": "delegate_task",
                "status": "empty_output",
                "output_excerpt": "api_key=sk-secret123456789\n" + ("no summary " * 200),
            },
            "approved_for_enforcement": False,
        },
        score=0.91,
        status="approved",
        tenant_id="atlas",
        repo_id="hermes-agent",
    )
    agent = object.__new__(AIAgent)
    agent._session_db = db
    agent.session_id = "session-delegate-runtime"
    agent._current_task_id = "task-delegate-runtime"
    agent.tenant_id = "atlas"
    agent.repo_id = "hermes-agent"

    captured = {}

    def fake_delegate_task(**kwargs):
        captured.update(kwargs)
        return json.dumps({"results": [{"task_index": 0, "status": "success", "summary": "done"}]})

    monkeypatch.setattr("tools.delegate_tool.delegate_task", fake_delegate_task)
    monkeypatch.setattr("hermes_cli.completion_gate.run_completion_gate", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("skip")))

    agent._dispatch_delegate_task({"goal": "Fix the failing test", "role": "codex", "context": "Existing context."})

    injected = captured["context"]
    assert "Runtime failure advisories" in injected
    assert "Repeated empty output" in injected
    assert "advisory only" in injected
    assert "sk-secret" not in injected
    assert len(injected) < 700
